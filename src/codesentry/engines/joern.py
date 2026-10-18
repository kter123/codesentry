"""Joern 引擎（agent.md §4.1/§4.2）。

M1.5 真实现（jvm 实测）：
- 按语言直接调用 joern 前端二进制（joern-parse 的 --language java 在目录模式走 jimple
  而非 javasrc，源码级需直接调 javasrc2cpg 等）
- 查询脚本用已验证语法（loadCpg(path).get / c.location.lineNumber）
- joern 的 println 走 **stderr**（实测确认），解析合并流
- sink 名按前端的 call-name 特性（go 的 exec.Command 拆为 member call "Command"）
- PHP phy2cpg 实验性：崩溃 -> 标 crashed，由 Semgrep 降级覆盖（§10/§4.2）
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from codesentry.models import EngineResult, Finding, Severity

_JOERN_ROOT = "/Volumes/macOS/codesentry/tools/joern-cli"

# 语言 → (前端命令, sink member/call 名列表)
_JOERN_FRONTEND = {
    "python": ("pysrc2cpg", ["get", "post", "urlopen"]),
    "java": ("javasrc2cpg", ["exec", "readString", "readAllLines", "getInputStream", "newFile"]),
    "javascript": ("jssrc2cpg.sh", ["fetch", "keys"]),  # keys 暂归 proto-pollution 面上
    "typescript": ("jssrc2cpg.sh", ["fetch", "keys"]),
    "go": ("gosrc2cpg", ["Command", "exec"]),
    "c": ("c2cpg.sh", ["system", "printf"]),
    "cpp": ("c2cpg.sh", ["system", "printf"]),
    "php": ("php2cpg", ["eval"]),
}

_QUERY_TEMPLATE = """
import _root_.io.joern.dataflowengineoss.language.*
import _root_.io.shiftleft.semanticcpg.language.*

val cpg2 = loadCpg("%(cpg)s").get
val names = List(%(names)s)
val out = names.flatMap { n => cpg2.call.name(n).l }
out.foreach { c =>
  println("JOERN_ALERT|" + c.method.filename.headOption.getOrElse("") + "|" + c.location.lineNumber.headOption.getOrElse(-1) + "|" + c.name)
}
println("TOTAL " + out.size)
cpg2.close
"""

_ALERT_MARK = "JOERN_ALERT|"


def _sev_by_cwe(cwe: int) -> Severity:
    if cwe in (78, 95, 918, 22, 134, 1321):
        return "high"
    return "medium"


def _rule_by_name(name: str) -> tuple[str, int]:
    if name in ("readString", "readAllLines", "getInputStream", "newFile"):
        return "joern.file-read", 22
    if name in ("exec", "Command", "system", "execve"):
        return "joern.cmd-injection", 78
    if name == "eval":
        return "joern.eval-sink", 95
    if name in ("get", "post", "urlopen", "fetch"):
        return "joern.ssrf-sink", 918
    if name == "printf":
        return "joern.format-string", 134
    if name == "keys":
        return "joern.proto-pollution", 1321
    return "joern.sink-call", 610


def _parse_alerts(stdout: str, stderr: str) -> list[Finding]:
    out: list[Finding] = []
    for line in (stdout + "\n" + stderr).splitlines():
        if not line.startswith(_ALERT_MARK):
            continue
        parts = line[len(_ALERT_MARK) :].split("|")
        if len(parts) != 3:
            continue
        file_s, line_s, name_s = parts
        try:
            line_no = int(line_s)
        except ValueError:
            continue
        if line_no < 1:
            continue
        rule_id, cwe = _rule_by_name(name_s)
        out.append(
            Finding(
                rule_id=rule_id,
                cwe=cwe,
                severity=_sev_by_cwe(cwe),
                confidence=0.7,
                file=file_s,
                line=line_no,
                message=f"joern sink call: {name_s}",
                engine="joern",
                taint_metadata={"source": "joern-cpg"},
            )
        )
    return out


def _which_frontend(fe_cmd: str) -> str | None:
    fe_path = Path(_JOERN_ROOT) / fe_cmd
    if fe_path.exists():
        return str(fe_path)
    return shutil.which(fe_cmd)


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
    if not _which_frontend("joern-parse"):
        return EngineResult(engine="joern", status="unavailable", reason="binary not found: joern-parse")

    fe_cmd, sink_names = _JOERN_FRONTEND.get(lang, (None, []))
    if fe_cmd is None:
        return EngineResult(engine="joern", status="unavailable", reason=f"unsupported language: {lang}")
    fe_path = _which_frontend(fe_cmd)
    if fe_path is None:
        return EngineResult(engine="joern", status="unavailable", reason=f"frontend not found: {fe_cmd}")

    work_root = os.environ.get("CODESENTRY_WORK_DIR", ".codesentry")
    work = (Path(work_root) if Path(work_root).is_absolute() else Path.cwd() / work_root) / "cpg"
    work.mkdir(parents=True, exist_ok=True)
    cpg_out = work / f"{Path(repo).name}.bin"

    jp = shutil.which("joern-parse")
    env = {**os.environ, "PATH": f"{Path(joern_path).parent}:{_JOERN_ROOT}:{os.environ.get('PATH', '')}"}
    abs_repo = str(Path(repo).resolve())

    def _frontend_cmd():
        if fe_path.endswith(".sh") or fe_path.endswith(".bat"):
            return ["sh", fe_path]
        return [fe_path]

    r1 = subprocess.run(
        _frontend_cmd() + [abs_repo, "--output", str(cpg_out)],
        capture_output=True, text=True, timeout=timeout, check=False, cwd=repo, env=env,
    )
    if r1.returncode != 0:
        return EngineResult(engine="joern", status="crashed",
                            reason=f"joern {fe_cmd} exit {r1.returncode}: {r1.stderr[-300:]}")

    script = _QUERY_TEMPLATE % {"cpg": cpg_out, "names": ", ".join(f'"{n}"' for n in sink_names)}
    with tempfile.NamedTemporaryFile("w", suffix=".sc", delete=False) as f:
        f.write(script)
        script_path = f.name
    try:
        r2 = subprocess.run(
            [joern_path, "--script", script_path],
            capture_output=True, text=True, timeout=timeout, check=False, env=env,
        )
        if r2.returncode != 0:
            return EngineResult(engine="joern", status="crashed",
                                reason=f"joern script exit {r2.returncode}: {r2.stderr[-300:]}")
        findings = _parse_alerts(r2.stdout, r2.stderr)
        return EngineResult(engine="joern", status="ok", findings=findings)
    finally:
        Path(script_path).unlink(missing_ok=True)
