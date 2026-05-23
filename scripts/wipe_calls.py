"""Wipe calls + turns from the local DB (preserves prompts + retrieval cache).

v1.0 -> v2.0 migration: the condition IDs changed from
{S1_base, S2_docs, S3_web, A1_agentic_full} to
{C1_oneshot, C2_docs, C3_compiler, C4_docs_compiler}.
Old generation results no longer fit the new factorial design, so this
script clears them so the v2 grid can be populated from a clean slate.

Run interactively (default) or non-interactively (--yes). Prompts and the
frozen prompt-set artifact are NOT touched.

Examples:
  python scripts/wipe_calls.py            # prompts for confirmation
  python scripts/wipe_calls.py --yes      # skip the prompt
  python scripts/wipe_calls.py --db results/leanbench.db --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without `pip install -e .`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.storage import DEFAULT_DB_PATH, Store


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite path")
    ap.add_argument("--yes", action="store_true", help="Skip interactive confirmation")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"DB not found at {args.db}; nothing to wipe.")
        return 0

    store = Store(args.db)
    n_calls = store.conn.execute("SELECT COUNT(*) AS n FROM calls").fetchone()["n"]
    n_turns = store.conn.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"]
    print(f"DB: {args.db}")
    print(f"  calls rows: {n_calls}")
    print(f"  turns rows: {n_turns}")

    if n_calls == 0 and n_turns == 0:
        print("Nothing to wipe.")
        return 0

    if not args.yes:
        confirm = input("Type 'wipe' to proceed: ").strip().lower()
        if confirm != "wipe":
            print("Aborted.")
            return 1

    summary = store.wipe_calls()
    print(f"Deleted {summary['calls_deleted']} calls, {summary['turns_deleted']} turns.")
    print("Prompts and retrieval cache preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
