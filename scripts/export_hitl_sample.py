"""Export a stratified HITL (human-in-the-loop) validation sample.

Draws a reproducible sample of judged calls for human labeling and writes
both JSONL (canonical) and CSV (spreadsheet-friendly) files. Each row
contains the prompt, generated code, a compact execution summary, the
judge's score / intent flag / failure mode, and blank fields for human
labelers to fill in.

Usage (from project root):
    .\\.venv\\Scripts\\python.exe scripts\\export_hitl_sample.py
        [--out-jsonl validation/hitl_sample.jsonl]
        [--out-csv   validation/hitl_sample.csv]
        [--per-cell  3]                # default per-stratum target
        [--seed      20260513]         # default deterministic seed
        [--db        results/leanbench.db]
        [--require-frozen]             # abort if frozen artifact missing/mismatched

Stratification:
  - Sampled from rows where calls.prompt_set_sha256 == frozen hash AND
    calls.status = 'completed' AND calls.judge_pass IS NOT NULL.
  - Stratum = (model_id, condition_id). Excluded cells produce zero rows
    (they're not in the population by design).
  - Within a stratum, sampling is further balanced across score bins
    (≤0.3, 0.4–0.6, 0.7–0.8, 0.9–1.0) and across the distinct primary
    failure modes seen — best-effort coverage, not strict quotas.

Output schema (per row in JSONL / CSV):
    call_id, prompt_id, model_id, condition_id, trial_index,
    benchmark_version, prompt_set_sha256, judge_version, judge_threshold,
    prompt_text, generated_code,
    backtest_summary { compile_success, runtime_success, runtime_error,
        num_trades, sharpe_ratio, total_return_pct },
    judge_score, judge_failure_mode, matches_prompt_intent_judge,
    # blank human-label fields (rubric is the same 0.0-1.0 scale):
    human_score, matches_prompt_intent_human, human_failure_mode, human_notes

Reuses the same rubric and failure-mode taxonomy as the judge. NEVER use
this export to tune the judge threshold (see decision log §3).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from harness.constants import BENCHMARK_VERSION, JUDGE_PASS_THRESHOLD
from harness.judge import JUDGE_VERSION
from harness.prompt_freeze import load_frozen
from harness.storage import Store

DEFAULT_DB = Path("results/leanbench.db")
DEFAULT_FROZEN = Path("results/frozen/prompt_set_v1.json")
DEFAULT_OUT_JSONL = Path("validation/hitl_sample.jsonl")
DEFAULT_OUT_CSV   = Path("validation/hitl_sample.csv")
DEFAULT_PER_CELL = 3
DEFAULT_SEED = 20260513


def _score_bin(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score <= 0.3:
        return "0.0-0.3"
    if score < 0.7:
        return "0.4-0.6"
    if score < 0.9:
        return "0.7-0.8"
    return "0.9-1.0"


def _primary_failure(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return ""
    if isinstance(parsed, list) and parsed:
        return str(parsed[0])
    if isinstance(parsed, str):
        return parsed
    return ""


def _stratified_pick(
    rows: list[dict],
    per_cell: int,
    rng: random.Random,
) -> list[dict]:
    """For each (model, condition) stratum, pick up to `per_cell` rows,
    spreading across score bins and primary failure modes when possible.
    """
    by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_cell[(r["model_id"], r["condition_id"])].append(r)

    picked: list[dict] = []
    for cell, cell_rows in sorted(by_cell.items()):
        if not cell_rows:
            continue
        # Index by (score_bin, primary_failure) — best-effort balance.
        bins: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in cell_rows:
            key = (_score_bin(r.get("judge_score")), _primary_failure(r.get("failure_mode")))
            bins[key].append(r)
        # Round-robin draw from non-empty bins.
        ordered_keys = sorted(bins.keys())
        rng.shuffle(ordered_keys)
        for v in bins.values():
            rng.shuffle(v)
        chosen: list[dict] = []
        idx = 0
        while len(chosen) < per_cell and any(bins[k] for k in ordered_keys):
            k = ordered_keys[idx % len(ordered_keys)]
            if bins[k]:
                chosen.append(bins[k].pop())
            idx += 1
        picked.extend(chosen)
    return picked


def _prompt_record_for_judge(prompt_row: dict, prompt_text: str) -> dict:
    """Subset of the prompts row the production judge sees.

    Mirrors what harness/orchestrator.py passes to judge_call() so that
    re-judging during validation uses the same context the live judge had.
    `harness/judge.py:_build_user_message` reads these fields by name.
    """
    return {
        "reformulated_text":         prompt_text,
        "original_text":             prompt_row.get("original_text") or prompt_text,
        "strategy_type":             prompt_row.get("strategy_type"),
        "evaluation_mode":           prompt_row.get("evaluation_mode"),
        "interpretation_strictness": prompt_row.get("interpretation_strictness"),
        "securities_type":           prompt_row.get("securities_type"),
        "resolution":                prompt_row.get("resolution"),
        "universe_type":             prompt_row.get("universe_type"),
        "tickers":                   prompt_row.get("tickers"),
        "indicators":                prompt_row.get("indicators"),
        "implementation_type":       prompt_row.get("implementation_type"),
        "leak_audit_notes":          prompt_row.get("leak_audit_notes"),
        "curator_notes":             prompt_row.get("curator_notes"),
    }


def _row_to_export(row: dict, prompt_row: dict, prompt_text: str) -> dict:
    backtest_summary = {
        "compile_success":   row.get("compile_success"),
        "runtime_success":   row.get("runtime_success"),
        "runtime_error":     (row.get("runtime_error") or "")[:300] or None,
        "num_trades":        row.get("num_trades"),
        "sharpe_ratio":      row.get("sharpe_ratio"),
        "total_return_pct":  row.get("total_return_pct"),
    }
    return {
        "call_id":                     row.get("call_id"),
        "prompt_id":                   row.get("prompt_id"),
        "model_id":                    row.get("model_id"),
        "condition_id":                row.get("condition_id") or row.get("condition"),
        "trial_index":                 row.get("trial_index") or row.get("pass_number") or 0,
        "benchmark_version":           row.get("benchmark_version") or BENCHMARK_VERSION,
        "prompt_set_sha256":           row.get("prompt_set_sha256"),
        "judge_version":               row.get("judge_version") or JUDGE_VERSION,
        "judge_threshold":             row.get("judge_threshold") or JUDGE_PASS_THRESHOLD,
        "prompt_text":                 prompt_text,
        # Full judge-input metadata. validate_judge.py reads this into the
        # prompt_record that judge_call() consumes, matching production.
        "prompt_record":               _prompt_record_for_judge(prompt_row, prompt_text),
        "generated_code":              row.get("generated_code"),
        "backtest_summary":            backtest_summary,
        # Mirror as backtest_result so validate_judge can pass it straight
        # through to judge_call without a translation layer.
        "backtest_result":             backtest_summary,
        "judge_score":                 row.get("judge_score"),
        "judge_failure_mode":          _primary_failure(row.get("failure_mode")),
        "matches_prompt_intent_judge": bool(row.get("matches_prompt_intent")) if row.get("matches_prompt_intent") is not None else None,
        # Blank human-label fields — same 0.0–1.0 rubric as the judge.
        # `human_failure_mode` accepts either a single string (CSV) or a
        # JSON list (JSONL). validate_judge normalizes both to a list.
        "human_score":                 None,
        "matches_prompt_intent_human": None,
        "human_failure_mode":          "",
        "human_notes":                 "",
    }


CSV_COLUMNS = (
    "call_id", "prompt_id", "model_id", "condition_id", "trial_index",
    "benchmark_version", "prompt_set_sha256", "judge_version", "judge_threshold",
    "judge_score", "judge_failure_mode", "matches_prompt_intent_judge",
    "prompt_text", "generated_code",
    "backtest_compile_success", "backtest_runtime_success", "backtest_num_trades",
    "backtest_sharpe_ratio", "backtest_total_return_pct", "backtest_runtime_error",
    # Blank human-label columns
    "human_score", "matches_prompt_intent_human", "human_failure_mode", "human_notes",
)


def _flatten_for_csv(item: dict) -> dict:
    bt = item.get("backtest_summary") or {}
    flat = dict(item)
    flat.pop("backtest_summary", None)
    flat["backtest_compile_success"]   = bt.get("compile_success")
    flat["backtest_runtime_success"]   = bt.get("runtime_success")
    flat["backtest_num_trades"]        = bt.get("num_trades")
    flat["backtest_sharpe_ratio"]      = bt.get("sharpe_ratio")
    flat["backtest_total_return_pct"]  = bt.get("total_return_pct")
    flat["backtest_runtime_error"]     = bt.get("runtime_error")
    return flat


def main(
    out_jsonl: Path,
    out_csv: Path,
    db_path: Path,
    frozen_path: Path,
    per_cell: int,
    seed: int,
    require_frozen: bool,
) -> int:
    frozen_hash: str | None = None
    if frozen_path.exists():
        _, frozen_hash = load_frozen(frozen_path)
    elif require_frozen:
        print(f"ERROR: required frozen artifact missing at {frozen_path}", file=sys.stderr)
        return 2

    store = Store(db_path)

    # Population: completed, judged, frozen-prompt-set rows only. Excluded
    # and adhoc rows are filtered out by definition.
    where = [
        "COALESCE(status, 'completed') = 'completed'",
        "judge_pass IS NOT NULL",
        "generated_code IS NOT NULL",
    ]
    params: list = []
    if frozen_hash is not None:
        where.append("prompt_set_sha256 = ?")
        params.append(frozen_hash)
    sql = f"SELECT * FROM calls WHERE {' AND '.join(where)}"
    rows = [dict(r) for r in store.conn.execute(sql, params).fetchall()]
    if not rows:
        print(f"No eligible rows for HITL export.", file=sys.stderr)
        if frozen_hash:
            print(f"  filter: prompt_set_sha256={frozen_hash[:12]}...", file=sys.stderr)
        return 1

    rng = random.Random(seed)
    picked = _stratified_pick(rows, per_cell, rng)

    # Composition summary for the report.
    by_cell: dict[tuple[str, str], int] = defaultdict(int)
    by_bin:  dict[str, int] = defaultdict(int)
    for r in picked:
        by_cell[(r["model_id"], r["condition_id"])] += 1
        by_bin[_score_bin(r.get("judge_score"))] += 1

    prompts_by_id = {p["prompt_id"]: p for p in store.list_prompts()}

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as fj, \
         out_csv.open("w", newline="", encoding="utf-8") as fc:
        writer = csv.DictWriter(fc, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in picked:
            prompt = prompts_by_id.get(r["prompt_id"]) or {}
            prompt_text = prompt.get("reformulated_text") or prompt.get("original_text") or ""
            item = _row_to_export(r, prompt, prompt_text)
            fj.write(json.dumps(item, ensure_ascii=False) + "\n")
            writer.writerow({k: _flatten_for_csv(item).get(k) for k in CSV_COLUMNS})

    print(f"Exported HITL sample:")
    print(f"  rows:         {len(picked)}")
    print(f"  seed:         {seed}")
    print(f"  per-cell:     {per_cell}")
    print(f"  frozen hash:  {frozen_hash}")
    print(f"  composition by (model, condition):")
    for cell, n in sorted(by_cell.items()):
        print(f"    {cell[0]:<24} {cell[1]:<20} n={n}")
    print(f"  composition by score bin:")
    for b in ("0.0-0.3", "0.4-0.6", "0.7-0.8", "0.9-1.0", "unknown"):
        print(f"    {b:<10} n={by_bin.get(b, 0)}")
    print(f"  wrote JSONL: {out_jsonl}")
    print(f"  wrote CSV:   {out_csv}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-jsonl", type=Path, default=DEFAULT_OUT_JSONL)
    p.add_argument("--out-csv",   type=Path, default=DEFAULT_OUT_CSV)
    p.add_argument("--db",        type=Path, default=DEFAULT_DB)
    p.add_argument("--frozen",    type=Path, default=DEFAULT_FROZEN)
    p.add_argument("--per-cell",  type=int, default=DEFAULT_PER_CELL)
    p.add_argument("--seed",      type=int, default=DEFAULT_SEED)
    p.add_argument("--require-frozen", action="store_true",
                   help="Abort if the frozen artifact is missing or unreadable")
    args = p.parse_args()
    raise SystemExit(main(
        out_jsonl=args.out_jsonl,
        out_csv=args.out_csv,
        db_path=args.db,
        frozen_path=args.frozen,
        per_cell=args.per_cell,
        seed=args.seed,
        require_frozen=args.require_frozen,
    ))
