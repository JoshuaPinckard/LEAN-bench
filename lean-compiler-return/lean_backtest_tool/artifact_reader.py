"""Read order count from the LEAN backtest results JSON.

Single responsibility: locate the results JSON in a backtest output dir and
return the order count. Returns None on any failure (missing, malformed,
schema-not-as-expected). The caller treats None as 'unknown'.

Per spec §4.3: do not extend this. Richer extraction is the mechanical
checker's job (separate component, downstream).
"""
import json
from pathlib import Path
from typing import Optional


def _candidate_json_paths(output_dir: Path) -> list[Path]:
    """Files in the backtest output dir that could be the results JSON.

    LEAN names the main results file '<backtest-id>.json' alongside files like
    '<backtest-id>-log.txt' and '<backtest-id>-order-events.json'. We filter
    out the suffixed variants and keep top-level *.json files only.
    """
    if not output_dir.is_dir():
        return []
    out: list[Path] = []
    for p in output_dir.glob("*.json"):
        name = p.name
        if name.endswith("-order-events.json"):
            continue
        if name.endswith("-summary.json"):
            continue
        if name.endswith("-alpha-results.json"):
            continue
        out.append(p)
    return out


def _orders_from_payload(payload: dict) -> Optional[int]:
    """Pull the order count from the parsed JSON. Tolerates the known LEAN
    schema shapes — Statistics.TotalOrders, runtimeStatistics, etc."""
    # LEAN backtest result schemas put order count in a few places depending
    # on engine version. Try them in order, return the first int we find.
    candidates = (
        ("totalOrders",),
        ("TotalOrders",),
        ("statistics", "Total Orders"),
        ("statistics", "TotalOrders"),
        ("Statistics", "Total Orders"),
        ("Statistics", "TotalOrders"),
        ("runtimeStatistics", "Total Orders"),
        ("RuntimeStatistics", "Total Orders"),
    )
    for path in candidates:
        cur = payload
        ok = True
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if not ok:
            continue
        try:
            # LEAN often stores stat values as strings, e.g. "12".
            return int(cur)
        except (TypeError, ValueError):
            continue

    # Fallback: count orders array if present.
    orders = payload.get("orders") or payload.get("Orders")
    if isinstance(orders, list):
        return len(orders)
    if isinstance(orders, dict):
        return len(orders)

    return None


def read_orders(output_dir: Path) -> Optional[int]:
    """Return the order count from a backtest output directory.

    Returns None if the directory is missing, no results JSON is present, the
    JSON is malformed, or the schema does not contain a recognizable order
    count field. The caller appends ORDERS_PLACED: unknown in that case.
    """
    output_dir = Path(output_dir)
    for json_path in _candidate_json_paths(output_dir):
        try:
            with json_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        count = _orders_from_payload(payload)
        if count is not None:
            return count
    return None
