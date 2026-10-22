"""扫描事件总线（M6 / A4）：节点级实时事件，供 WebSocket pump 消费。"""

from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_pending: dict[int, list[dict]] = defaultdict(list)


def publish(scan_id: int, event: dict) -> None:
    if not scan_id:
        return
    with _lock:
        _pending[int(scan_id)].append(event)


def drain(scan_id: int) -> list[dict]:
    with _lock:
        return _pending.pop(int(scan_id), [])


def room_ids() -> list[int]:
    with _lock:
        return list(_pending.keys())
