"""主密钥轮换：用旧密钥解密、新密钥重加密 LLM/Embedding 密钥。

用法：
  CODESENTRY_OLD_SECRET=... CODESENTRY_NEW_SECRET=... \
  PYTHONPATH=src .venv/bin/python scripts/rotate_master_key.py

轮换后请更新 CODESENTRY_SECRET_KEY 并重启服务。
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys

from cryptography.fernet import Fernet

from codesentry.db.pool import get_conn


def _fernet(raw: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


def main() -> int:
    old = os.environ.get("CODESENTRY_OLD_SECRET", "")
    new = os.environ.get("CODESENTRY_NEW_SECRET", "")
    if not old or not new:
        print("需要 CODESENTRY_OLD_SECRET 与 CODESENTRY_NEW_SECRET", file=sys.stderr)
        return 2
    f_old, f_new = _fernet(old), _fernet(new)
    changed = 0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, api_key_cipher FROM llm_profiles WHERE api_key_cipher <> ''")
        for pid, cipher in cur.fetchall():
            try:
                plain = f_old.decrypt(cipher.encode()).decode()
            except Exception as e:  # noqa: BLE001
                print(f"skip profile {pid}: decrypt failed ({str(e)[:60]})", file=sys.stderr)
                continue
            cur.execute(
                "UPDATE llm_profiles SET api_key_cipher=%s, updated_at=now() WHERE id=%s",
                (f_new.encrypt(plain.encode()).decode(), pid),
            )
            changed += 1
        cur.execute("SELECT key, value FROM app_settings WHERE key LIKE %s", ("%api_key",))
        for key, cipher in cur.fetchall():
            if not cipher:
                continue
            try:
                plain = f_old.decrypt(cipher.encode()).decode()
            except Exception as e:  # noqa: BLE001
                print(f"skip setting {key}: decrypt failed ({str(e)[:60]})", file=sys.stderr)
                continue
            cur.execute(
                "UPDATE app_settings SET value=%s, updated_at=now() WHERE key=%s",
                (f_new.encrypt(plain.encode()).decode(), key),
            )
            changed += 1
        conn.commit()
    print(f"rotated {changed} secret(s); update CODESENTRY_SECRET_KEY and restart")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
