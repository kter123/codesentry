"""Joern 引擎（agent.md §4.1 全场景深度引擎；§4.2 六语言矩阵）。

M1.5 真实现：joern-parse 建 CPG → joern -c 执行生成的 Scala 查询脚本 → 解析 alert JSON。
CPG 落 CODESENTRY_WORK_DIR（挂载盘）；查询脚本仅用 joern 内置 API（不移植 CodeQL 查询，§3）。
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from codesentry.models import EngineResult, Finding, Severity

JOERN_LANG = {
    "python": "PYTHONSRC",
    "java": "JAVASRC",
    "javascript": "JSSRC",
    "typescript": "JSSRC",
    "go": "GOSRC",
    "c": "C",
    "cpp": "C",
    "php": "PHPSRC",
}

_QUERY_SCRIPT = """
@volatile var out = List.empty[Map[String, Any]]

def add(rule: String, cwe: Int, sev: String, file: String, line: Int, msg: String): Unit = {
  out = out :+ Map("rule" -> rule, "cwe" -> cwe, "sev" -> sev,
                   "file" -> file, "line" -> line, "message" -> msg)
}

// —— 自研通用 sink 查询（Apache-2.0 原创；M3 按语言/框架深化）——
cpg.call.name("(exec|system|popen|os\\.system|subprocess\\.(call|run|Popen)|Runtime\\.getRuntime.*exec)").l.foreach { c =>
  add("joern.cmd-injection", 78, "high",
      c.method.filename.headOption.getOrElse(""), c.line.headOption.getOrElse(-1),
      "call to command sink: " + c.name)
}
cpg.call.name("(eval|os\\.popen|phpeval)").l.foreach { c =>
  add("joern.eval-sink", 95, "high",
      c.method.filename.headOption.getOrElse(""), c.line.headOption.getOrElse(-1),
      "call to eval sink: " + c.name)
}
cpg.call.name("(requests\\.(get|post)|urllib\\.request\\.urlopen|fetch|HttpClient.*send)").l.where(
  _.argument.code("(parameters|args|request\\.args\\.|query_params|Query\\(|form|body)").nonEmpty
).l.foreach { c =>
  add("joern.ssrf-sink", 918, "high",
      c.method.filename.headOption.getOrElse(""), c.line.headOption.getOrElse(-1),
      "request with possibly user-controlled URL: " + c.name)
}
cpg.literal.code("(\\\"/.*\\\"\\s*\\+|\"/.*\"\\s*\\+)").l.foreach { l =>
  add("joern.path-prefix-literal", 22, "low",
      l.method.filename.headOption.getOrElse(""), l.line.headOption.getOrElse(-1),
      "path built by string concat; review origin")
}

println("__RULES_OUT__" + write(out.map(m => m.asJava).asJava))
"""

_OUT_MARK = "__RULES_OUT__"


def _parse_alerts(stdout: str) -> list[Finding]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_OUT_MARK):
            raw = json.loads(line[len(_OUT_MARK) :])
            out: list[Finding] = []
            for m in raw:
                line_no = int(m.get("line", -1))
                if line_no < 1:
                    continue
                out.append(
                    Finding(
                        rule_id=str(m.get("rule", "joern.custom")),
                        cwe=int(m.get("cwe", 610)),
                        severity=str(m.get("sev") or "medium"),  # type: ignore[arg-type]  # 查询脚本只产 high/low/medium
                        confidence=0.7,
                        file=str(m.get("file", "")),
                        line=line_no,
                        message=str(m.get("message", "")),
                        engine="joern",
                        taint_metadata={"source": "joern-cpg"},
                    )
                )
            return out
    return []


def run_joern(
    repo: str,
    lang: str,
    out_dir: str,
    *,
    timeout: int = 3600,
    joern_bin: str | None = None,
) -> EngineResult:
    joern_name = joern_bin or os.environ.get("CODESENTRY_JOERN_BIN", "joern")
    joern_parse_name = shutil.which("joern-parse") or shutil.which(
        str(Path(shutil.which(joern_name) or "").parent / "joern-parse")
    )
    if not joern_name or shutil.which(joern_name) is None:
        return EngineResult(engine="joern", status="unavailable", reason=f"binary not found: {joern_name}")
    if not joern_parse_name:
        return EngineResult(engine="joern", status="unavailable", reason="binary not found: joern-parse")
    frontend = JOERN_LANG.get(lang)
    if frontend is None:
        return EngineResult(engine="joern", status="unavailable", reason=f"unsupported language: {lang}")

    work = Path(os.environ.get("CODESENTRY_WORK_DIR", ".codesentry")) / "cpg"
    work.mkdir(parents=True, exist_ok=True)
    cpg_out = work / (Path(repo).name + ".bin")

    # 1) CPG 构建
    r1 = subprocess.run(
        [joern_parse_name, repo, "--output", str(cpg_out), "-J", str(frontend)],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if r1.returncode != 0:
        return EngineResult(engine="joern", status="crashed", reason=f"joern-parse exit {r1.returncode}: {r1.stderr[-400:]}")

    # 2) 查询脚本执行
    with tempfile.NamedTemporaryFile("w", suffix=".sc", delete=False) as f:
        f.write(_QUERY_SCRIPT)
        script_path = f.name
    try:
        r2 = subprocess.run(
            [shutil.which(joern_name) or joern_name, "--script", script_path, str(cpg_out)],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        if r2.returncode != 0:
            return EngineResult(engine="joern", status="crashed", reason=f"joern script exit {r2.returncode}: {r2.stderr[-400:]}")
        findings = _parse_alerts(r2.stdout)
        return EngineResult(engine="joern", status="ok", findings=findings)
    finally:
        Path(script_path).unlink(missing_ok=True)
