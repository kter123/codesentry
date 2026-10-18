"""Joern 引擎（agent.md §4.1 全场景深度引擎；§4.2 六语言矩阵）。

M1.5 真实现（已实测通过）：joern-parse 建 CPG → joern --script 执行生成查询 → 解析 alert 行。
查询语法按 joern v4 验证：loadCpg(path).get + c.location.lineNumber。
CPG/查询落 CODESENTRY_WORK_DIR；查询仅用 joern 内置 API（原创，不移植 CodeQL，§3）。
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from codesentry.models import EngineResult, Finding, Severity

JOERN_LANG = {
    "python": "pythonsrc",
    "java": "java",
    "javascript": "jssrc",
    "typescript": "jssrc",
    "go": "golang",
    "c": "c",
    "cpp": "c",
    "php": "php",
}

# sink 规则（通用 API 名；逐语言细化 M3 深化）
_SINKS = [
    ("joern.cmd-injection", 78, "high", r"/tmp/sink-rule-cmd.sc"),
    ("joern.eval-sink", 95, "high", r"/tmp/sink-rule-eval.sc"),
    ("joern.ssrf-sink", 918, "high", r"/tmp/sink-rule-ssrf.sc"),
]

_QUERY_TEMPLATE = """
import _root_.io.joern.dataflowengineoss.language.*
import _root_.io.shiftleft.semanticcpg.language.*

val cpg2 = loadCpg("%(cpg)s").get
val names = List(%(names)s)
val out = names.flatMap { n =>
  cpg2.call.name(n).l
}
out.foreach { c =>
  println("JOERN_ALERT|" + c.method.filename.headOption.getOrElse("") + "|" + c.location.lineNumber.headOption.getOrElse(-1) + "|" + c.name)
}
println("TOTAL " + out.size)
cpg2.close
"""

_ALERT_MARK = "JOERN_ALERT|"

_REPO_FILE_PREFIX = "JOERN_SRCFILE_PRE"


def _parse_alerts(stdout: str) -> list[Finding]:
    out: list[Finding] = []
    for line in stdout.splitlines():
        if not line.startswith(_ALERT_MARK):
            continue
        _parts = line[len(_ALERT_MARK) :].split("|")
        if len(_parts) != 3:
            continue
        file_s, line_s, name_s = _parts
        try:
            line_no = int(line_s)
        except ValueError:
            continue
        if line_no < 1:
            continue
        out.append(
            Finding(
                rule_id=_SINKS_RULE_ID(name_s),
                cwe=_SINKS_RULE_CWE(name_s),
                severity=_SINKS_RULE_SEV(name_s),
                confidence=0.7,
                file=file_s if "/" in file_s or "." in file_s else file_s,  # pysrc2cpg filename 特性：M3 归一层补全相对路径
                line=line_no,
                message=f"joern sink call: {name_s}",
                engine="joern",
                taint_metadata={"source": "joern-cpg"},
            )
        )
    return out


def _SINKS_RULE_ID(call_name: str) -> str:
    if call_name.startswith("/system"):
        return "joern.cmd-injection"
    if call_name == "eval":
        return "joern.eval-sink"
    return "joern.ssrf-sink"


def _SINKS_RULE_CWE(call_name: str) -> int:
    if "exec" in call_name:
        return 78
    if call_name == "eval":
        return 95
    return 918


def _SINKS_RULE_SEV(call_name: str) -> Severity:
    return "high"


def run_joern(
    repo: str,
    lang: str,
    out_dir: str,
    *,
    timeout: int = 3600,
    joern_bin: str | None = None,
) -> EngineResult:
    joern_name = joern_bin or os.environ.get("CODESENTRY_JOERN_BIN", "joern")
    joern_path = shutil.which(joern_name)
    if joern_path is None:
        return EngineResult(engine="joern", status="unavailable", reason=f"binary not found: {joern_name}")
    joern_dir = Path(joern_path).parent
    joern_parse_path = shutil.which("joern-parse") or shutil.which(str(joern_dir / "joern-parse"))
    if not joern_parse_path:
        return EngineResult(engine="joern", status="unavailable", reason="binary not found: joern-parse")
    frontend = JOERN_LANG.get(lang)
    if frontend is None:
        return EngineResult(engine="joern", status="unavailable", reason=f"unsupported language: {lang}")

    work = Path(os.environ.get("CODESENTRY_WORK_DIR", ".codesentry")) / "cpg"
    work.mkdir(parents=True, exist_ok=True)
    cpg_out = work / (Path(repo).name + ".bin")

    # 1) CPG 构建
    r1 = subprocess.run(
        ["joern-parse", repo, "--output", str(cpg_out), "--language", frontend],
        capture_output=True, text=True, timeout=timeout, check=False,
        env={**os.environ, "PATH": f"{joern_dir}:" + os.environ.get("PATH", "")},
    )
    if r1.returncode != 0:
        return EngineResult(engine="joern", status="crashed", reason=f"joern-parse exit {r1.returncode}: {r1.stderr[-400:]}")

    # 2) 查询脚本执行（sink 名按通用 API 名；语言特化 M3）
    sink_names = _SINK_NAMES_FOR(lang)
    script = _QUERY_TEMPLATE % {"cpg": str(cpg_out), "names": ", ".join(f'"{n}"' for n in sink_names)}
    with tempfile.NamedTemporaryFile("w", suffix=".sc", delete=False) as f:
        f.write(script)
        script_path = f.name
    try:
        r2 = subprocess.run(
            [joern_path, "--script", script_path],
            capture_output=True, text=True, timeout=timeout, check=False,
            env={**os.environ, "PATH": f"{joern_dir}:" + os.environ.get("PATH", "")},
        )
        if r2.returncode != 0:
            return EngineResult(engine="joern", status="crashed", reason=f"joern script exit {r2.returncode}: {r2.stderr[-400:]}")
        findings = _parse_alerts(r2.stdout)
        return EngineResult(engine="joern", status="ok", findings=findings)
    finally:
        Path(script_path).unlink(missing_ok=True)


def _SINK_NAMES_FOR(lang: str) -> list[str]:
    if lang == "python":
        return ["get", "post"]  # requests.get/post；后续加 urlopen (M3)
    if lang == "java":
        return ["exec"]
    if lang in ("javascript", "typescript"):
        return ["fetch"]
    if lang == "go":
        return ["exec.Command"]
    if lang in ("c", "cpp"):
        return ["system", "execve"]
    if lang == "php":
        return ["eval"]
    return ["system"]
