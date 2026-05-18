"""Freeze the benchmark-eligible prompts to a canonical artifact.

Run this BEFORE any main benchmark run. The output is the reproducibility
anchor: its SHA256 is stamped on every call (calls.prompt_set_sha256), and
the orchestrator refuses to start if the live DB hash diverges.

Usage (from project root):
    .\\.venv\\Scripts\\python.exe scripts\\freeze_prompt_set.py
        [--out results/frozen/prompt_set_v1.json]
        [--db  results/leanbench.db]
        [--check]   # don't write; just print the hash that would be written

Exit codes:
    0 — wrote (or would write) successfully
    1 — no eligible prompts found
    2 — --check used and on-disk hash diverges from current DB

The canonical field set lives in harness/prompt_freeze.py; see
docs/benchmark_decision_log.md for the methodology rationale.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from harness.constants import BENCHMARK_VERSION, LEAN_CLI_VERSION, LEAN_ENGINE_IMAGE
from harness.prompt_freeze import canonicalize, is_eligible, load_frozen, sha256_of
from harness.storage import Store

DEFAULT_OUT = Path("results/frozen/prompt_set_v1.json")
DEFAULT_DB = Path("results/leanbench.db")


def main(out_path: Path, db_path: Path, check_only: bool) -> int:
    store = Store(db_path)
    rows = store.list_prompts()
    eligible = [p for p in rows if is_eligible(p)]
    if not eligible:
        print(f"ERROR: no eligible prompts in {db_path}", file=sys.stderr)
        print(f"  total prompts: {len(rows)}  (excludes adhoc + excluded_from_benchmark)", file=sys.stderr)
        return 1

    canonical = canonicalize(eligible)
    live_hash = sha256_of(canonical)

    print(f"Benchmark version: {BENCHMARK_VERSION}")
    print(f"Eligible prompts:  {len(eligible)} / {len(rows)} total")
    print(f"Canonical SHA256:  {live_hash}")
    print(f"Canonical size:    {len(canonical):,} bytes")

    if check_only:
        if not out_path.exists():
            print(f"\nNo frozen artifact at {out_path} yet. Run without --check to create one.")
            return 0
        _, on_disk_hash = load_frozen(out_path)
        print(f"On-disk SHA256:    {on_disk_hash}")
        if on_disk_hash != live_hash:
            print("\nMISMATCH: live DB diverges from frozen artifact.", file=sys.stderr)
            return 2
        print("\nOK: live DB matches frozen artifact.")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(canonical)

    # Drop a sidecar metadata file so it's obvious when the freeze was taken
    # without affecting the canonical bytes. Stamping the LEAN execution pins
    # makes every freeze traceable to the exact CLI + engine image that
    # benchmark runs against this artifact will use; mirrors the canonical
    # discipline the RAG datastore uses for its embedding stack.
    meta_path = out_path.with_suffix(out_path.suffix + ".meta.json")
    meta = {
        "benchmark_version": BENCHMARK_VERSION,
        "prompt_set_sha256": live_hash,
        "count":             len(eligible),
        "frozen_at_utc":     datetime.now(timezone.utc).isoformat(),
        "lean_cli_version":  LEAN_CLI_VERSION,
        "lean_engine_image": LEAN_ENGINE_IMAGE,
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote frozen artifact -> {out_path}")
    print(f"Wrote freeze metadata -> {meta_path}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"Output path (default {DEFAULT_OUT})")
    p.add_argument("--db",  type=Path, default=DEFAULT_DB,  help=f"SQLite DB (default {DEFAULT_DB})")
    p.add_argument("--check", action="store_true", help="Don't write; compare live DB hash to on-disk frozen artifact")
    args = p.parse_args()
    raise SystemExit(main(args.out, args.db, args.check))
