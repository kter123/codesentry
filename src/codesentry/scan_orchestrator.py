"""scan 主流程编排（agent.md FR-1/D8：极简 recon → Gate → 并行引擎 → 报告）。

M1 不引入 LangGraph（M3 职责）；M1 用 ThreadPoolExecutor 做引擎级并行。
"""

import concurrent.futures
import os
from datetime import UTC
from pathlib import Path

import typer

from codesentry.config import get_settings
from codesentry.gate import LicenseGate
from codesentry.models import EngineResult, LicenseDeclaration, ScanProfile

ENGINE_ORDER = ["codeql", "joern", "semgrep"]

# 语言 → 文件扩展名（极简 recon）
LANG_EXTS = {
    "python": {".py"},
    "java": {".java"},
    "javascript": {".js", ".mjs", ".cjs"},
    "typescript": {".ts", ".tsx"},
    "go": {".go"},
    "c": {".c", ".h"},
    "cpp": {".cc", ".cpp", ".hpp", ".cxx"},
    "php": {".php"},
}


def select_engines(OSS: bool, lang: str | None = None) -> list[str]:
    """引擎组合（agent.md D8 + §4.2）：开源 CodeQL+Semgrep；闭源 Joern+Semgrep；PHP 无 CodeQL。"""
    if lang == "php":
        return ["joern", "semgrep"]
    if OSS:
        return ["codeql", "semgrep"]
    return ["joern", "semgrep"]


def detect_languages(repo: str) -> list[str]:
    """极简 recon：按扩展名推断语言出现（M3 ReconAgent 深化）。"""
    repo_path = Path(repo)
    found: set[str] = set()
    for root, _dirs, files in os.walk(repo_path):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            for lang, exts in LANG_EXTS.items():
                if ext in exts:
                    found.add(lang)
    return sorted(found) if found else []


def run_engines_parallel(specs: list, **kwargs) -> list[EngineResult]:
    """并行执行引擎 callable；单个崩溃/超时捕获为降级 EngineResult（§10）。"""
    results: list[EngineResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(specs))) as pool:
        futures = {pool.submit(spec, **kwargs): spec for spec in specs}
        for fut in concurrent.futures.as_completed(futures):
            spec = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001 - 引擎故障必须降级不阻塞整条流水线
                name = getattr(spec, "__name__", "unknown")
                engine = next(
                    (n for n in ENGINE_ORDER if n in name), "joern"
                )
                results.append(
                    EngineResult(
                        engine=engine,  # type: ignore[arg-type]  # 由 spec 名推定，非 run_* 命名时兜底 joern
                        status="crashed",
                        reason=str(e),
                    )
                )
    order = {n: i for i, n in enumerate(ENGINE_ORDER)}
    results.sort(key=lambda r: order.get(r.engine, 99))
    return results


def run_scan(repo: str, OSS: bool, out_dir: str) -> int:
    """完整 scan 流程：recon → Gate → 并行引擎 → 报告双写（FR-1/FR-3/FR-6）。

    返回 0 成功 / 1 失败（中止落因）。
    """
    from codesentry.engines.codeql import run_codeql
    from codesentry.engines.joern import run_joern
    from codesentry.engines.semgrep import run_semgrep
    from codesentry.reportex.markdown import render_markdown
    from codesentry.reportex.sarif import write_sarif

    lang_list = detect_languages(repo)
    lang = lang_list[0] if lang_list else "python"
    profile = ScanProfile(languages=lang_list)

    declaration = LicenseDeclaration(OSS=OSS, declared_at=_now_iso())
    gate = LicenseGate(OSS=OSS)
    engine_names = select_engines(OSS=OSS, lang=lang)
    blocked = [n for n in engine_names if not gate.check_engine(n)[0]]


    def _engine_spec(name):
        def spec(**kw):
            if name == "codeql":
                return run_codeql(
                    repo=repo, lang=lang, OSS=OSS, out_dir=out_dir,
                    codeql_bin=get_settings().codeql_bin,
                )
            if name == "joern":
                return run_joern(
                    repo=repo, lang=lang, out_dir=out_dir,
                    joern_bin=get_settings().joern_bin,
                )
            return run_semgrep(
                repo=repo, semgrep_bin=get_settings().semgrep_bin,
            )

        spec.__name__ = f"run_{name}"
        return spec

    specs = [_engine_spec(n) for n in engine_names if n not in blocked]
    results = run_engines_parallel(specs=specs) if specs else []

    all_dead = all(r.status != "ok" for r in results)
    if all_dead:
        typer.echo(
            f"scan 中止：全部引擎不可用（choices={engine_names}, blocked={blocked}, "
            f"status={[r.status for r in results]}）", err=True
        )
        return 1

    findings = [f for r in results for f in r.findings]
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    write_sarif(findings, str(out_path / "report.sarif"))
    md = render_markdown(
        findings,
        profile_languages=profile.languages,
        license_declaration={"OSS": declaration.OSS, "declared_at": declaration.declared_at},
    )
    (out_path / "report.md").write_text(md, encoding="utf-8")
    return 0


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
