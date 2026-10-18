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

    def record(self, *, tokens: int = 0, tool_calls: int = 0, cost_usd: float = 0.0, phase: str = "") -> None:
        self.tokens += tokens
        self.tool_calls += tool_calls
        self.cost_usd += cost_usd
        try:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO budget_ledger (scan_id, tokens_used, tool_calls, cost_usd, phase) VALUES (%s,%s,%s,%s,%s)",
                    (self.scan_id, tokens, tool_calls, cost_usd, phase),
                )
                conn.commit()
        except Exception:  # noqa: BLE001 - 台账失败不阻塞主流程（M3 单机单写、真实异常仅断连）
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

    def to_state(self) -> dict:
        p = self.phase_now()
        return {
            "tokens": self.tokens,
            "tool_calls": self.tool_calls,
            "cost_usd": self.cost_usd,
            "phase": p.value,
        }
