"""CodeQL 预授权安装（P2）：固定版本、官方 URL、SHA256、安全解压。"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

ALLOWED_HOST = "github.com"
RELEASE_PREFIX = "/github/codeql-action/releases/download/"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _setting(key: str) -> str:
    try:
        from codesentry.db.pool import get_conn

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
            row = cur.fetchone()
        if row is not None:
            return str(row[0])
    except Exception:  # noqa: BLE001, S110
        pass
    from codesentry.config import get_settings

    s = get_settings()
    return str(getattr(s, key, "") or "")


def platform_asset() -> str:
    sys_name = platform.system().lower()
    machine = platform.machine().lower()
    if sys_name == "darwin":
        return "codeql-bundle-osx64.tar.gz"
    if sys_name == "linux":
        return "codeql-bundle-linux64.tar.gz"
    if sys_name == "windows":
        return "codeql-bundle-win64.zip"
    raise ValueError(f"unsupported platform: {sys_name}/{machine}")


def release_url(version: str, asset: str | None = None) -> str:
    if not VERSION_RE.match(str(version or "")):
        raise ValueError("invalid CodeQL version")
    return (
        f"https://{ALLOWED_HOST}{RELEASE_PREFIX}codeql-bundle-v{version}/"
        f"{asset or platform_asset()}"
    )


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError("CodeQL 下载地址必须是官方 GitHub Release")
    if not parsed.path.startswith(RELEASE_PREFIX):
        raise ValueError("CodeQL 下载路径不在 release 白名单")
    return url


def install_dir() -> Path:
    from codesentry.config import get_settings

    settings = get_settings()
    value = _setting("codeql_install_dir")
    if value:
        return Path(value).expanduser().resolve()
    return (Path(settings.work_dir) / "tools" / "codeql").resolve()


def install_codeql(*, version: str = "", license_ack: bool = False,
                   sha256: str = "", timeout_s: int = 300) -> dict:
    from codesentry.config import get_settings

    settings = get_settings()
    version = version or _setting("codeql_version") or settings.codeql_version
    ack = license_ack or _setting("codeql_license_ack").lower() in ("1", "true", "yes", "on")
    if not ack:
        return {"ok": False, "error": "需要明确确认 CodeQL 许可（license_ack）"}
    if not VERSION_RE.match(str(version)):
        return {"ok": False, "error": "非法版本号"}
    url = _validate_url(release_url(version))
    expected = sha256 or _setting("codeql_sha256")
    dest = install_dir()
    tmp_path: Path | None = None
    try:
        with httpx.stream("GET", url, follow_redirects=False, timeout=timeout_s) as resp:
            if resp.status_code != 200:
                return {"ok": False, "error": f"下载失败：HTTP {resp.status_code}", "url": url}
            final = resp.headers.get("location") or ""
            if final:
                # 不跟随重定向；显式校验 location 仍是官方 release
                _validate_url(final)
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".tar.gz", delete=False
            ) as tmp:
                digest = hashlib.sha256()
                for chunk in resp.iter_bytes():
                    tmp.write(chunk)
                    digest.update(chunk)
                tmp_path = Path(tmp.name)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200], "url": url}
    try:
        actual = digest.hexdigest()
        if expected and actual.lower() != expected.lower():
            return {"ok": False, "error": "SHA256 校验失败", "sha256": actual}
        with tarfile.open(tmp_path) as tar:
            members = tar.getmembers()
            if len(members) > 50000:
                return {"ok": False, "error": "安装包条目过多"}
            for m in members:
                name = m.name.replace("\\", "/")
                if name.startswith("/") or ".." in Path(name).parts:
                    return {"ok": False, "error": f"安装包包含非法路径：{name}"}
                if m.issym() or m.islnk():
                    return {"ok": False, "error": "安装包包含链接，拒绝解压"}
            extract_root = Path(tempfile.mkdtemp(prefix="cs-codeql-"))
            tar.extractall(extract_root, filter="data")
        candidates = list(extract_root.rglob("codeql"))
        binary = next((p for p in candidates if p.is_file() and os.access(p, os.X_OK)),
                      None)
        if binary is None:
            return {"ok": False, "error": "安装包中未找到 codeql 可执行文件"}
        version_out = ""
        try:
            r = subprocess.run([str(binary), "version"], capture_output=True, text=True,
                               timeout=30, check=False)
            version_out = (r.stdout or r.stderr).strip()[:300]
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"codeql version 验证失败：{str(e)[:160]}"}
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(binary.parent), str(dest))
        from codesentry.control.audit import audit_write

        audit_write("system", "install", "codeql", version,
                    None, {"version": version, "path": str(dest),
                           "sha256": actual, "url": url})
        return {"ok": True, "version": version, "binary": str(dest / "codeql"),
                "version_output": version_out, "sha256": actual,
                "verified_sha256": bool(expected)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200], "url": url}
    finally:
        try:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001, S110
            pass
