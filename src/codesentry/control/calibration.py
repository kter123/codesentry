"""置信度校准参数（M6.4）：温度缩放 a/b 拟合与 ECE。"""

from __future__ import annotations

from codesentry.agents.confidence import calibrate


def get_params() -> dict:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT a, b, ece, n, fit_at FROM calibration_params ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        if not row:
            return {"a": 1.0, "b": 0.0, "ece": 0.0, "n": 0, "fit_at": None}
        return {"a": float(row[0]), "b": float(row[1]), "ece": float(row[2]),
                "n": int(row[3]), "fit_at": str(row[4])}
    except Exception:  # noqa: BLE001
        return {"a": 1.0, "b": 0.0, "ece": 0.0, "n": 0, "fit_at": None}


def ece(pairs: list[dict], a: float, b: float, bins: int = 10) -> float:
    if not pairs:
        return 0.0
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
    for item in pairs:
        p = calibrate(float(item["raw"]), a, b)
        label = float(item["label"])
        idx = min(bins - 1, max(0, int(p * bins)))
        buckets[idx].append((p, label))
    total = len(pairs)
    err = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        avg_conf = sum(p for p, _ in bucket) / len(bucket)
        avg_acc = sum(y for _, y in bucket) / len(bucket)
        err += len(bucket) / total * abs(avg_conf - avg_acc)
    return round(err, 6)


def fit(pairs: list[dict]) -> dict:
    best = (1.0, 0.0, 1.0)
    for a_int in range(2, 31):  # 0.2 .. 3.0
        a = a_int / 10.0
        for b_int in range(-30, 31, 2):  # -3.0 .. 3.0
            b = b_int / 10.0
            e = ece(pairs, a, b)
            if e < best[2]:
                best = (a, b, e)
    return {"a": best[0], "b": best[1], "ece": best[2], "n": len(pairs)}


def save(params: dict) -> bool:
    try:
        from codesentry.control.bootstrap import ensure_control_schema
        from codesentry.db.pool import get_conn

        ensure_control_schema()
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO calibration_params (a, b, ece, n) VALUES (%s,%s,%s,%s)",
                (float(params["a"]), float(params["b"]), float(params.get("ece", 0)),
                 int(params.get("n", 0))),
            )
            conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def fit_and_save(pairs: list[dict]) -> dict:
    params = fit(pairs)
    save(params)
    return params
