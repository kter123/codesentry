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

    engine_names = []
    for lang in (langs or ["python"]):
        for name in select_engines(OSS=OSS, lang=lang):
            if name not in engine_names:
                engine_names.append(name)
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

    def _semgrep_spec():
        def spec(**_kw):
            return run_semgrep(repo=repo, semgrep_bin=settings.semgrep_bin,
                               config=_rules_path())

        spec.__name__ = "run_semgrep"
        return spec

    def _codeql_spec(lang: str):
        def spec(**_kw):
            return run_codeql(repo=repo, lang=lang, OSS=OSS,
                              out_dir=settings.work_dir,
                              codeql_bin=settings.codeql_bin)

        spec.__name__ = f"run_codeql_{lang}"
        return spec

    def _joern_spec(lang: str):
        def spec(**_kw):
            return run_joern(repo=repo, lang=lang, out_dir=settings.work_dir,
                             joern_bin=settings.joern_bin)

        spec.__name__ = "run_joern"
        return spec

    from codesentry.scan_orchestrator import codeql_langs

    specs: list = []
    for name in engine_names:
        if name in blocked:
            continue
        if name == "codeql":
            specs.extend(_codeql_spec(lang) for lang in codeql_langs(langs))
        elif name == "joern":
            specs.append(_joern_spec("java" if "java" in langs else (langs[0] if langs else "java")))
        else:
            specs.append(_semgrep_spec())
    results = run_engines_parallel(specs=specs) if specs else []

    if results and all(r.status != "ok" for r in results):
        return {
            "phase": "audit",
            "engine_hints": [],
            "messages": [*(state.get("messages") or []), "scan：全部引擎不可用，转为纯图审计"],
            "engine_results_meta": [r.model_dump() for r in results],
        }

    from codesentry.rag.graph_delta import apply_engine_hints, hints_from_engine_results

    hints = hints_from_engine_results(results)
    applied: dict[str, object] = {"applied": 0, "anchored": 0}
    try:
        applied = apply_engine_hints(
            repo, int(state.get("graph_build_id") or 0), hints
        )
    except Exception as exc:  # noqa: BLE001 - 图写入失败不影响后续 Agent 审计
        applied = {"applied": 0, "anchored": 0, "error": str(exc)[:200]}

    engine_graph: dict = {}
    project = str(Path(repo).resolve())
    if any(r.engine == "joern" and r.status == "ok" for r in results):
        try:
            from codesentry.engines.joern_graph import run_joern_graph

            engine_graph["joern"] = run_joern_graph(repo, project)
        except Exception as exc:  # noqa: BLE001 - 引擎图失败降级
            engine_graph["joern"] = {"ok": False, "error": str(exc)[:200]}
    if any(r.engine == "codeql" and r.status == "ok" for r in results):
        from codesentry.engines.codeql_graph import run_codeql_graph

        build_id = int(state.get("graph_build_id") or 0)
        sarifs = [r.artifact for r in results
                  if r.engine == "codeql" and r.status == "ok" and r.artifact]
        if not sarifs:
            sarifs = [str(p) for p in sorted(Path(settings.work_dir).glob("codeql-*.sarif"))]
        merged: dict = {"ok": True, "languages": {}, "flows": 0, "nodes": 0,
                        "edges": 0, "calls": 0, "dataflow": 0, "truncated": False}
        errors = []
        for sarif in sarifs:
            try:
                stats = run_codeql_graph(sarif, repo, project, build_id=build_id)
                lang = Path(sarif).stem.removeprefix("codeql-")
                merged["languages"][lang] = stats
                for key in ("flows", "nodes", "edges", "calls", "dataflow"):
                    merged[key] += int(stats.get(key) or 0)
                merged["truncated"] = bool(merged["truncated"] or stats.get("truncated"))
                if not stats.get("ok", True):
                    errors.append(stats.get("error", ""))
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc)[:200])
        if errors:
            merged["errors"] = errors
        engine_graph["codeql"] = merged
    applied = {**applied, "engine_graph": engine_graph}
    return {
        "phase": "audit",
        "engine_hints": hints,
        "engine_results_meta": [r.model_dump() for r in results],
        "graph_delta": applied,
        "messages": [
            *(state.get("messages") or []),
            *(f"engines gate blocked: {n}" for n in blocked),
            f"scan: {len(hints)} engine hints → graph ({applied.get('applied', 0)} sinks)",
        ],
    }
