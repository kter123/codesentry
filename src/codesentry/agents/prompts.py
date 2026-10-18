"""Prompt 生效源（D33/§6）：DB 活跃版本加载；缺失/损坏回退代码内种子并告警。"""

from codesentry.db.pool import get_conn

# 种子 Prompt（代码内常量，仅用于初始化与回退；六 agent 各一段简中说明）
SEED_PROMPTS: dict[str, str] = {
    "recon": "你是 CodeSentry ReconAgent：识别语言/框架/构建方式/入口点，产出仓库画像；增量模式下只考虑 diff 可达闭包。输出 JSON。",
    "scan": "你是 CodeSentry ScanAgent：执行许可 Gate（仅 --oss 允许 CodeQL），按引擎策略并行调度（开源 CodeQL+Semgrep，闭源 Joern+Semgrep），结果归一 Finding。",
    "retrieval": "你是 CodeSentry RetrievalAgent：为每个候选 finding 拉取代码切片/相似历史漏洞/知识条目，输出证据集合。",
    "triage": "你是 CodeSentry TriageAgent：对每个 finding 做可达性验证与误报判别（按需拉调用链直到闭环），输出 保留/降级/否决 + 置信度 + 证据链 + 修复建议。领域 Skill 是你的主要参考。",
    "poc_gen": "你是 CodeSentry PoCGenAgent：对保留 finding 生成利用链路与分级 PoC（HTTP 请求序列 / 本地 payload+调用），POC_RUN 控制是否执行；危险 payload 必须拒绝。",
    "report": "你是 CodeSentry ReportAgent：去重合并、按严重度/置信度排序，生成中文 Markdown + SARIF 报告。",
}

_AGENT_TABLE = {
    "recon", "scan", "retrieval", "triage", "poc_gen", "report",
}


def seed_prompts_to_db() -> int:
    """init 时把种子写入 prompt_versions（幂等：同 agent+version1 已存在则跳过）。"""
    n = 0
    try:
        with get_conn() as conn, conn.cursor() as cur:
            for agent, body in SEED_PROMPTS.items():
                cur.execute("SELECT 1 FROM prompt_versions WHERE agent = %s AND version = 1", (agent,))
                if cur.fetchone():
                    continue
                cur.execute(
                    "INSERT INTO prompt_versions (agent, version, body, active) VALUES (%s, 1, %s, TRUE)",
                    (agent, body),
                )
                n += 1
            conn.commit()
    except Exception:  # noqa: BLE001, S110 - 无库时静默（init-db 由 CLI 引导）
        pass
    return n


def load_prompt(agent: str) -> tuple[str, int | None, bool]:
    """返回 (prompt_text, version, is_fallback)。DB 生效源；缺失回退种子。"""
    assert agent in _AGENT_TABLE, f"unknown agent: {agent}"
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT version, body FROM prompt_versions WHERE agent = %s AND active = TRUE ORDER BY version DESC LIMIT 1",
                (agent,),
            )
            row = cur.fetchone()
            if row:
                return str(row[1]), int(row[0]), False
    except Exception:  # noqa: BLE001 - DB 不可用回退种子（§10）
        pass
    return SEED_PROMPTS[agent], None, True
