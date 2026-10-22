"""CodeSentry Python SDK（M6.7/FR-41）：轻量 HTTP 客户端。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class CodeSentryClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", token: str | None = None,
                 timeout: float = 30.0, transport: httpx.BaseTransport | None = None) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, headers=headers,
                                    timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CodeSentryClient:  # noqa: PYI034
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def health(self) -> dict:
        return self._client.get("/api/health").raise_for_status().json()

    def create_scan(self, *, file: str | Path | None = None, git_url: str = "",
                    diff_text: str = "", oss: bool = False) -> dict:
        data: dict[str, Any] = {"oss": str(oss).lower()}
        if git_url:
            data["git_url"] = git_url
        if diff_text:
            data["diff_text"] = diff_text
        files = None
        if file:
            p = Path(file)
            files = {"file": (p.name, p.read_bytes(), "application/zip")}
        result = self._client.post("/api/scans", params=data, files=files)
        return result.raise_for_status().json()

    def list_scans(self) -> list[dict]:
        return self._client.get("/api/scans").raise_for_status().json()

    def get_scan(self, scan_id: int) -> dict:
        return self._client.get(f"/api/scans/{scan_id}").raise_for_status().json()

    def findings(self, scan_id: int) -> dict:
        return self._client.get(f"/api/scans/{scan_id}/findings").raise_for_status().json()

    def artifacts(self, scan_id: int) -> dict:
        return self._client.get(f"/api/scans/{scan_id}/artifacts").raise_for_status().json()

    def verify_artifacts(self, scan_id: int) -> dict:
        return self._client.get(f"/api/scans/{scan_id}/artifacts/verify").raise_for_status().json()

    def resume(self, scan_id: int, decisions: list[dict]) -> dict:
        return self._client.post(f"/api/scans/{scan_id}/resume",
                                 json={"decisions": decisions}).raise_for_status().json()

    def ask(self, question: str, scan_id: int | None = None) -> dict:
        return self._client.post("/api/assist/ask",
                                 json={"question": question, "scan_id": scan_id}).raise_for_status().json()

    def usage(self, group_by: str = "agent") -> dict:
        return self._client.get("/api/usage/summary", params={"group_by": group_by}).raise_for_status().json()
