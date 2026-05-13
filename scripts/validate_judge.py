"""Judge validation harness.

Loads a hand-scored set of calls from a JSONL file and runs the current judge
against each, reporting:
  - Pearson and Spearman correlation between human and judge scores
  - Mean absolute error
  - Per-call disagreements > 0.3 (flagged)
  - Per-failure-mode agreement rate

Run from the project root:
    .\\.venv\\Scripts\\python.exe scripts\\validate_judge.py validation/handscored.jsonl

Hand-scored file format (one JSON object per line):
    {
      "call_id":          "...",            # optional, for reference
      "prompt_record":    {...},            # subset of prompts row (text + metadata)
      "generated_code":   "...",
      "backtest_result":  {...},            # compile_success, runtime_success, ...
      "human_score":      0.7,
      "human_failure_mode": ["wrong_indicator"]  # optional
    }

Targets (per spec — soft, not hard gates):
  - correlation ~0.8
  - failure-mode exact-match agreement ~0.75
The author makes the final call on whether to ship the current judge_version.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path

# Make `harness` importable when running this script from anywhere.
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


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    den = math.sqrt(dx2 * dy2)
    return num / den if den else float("nan")


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman = Pearson on ranks."""
    def ranks(vs: list[float]) -> list[float]:
        sorted_idx = sorted(range(len(vs)), key=lambda i: vs[i])
        r = [0.0] * len(vs)
        i = 0
        while i < len(vs):
            j = i
            while j + 1 < len(vs) and vs[sorted_idx[j + 1]] == vs[sorted_idx[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[sorted_idx[k]] = avg_rank
            i = j + 1
        return r
    return _pearson(ranks(xs), ranks(ys))


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{ln}: malformed JSON: {exc}") from exc
    return out


async def _score_one(item: dict) -> dict | None:
    try:
        return await judge_call(
            prompt_record=item["prompt_record"],
            generated_code=item["generated_code"],
            backtest_result=item.get("backtest_result", {}),
        )
    except JudgeError as exc:
        print(f"  [error] call_id={item.get('call_id','?')}: {exc}", file=sys.stderr)
        return None


async def main(path: Path) -> int:
    items = _load_jsonl(path)
    if not items:
        print(f"No items in {path}", file=sys.stderr)
        return 1
    print(f"Validating judge_version={JUDGE_VERSION} against {len(items)} hand-scored calls...")

    results: list[tuple[dict, dict]] = []
    for i, item in enumerate(items, 1):
        print(f"  [{i}/{len(items)}] call_id={item.get('call_id','?')} ...", flush=True)
        judged = await _score_one(item)
        if judged is not None:
            results.append((item, judged))

    if not results:
        print("No successful judgments. Aborting.")
        return 1

    human_scores = [float(it["human_score"]) for it, _ in results]
    judge_scores = [float(j["judge_score"])  for _, j  in results]

    pearson  = _pearson(human_scores, judge_scores)
    spearman = _spearman(human_scores, judge_scores)
    mae = sum(abs(h - j) for h, j in zip(human_scores, judge_scores)) / len(results)

    flagged = [
        (item.get("call_id", "?"), human_scores[i], judge_scores[i])
        for i, (item, _) in enumerate(results)
        if abs(human_scores[i] - judge_scores[i]) > 0.3
    ]

    # Per-failure-mode exact agreement (primary mode == primary mode)
    fm_total = 0
    fm_agree = 0
    fm_disagree: list[tuple[str, list[str], list[str]]] = []
    for item, j in results:
        if "human_failure_mode" not in item:
            continue
        human_fm = item["human_failure_mode"] or []
        judge_fm = j.get("failure_mode") or []
        fm_total += 1
        h_primary = human_fm[0] if human_fm else None
        j_primary = judge_fm[0] if judge_fm else None
        if h_primary == j_primary:
            fm_agree += 1
        else:
            fm_disagree.append((item.get("call_id", "?"), human_fm, judge_fm))

    print()
    print("=== Score alignment ===")
    print(f"  N:                       {len(results)}")
    print(f"  Pearson correlation:     {pearson:.3f}   (target ~0.80)")
    print(f"  Spearman correlation:    {spearman:.3f}")
    print(f"  Mean absolute error:     {mae:.3f}")
    print(f"  Disagreements > 0.3:     {len(flagged)} of {len(results)}")
    for cid, h, j in flagged:
        print(f"    - {cid}: human={h:.2f} judge={j:.2f}")

    if fm_total:
        rate = fm_agree / fm_total
        print()
        print("=== Failure-mode agreement (primary) ===")
        print(f"  N (with human_failure_mode): {fm_total}")
        print(f"  Exact agreement:             {fm_agree}/{fm_total}  ({rate:.0%})  (target ~75%)")
        for cid, h, j in fm_disagree:
            print(f"    - {cid}: human={h or '[]'} judge={j or '[]'}")

    print()
    print("Author makes the call on whether to ship this judge_version.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", type=Path, help="JSONL file of hand-scored calls")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(args.path)))
