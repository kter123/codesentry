from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "low", "medium", "high", "critical"]
EngineName = Literal["codeql", "joern", "semgrep", "agent"]


class Finding(BaseModel):
    rule_id: str
    cwe: int
    severity: Severity = "medium"
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    file: str
    line: int = Field(ge=1)
    end_line: int | None = None
    message: str
    engine: EngineName
    taint_metadata: dict = Field(default_factory=dict)
    fix_advice: str = ""


class LicenseDeclaration(BaseModel):
    OSS: bool
    declared_at: str


class ScanProfile(BaseModel):
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)


class EngineResult(BaseModel):
    engine: EngineName
    status: Literal["ok", "timeout", "crashed", "unavailable"]
    findings: list[Finding] = Field(default_factory=list)
    reason: str = ""
