"""密钥加密与脱敏（M6.1）：Fernet 落库，读接口掩码，日志/审计脱敏。"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets as _secrets
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class SecretError(Exception):
    """密钥无法解密（不携带密文，避免日志泄露）。"""


_SENSITIVE = re.compile(r"(api[_-]?key|secret|password|passwd|token|credential)", re.IGNORECASE)


def _derive_key(raw: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())


def _key_file() -> Path:
    from codesentry.config import get_settings

    return Path(get_settings().work_dir) / ".secret_key"


def _raw_secret() -> bytes:
    from codesentry.config import get_settings

    raw = get_settings().secret_key or os.environ.get("CODESENTRY_SECRET_KEY", "")
    if raw:
        return raw.encode("utf-8")
    path = _key_file()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(base64.urlsafe_b64encode(_secrets.token_bytes(32)))
        except FileExistsError:  # 另一进程已生成，直接复用
            pass
    return path.read_bytes()


def get_fernet() -> Fernet:
    """优先 CODESENTRY_SECRET_KEY；否则使用 work_dir/.secret_key（0600，自动生成）。"""
    from codesentry.config import get_settings

    raw = get_settings().secret_key or os.environ.get("CODESENTRY_SECRET_KEY", "")
    if raw:
        return Fernet(_derive_key(raw))
    return Fernet(_raw_secret())


def get_signing_key() -> bytes:
    """JWT/HMAC 签名密钥（从主密钥派生）。"""
    return hashlib.sha256(_raw_secret()).digest()


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return get_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(cipher: str) -> str:
    if not cipher:
        return ""
    try:
        return get_fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretError("密钥解密失败（主密钥可能已轮换）") from exc


def mask_secret(plain: str) -> str:
    """只展示前 8 位；短密钥整体打码。"""
    if not plain:
        return ""
    if len(plain) <= 8:
        return "***"
    return plain[:8] + "…"


def mask_cipher(cipher: str) -> str:
    if not cipher:
        return ""
    try:
        return mask_secret(decrypt_secret(cipher))
    except SecretError:
        return "***"


def redact_mapping(value: Any) -> Any:
    """递归脱敏审计 before/after；敏感键的值替换为 ***。"""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _SENSITIVE.search(str(k)) and v not in (None, ""):
                out[k] = "***"
            else:
                out[k] = redact_mapping(v)
        return out
    if isinstance(value, list):
        return [redact_mapping(v) for v in value]
    return value
