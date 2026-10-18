class LicenseGate:
    """许可 Gate（agent.md FR-3）：仅声明开源（--oss）时允许 CodeQL。"""

    def __init__(self, OSS: bool) -> None:
        self.OSS = OSS

    def check_engine(self, engine: str) -> tuple[bool, str]:
        if engine == "codeql" and not self.OSS:
            return False, "CodeQL 仅允许用于开源代码（license 红线）——目标未声明 --oss，闭源场景禁用"
        return True, ""


def record_declaration(declared_at: str, OSS: bool) -> dict:
    """声明记录（M3 落 scans 表；M1 返回 dict 进扫描元数据）。"""
    return {"OSS": OSS, "declared_at": declared_at}
