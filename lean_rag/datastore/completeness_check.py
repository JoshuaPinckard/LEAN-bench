"""Phase 4 — Completeness check.

Mode chosen: (b) "documented members only".

Rationale: Roslyn emits XML for the exact set of `///`-documented members.
That set is identical to what the published QuantConnect API reference shows
to developers, which is the audience we are emulating in the factorial study.
Cross-checking against compiled-assembly metadata (option (a)) would inflate
the datastore with undocumented internals that no human developer would see.

We still perform the spec's required SetHoldings acceptance test: confirm
the SetHoldings overloads from QuantConnect.Algorithm.QCAlgorithm are present.
This is the exact gap that motivated the spec, so its absence is a fail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load_chunks(jsonl_path: Path) -> list[dict]:
    chunks: list[dict] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def find_setholdings_overloads(chunks: list[dict]) -> list[dict]:
    """Return all SetHoldings method chunks defined on QCAlgorithm."""
    out = []
    for c in chunks:
        if c["member_kind"] != "M":
            continue
        if c["class_fqn"] != "QuantConnect.Algorithm.QCAlgorithm":
            continue
        if c["member_name"] != "SetHoldings":
            continue
        out.append(c)
    return out


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", required=True, type=Path)
    args = ap.parse_args()

    chunks = load_chunks(args.chunks)
    print(f"Total chunks: {len(chunks)}")

    overloads = find_setholdings_overloads(chunks)
    print(f"SetHoldings overloads on QCAlgorithm: {len(overloads)}")
    for o in overloads:
        print(f"  {o['signature']}")

    if not overloads:
        print("FAIL: SetHoldings overloads missing from datastore.", file=sys.stderr)
        sys.exit(2)

    print("PASS: SetHoldings overloads present.")


if __name__ == "__main__":
    main()
