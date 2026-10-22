"""预算守卫（agent.md §7.3/D14）：计数/预警80%/熔断100%/台账 budget_ledger。"""

from enum import Enum

from codesentry.config import get_settings
from codesentry.db.pool import get_conn


class BudgetPhase(str, Enum):
    OK = "ok"
    WARN = "warn"
    BREACH = "breach"


class BudgetGuard:
    def __init__(self, scan_id: int) -> None:
        s = get_settings()
        self.scan_id = scan_id
        self.max_tokens = s.max_tokens
        self.max_tool_calls = s.max_tool_calls
        self.max_cost_usd = s.max_cost_usd
        self.max_findings = s.max_findings
        self.tokens = 0
        self.tool_calls = 0
        self.cost_usd = 0.0
        self.agent_tokens: dict[str, int] = {}
        self.agent_cost: dict[str, float] = {}
        self.agent_calls: dict[str, int] = {}

    def record(self, *, tokens: int = 0, tool_calls: int = 0, cost_usd: float = 0.0,
               phase: str = "", agent: str = "") -> None:
        self.tokens += tokens
        self.tool_calls += tool_calls
        self.cost_usd += cost_usd
        if agent:
            self.agent_tokens[agent] = self.agent_tokens.get(agent, 0) + tokens
            self.agent_cost[agent] = self.agent_cost.get(agent, 0.0) + cost_usd
            self.agent_calls[agent] = self.agent_calls.get(agent, 0) + tool_calls
        try:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO budget_ledger (scan_id, tokens_used, tool_calls, cost_usd, phase) VALUES (%s,%s,%s,%s,%s)",
                    (self.scan_id, tokens, tool_calls, cost_usd, phase),
                )
                conn.commit()
        except Exception:  # noqa: BLE001, S110 - 台账失败不阻塞主流程（M3 单机单写、真实异常仅断连；主流程 status 已有 budget 复本）
            pass

    def phase_now(self) -> BudgetPhase:
        ratios = [
            self.tokens / self.max_tokens if self.max_tokens else 0,
            self.tool_calls / self.max_tool_calls if self.max_tool_calls else 0,
            self.cost_usd / self.max_cost_usd if self.max_cost_usd else 0,
        ]
        if any(r >= 1.0 for r in ratios):
            return BudgetPhase.BREACH
        if any(r >= 0.8 for r in ratios):
            return BudgetPhase.WARN
        return BudgetPhase.OK

    def breached(self) -> bool:
        return self.phase_now() is BudgetPhase.BREACH

    def over_agent(self, agent: str, override: dict | None) -> bool:
        """按 Agent 覆写预算判断是否已超限。"""
        if not override:
            return False
        max_tokens = int(override.get("max_tokens") or 0)
        max_cost = float(override.get("max_cost_usd") or 0.0)
        max_calls = int(override.get("max_tool_calls") or 0)
        return bool(
            (max_tokens and self.agent_tokens.get(agent, 0) >= max_tokens)
            or (max_cost and self.agent_cost.get(agent, 0.0) >= max_cost)
            or (max_calls and self.agent_calls.get(agent, 0) >= max_calls)
        )

    def to_state(self) -> dict:
        p = self.phase_now()
        return {
            "tokens": self.tokens,
            "tool_calls": self.tool_calls,
            "cost_usd": self.cost_usd,
            "phase": p.value,
            "agents": {
                "tokens": self.agent_tokens,
                "cost_usd": self.agent_cost,
                "tool_calls": self.agent_calls,
            },
        }
