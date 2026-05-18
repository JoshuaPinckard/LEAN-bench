"""Judge validation harness.

Loads a hand-scored set of calls from a JSONL file and runs the current judge
against each, reporting:
  - Pearson and Spearman correlation between human and judge scores
  - Mean absolute error
  - Per-call disagreements > 0.3 (flagged)
  - Intent agreement (matches_prompt_intent: human vs judge)
  - Per-failure-mode agreement rate
  - Sample composition: counts by (model_id, condition_id) and score bin

Run from the project root:
    .\\.venv\\Scripts\\python.exe scripts\\validate_judge.py validation/handscored.jsonl

Hand-scored file format (one JSON object per line, ideally produced by
`scripts/export_hitl_sample.py`):
    {
      "call_id":          "...",            # optional, for reference
      "prompt_record":    {...},            # subset of prompts row (text + metadata)
      "generated_code":   "...",
      "backtest_result":  {...},            # compile_success, runtime_success, ...
      "human_score":      0.7,
      "matches_prompt_intent_human": true,  # optional
      "human_failure_mode": ["wrong_indicator"]  # optional
    }

Also accepts the output schema from `scripts/export_hitl_sample.py` (model_id /
condition_id / backtest_summary at the top level) once humans fill in the
`human_score`, `matches_prompt_intent_human`, and `human_failure_mode` columns.

Targets (per spec — soft, not hard gates):
  - correlation ~0.8
  - failure-mode exact-match agreement ~0.75
The author makes the final call on whether to ship the current judge_version.

IMPORTANT: This script evaluates judge credibility. It does NOT optimize the
pass threshold (see docs/benchmark_decision_log.md §3).
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


def _adapt_export_format(item: dict) -> dict:
    """Adapt the HITL export-script row format into what _score_one expects.

    The exporter writes both `prompt_record` (full metadata mirroring what
    the production judge sees) AND a flat `prompt_text` for human readability.
    Prefer `prompt_record` when present so validation uses the same context
    the live judge had. Falls back to a thin record built from prompt_text
    when only an old-format file is provided.
    Idempotent.
    """
    if "prompt_record" not in item and "prompt_text" in item:
        item["prompt_record"] = {
            "reformulated_text":         item["prompt_text"],
            "original_text":             item["prompt_text"],
            "strategy_type":             item.get("strategy_type"),
            "evaluation_mode":           item.get("evaluation_mode"),
            "interpretation_strictness": item.get("interpretation_strictness"),
        }
    if "backtest_result" not in item and "backtest_summary" in item:
        item["backtest_result"] = item["backtest_summary"]
    if "matches_prompt_intent_human" in item and "human_matches_prompt_intent" not in item:
        item["human_matches_prompt_intent"] = item["matches_prompt_intent_human"]
    # human_failure_mode may be a single string (CSV) OR a JSON list (legacy
    # JSONL). Normalize to a list so primary-mode comparison is correct.
    raw_hfm = item.get("human_failure_mode")
    if isinstance(raw_hfm, str):
        s = raw_hfm.strip()
        if not s:
            item["human_failure_mode"] = []
        elif s.startswith("["):
            try:
                parsed = json.loads(s)
                item["human_failure_mode"] = parsed if isinstance(parsed, list) else [s]
            except json.JSONDecodeError:
                item["human_failure_mode"] = [s]
        else:
            item["human_failure_mode"] = [s]
    elif raw_hfm is None:
        item["human_failure_mode"] = []
    return item


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
    items = [_adapt_export_format(it) for it in _load_jsonl(path)]
    # Only keep rows that have a human label — export rows with blank
    # human_score are not yet ready for validation.
    items = [it for it in items if it.get("human_score") is not None]
    if not items:
        print(f"No labeled items in {path} (rows must have non-null human_score)", file=sys.stderr)
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

    # Intent agreement (matches_prompt_intent boolean)
    intent_total = 0
    intent_agree = 0
    for item, j in results:
        h_intent = item.get("human_matches_prompt_intent")
        if not isinstance(h_intent, bool):
            continue
        j_intent = bool(j.get("matches_prompt_intent"))
        intent_total += 1
        if h_intent == j_intent:
            intent_agree += 1
    if intent_total:
        print()
        print("=== matches_prompt_intent agreement ===")
        print(f"  N (with human intent label): {intent_total}")
        print(f"  Exact agreement:             {intent_agree}/{intent_total}  ({intent_agree/intent_total:.0%})")

    # Sample composition by stratum (model_id, condition_id) and score bin.
    from collections import Counter

    def _bin(s: float) -> str:
        if s <= 0.3: return "0.0-0.3"
        if s <  0.7: return "0.4-0.6"
        if s <  0.9: return "0.7-0.8"
        return "0.9-1.0"

    cell_counts: Counter[tuple[str, str]] = Counter()
    bin_counts:  Counter[str] = Counter()
    for item, _ in results:
        cell = (str(item.get("model_id") or "?"), str(item.get("condition_id") or "?"))
        cell_counts[cell] += 1
        bin_counts[_bin(float(item["human_score"]))] += 1
    print()
    print("=== Sample composition ===")
    print("  by (model, condition):")
    for (m, c), n in sorted(cell_counts.items()):
        print(f"    {m:<24} {c:<20} n={n}")
    print("  by human-score bin:")
    for b in ("0.0-0.3", "0.4-0.6", "0.7-0.8", "0.9-1.0"):
        print(f"    {b:<10} n={bin_counts.get(b, 0)}")

    print()
    print("Author makes the call on whether to ship this judge_version.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", type=Path, help="JSONL file of hand-scored calls")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(args.path)))
