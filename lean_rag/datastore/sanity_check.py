"""Phase 6 — Smoke test.

Run ~10 hand-written LEAN queries against the frozen index. Eyeball that
returned members look relevant. NOT a retrieval evaluation. Once this passes,
the datastore is frozen and never re-tuned.
"""

from __future__ import annotations

import json
from pathlib import Path

from .retrieve import retrieve_with_ids

SANITY_QUERIES = [
    "how to warm up an indicator",
    "set holdings to a percentage of portfolio",
    "create an EMA on daily resolution",
    "schedule a function to run at market open",
    "subscribe to a symbol at hourly resolution",
    "place a limit order for an equity",
    "consolidate trade bars into 30 minute bars",
    "get historical data for a symbol",
    "register an option chain",
    "set the algorithm warm up period",
]


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="logs/sanity_check.json", type=Path)
    args = ap.parse_args()

    results = []
    for q in SANITY_QUERIES:
        hits = retrieve_with_ids(q)
        print(f"\nQUERY: {q}")
        for cid, _text, score in hits:
            print(f"  {score:.4f}  {cid}")
        results.append(
            {
                "query": q,
                "hits": [
                    {"chunk_id": cid, "score": score} for cid, _t, score in hits
                ],
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
