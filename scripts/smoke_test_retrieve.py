"""Smoke test for the frozen LEAN RAG retriever.

Runs ~10 hand-written LEAN queries through ``retrieve()`` and reports the
top chunk IDs for each. The same call also appends one record per query
to ``lean_rag/logs/retrieval.log.jsonl`` (verified at the end).

This is NOT a quality eval (no tuning, no metrics) — it confirms the
artifact survived the folder move, paths resolve, the model loads, the
FAISS index loads, and the logging hook fires.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lean_rag.datastore.retrieve import retrieve  # noqa: E402

QUERIES: list[str] = [
    "set holdings to a percentage of portfolio",
    "warm up an indicator",
    "create an EMA on daily resolution",
    "schedule a function to run at market open",
    "place a limit market order for an equity",
    "consolidate trade bars into 30 minute bars",
    "get historical data for a symbol",
    "subscribe to a symbol at hourly resolution",
    "register an option chain",
    "set the algorithm warm up period",
]

LOG_PATH = REPO_ROOT / "lean_rag" / "logs" / "retrieval.log.jsonl"


def _id_line(text: str) -> str:
    """Best-effort identifier line for a chunk text (first non-empty line)."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return "(empty chunk)"


def main() -> int:
    log_lines_before = LOG_PATH.read_text(encoding="utf-8").count("\n") if LOG_PATH.exists() else 0

    for i, q in enumerate(QUERIES, 1):
        chunks = retrieve(q)
        print(f"\n[{i:02d}] query: {q}")
        print(f"     returned {len(chunks)} chunks")
        for j, c in enumerate(chunks, 1):
            print(f"       {j}. {_id_line(c)}")

    log_lines_after = LOG_PATH.read_text(encoding="utf-8").count("\n")
    appended = log_lines_after - log_lines_before
    print(f"\nlog: {LOG_PATH}")
    print(f"log lines before: {log_lines_before}")
    print(f"log lines after:  {log_lines_after}")
    print(f"log lines appended this run: {appended}")

    if appended != len(QUERIES):
        print(f"FAIL: expected {len(QUERIES)} new log lines, got {appended}")
        return 1

    # Spot-check the last record actually has the expected fields.
    last_record = LOG_PATH.read_text(encoding="utf-8").rstrip("\n").rsplit("\n", 1)[-1]
    parsed = json.loads(last_record)
    for key in ("ts", "query", "returned_ids", "top_k"):
        if key not in parsed:
            print(f"FAIL: log record missing key {key!r}")
            return 1
    if parsed["top_k"] != 5:
        print(f"FAIL: top_k={parsed['top_k']!r}, expected 5")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
