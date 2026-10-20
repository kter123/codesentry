"""ScanAgent（§7.2）：LicenseGate + 引擎组合选择并用 M1 引擎层跑（结果进 AuditState）。"""

from pathlib import Path

from codesentry.config import get_settings
from codesentry.engines.codeql import run_codeql
from codesentry.engines.joern import run_joern
from codesentry.engines.semgrep import run_semgrep
from codesentry.gate import LicenseGate
from codesentry.scan_orchestrator import run_engines_parallel, select_engines

_RULES_PATH = None


def _rules_path() -> str:
    global _RULES_PATH
    if _RULES_PATH is None:
        import codesentry

        # src/codesentry/agents/scan.py -> src/codesentry -> src -> repo root -> rules/
        pkg_file = codesentry.__file__ or "./codesentry/__init__.py"
        repo_root = str(Path(pkg_file).resolve().parent.parent.parent)
        _RULES_PATH = str(Path(repo_root) / "rules" / "codesentry-core.yml")
    return _RULES_PATH


def run_scan_agent(state: dict) -> dict:
    repo = state["repo_path"]
    OSS = bool(state["license_declaration"]["OSS"])
    gate = LicenseGate(OSS=OSS)
    profile = state.get("profile") or {}
    langs = profile.get("languages") or []

    engine_names = select_engines(OSS=OSS, lang=(langs[0] if langs else None))
    caps: dict = {}
    try:
        from codesentry.control.agent_config import effective_capabilities

        caps = effective_capabilities("scan")
        if "engines" in caps:
            allowed = caps.get("engines") or []
            engine_names = [n for n in engine_names if n in allowed]
    except Exception:  # noqa: BLE001, S110 - 控制面不可用时保持原引擎组合
        pass
    if caps and not caps.get("shell", True):
        return {
            "phase": "report",
            "engine_findings": [],
            "messages": [*(state.get("messages") or []), "scan 中止：能力矩阵禁用 shell"],
        }
    blocked = [n for n in engine_names if not gate.check_engine(n)[0]]
    settings = get_settings()

    def _spec(name):
        def spec(**_kw):
            if name == "codeql":
                return run_codeql(repo=repo, lang=(langs[0] if langs else "python"), OSS=OSS,
                                  out_dir=settings.work_dir, codeql_bin=settings.codeql_bin)
            if name == "joern":
                return run_joern(repo=repo, lang=(langs[0] if langs else "python"),
                                 out_dir=settings.work_dir, joern_bin=settings.joern_bin)
            return run_semgrep(repo=repo, semgrep_bin=settings.semgrep_bin, config=_rules_path())

        spec.__name__ = f"run_{name}"
        return spec

    specs = [_spec(n) for n in engine_names if n not in blocked]
    results = run_engines_parallel(specs=specs) if specs else []

    if results and all(r.status != "ok" for r in results):
        return {
            "phase": "report",
            "messages": [*(state.get("messages") or []), "scan 中止：全部引擎不可用"],
            "engine_findings": [],
            "engine_results_meta": [r.model_dump() for r in results],
        }

    findings = [f.model_dump() for r in results if r.status == "ok" for f in r.findings]
    return {
        "phase": "retrieval",
        "engine_findings": findings,
        "engine_results_meta": [r.model_dump() for r in results],
        "messages": [
            *(state.get("messages") or []),
            *(f"engines gate blocked: {n}" for n in blocked),
        ],
    }
