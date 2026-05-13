"""Re-run the judge on existing calls.

When the judge's rubric or system prompt changes, bump JUDGE_VERSION in
harness/judge.py and run this script to overwrite stale judgments in place.

Usage (from project root):
    .\\.venv\\Scripts\\python.exe scripts\\rejudge.py
        [--target-version v2]    # default: current JUDGE_VERSION from harness/judge.py
        [--limit 50]             # cap the number of calls to re-judge in this run
        [--dry-run]              # print what would change, write nothing
        [--prompt-id lb-0042]    # restrict to a single prompt
        [--include-equal]        # also re-score calls whose stored version already matches

Selection rule (default): re-score every calls row where:
  - generated_code IS NOT NULL
  - error IS NULL
  - (judge_version IS NULL OR judge_version != target_version)

Re-scored fields (overwrite in place): judge_score, judge_reasoning, judge_version,
failure_mode, failure_notes, matches_prompt_intent. The previous judgment is NOT
preserved by this script — export externally first if you need the history.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env")
for vite, std in (
    ("VITE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    ("VITE_OPENAI_API_KEY",    "OPENAI_API_KEY"),
    ("VITE_GEMINI_API_KEY",    "GEMINI_API_KEY"),
):
    if not os.environ.get(std) and os.environ.get(vite):
        os.environ[std] = os.environ[vite]

from harness.judge import JUDGE_VERSION, JudgeError, judge_call
from harness.storage import Store


def _select_calls(store: Store, target_version: str, include_equal: bool, prompt_id: str | None, limit: int | None) -> list[dict]:
    where = ["generated_code IS NOT NULL", "error IS NULL"]
    params: list = []
    if not include_equal:
        where.append("(judge_version IS NULL OR judge_version != ?)")
        params.append(target_version)
    if prompt_id is not None:
        where.append("prompt_id = ?")
        params.append(prompt_id)
    sql = f"SELECT * FROM calls WHERE {' AND '.join(where)} ORDER BY COALESCE(created_at, request_timestamp)"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in store.conn.execute(sql, params).fetchall()]


def _reconstruct_backtest_result(row: dict) -> dict:
    """Build the backtest_result dict from whatever's been written to the call row."""
    return {
        "compile_success":         row.get("compile_success") if row.get("compile_success") is not None else row.get("compile_pass"),
        "runtime_success":         row.get("runtime_success") if row.get("runtime_success") is not None else row.get("backtest_pass"),
        "runtime_error":           row.get("runtime_error"),
        "lean_results_json":       row.get("lean_results_json"),
        "total_return_pct":        row.get("total_return_pct"),
        "sharpe_ratio":            row.get("sharpe_ratio"),
        "max_drawdown_pct":        row.get("max_drawdown_pct"),
        "num_trades":              row.get("num_trades"),
    }


async def main(target_version: str, limit: int | None, dry_run: bool, prompt_id: str | None, include_equal: bool) -> int:
    store = Store()
    rows = _select_calls(store, target_version, include_equal, prompt_id, limit)
    if not rows:
        print(f"No calls match the selection (target_version={target_version!r}, "
              f"prompt_id={prompt_id}, include_equal={include_equal}).")
        return 0
    print(f"Re-judging {len(rows)} call(s) -> judge_version={target_version!r}"
          + (" [DRY RUN]" if dry_run else ""))

    ok = 0
    skipped = 0
    failed = 0
    for i, row in enumerate(rows, 1):
        call_id = row["call_id"]
        prompt_row = store.get_prompt(row["prompt_id"])
        if prompt_row is None:
            print(f"  [{i}/{len(rows)}] {call_id[:8]} SKIP (prompt {row['prompt_id']} missing)")
            skipped += 1
            continue
        try:
            result = await judge_call(
                prompt_record=prompt_row,
                generated_code=row["generated_code"],
                backtest_result=_reconstruct_backtest_result(row),
                judge_version=target_version,
            )
        except JudgeError as exc:
            print(f"  [{i}/{len(rows)}] {call_id[:8]} FAIL: {exc}")
            failed += 1
            continue

        prev_score = row.get("judge_score")
        prev_ver = row.get("judge_version")
        print(f"  [{i}/{len(rows)}] {call_id[:8]} "
              f"{prev_ver or 'unscored'}={prev_score} -> "
              f"{target_version}={result['judge_score']:.2f} "
              f"(intent={result['matches_prompt_intent']}, modes={result['failure_mode']})")

        if not dry_run:
            store.update_call_with_judge(
                call_id,
                judge_score=result["judge_score"],
                judge_reasoning=result["judge_reasoning"],
                judge_version=result["judge_version"],
                failure_mode=result["failure_mode"],
                failure_notes=result["failure_notes"],
                matches_prompt_intent=result["matches_prompt_intent"],
            )
        ok += 1

    print()
    print(f"Done. updated={ok}  skipped={skipped}  failed={failed}"
          + (" (dry-run; no writes)" if dry_run else ""))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target-version", default=JUDGE_VERSION,
                   help=f"Judge version tag to write (default: {JUDGE_VERSION})")
    p.add_argument("--limit", type=int, default=None, help="Max calls to process this run")
    p.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    p.add_argument("--prompt-id", default=None, help="Restrict to one prompt_id")
    p.add_argument("--include-equal", action="store_true",
                   help="Also re-score calls already at the target version")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(
        target_version=args.target_version,
        limit=args.limit,
        dry_run=args.dry_run,
        prompt_id=args.prompt_id,
        include_equal=args.include_equal,
    )))
