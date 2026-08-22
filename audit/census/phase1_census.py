"""PHASE 1 of the full-corpus census (owner-ordered 2026-08-19): the mechanical
half, zero LLM calls.

Over ALL 400 QuantCode-Bench tasks:
  1. data-binding resolution per PLAN.md D2 (requirements file wins; divergence
     from task fields logged),
  2. cache coverage vs the pilot's frozen_cache (pilot pickles are IMMUTABLE -
     kept byte-identical; only missing pairs are downloaded, via the bench's
     OWN build_cache.download_pair so windows cannot drift),
  3. dead-binding identification (pairs that cannot be downloaded),
  4. a census manifest: per-task binding status + per-pair sha256.

Writes census/PHASE1-CENSUS.json + census/census_cache_manifest.json.
The pilot's cache_manifest.json and sample files are never touched.
"""
import hashlib
import importlib.util
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).parent          # qcb_audit/census
ROOT = HERE.parent                    # qcb_audit
REPO = ROOT / "QuantCode-Bench"
FROZEN = ROOT / "frozen_cache"
THEIR_CACHE = REPO / "data" / "cache"

spec = importlib.util.spec_from_file_location("build_cache", REPO / "scripts" / "build_cache.py")
build_cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_cache)

tasks = json.loads((REPO / "data" / "benchmark_tasks_multiframe.json").read_text(encoding="utf-8"))
reqs = {r["task_id"]: r for r in json.loads((REPO / "data" / "task_data_requirements.json").read_text(encoding="utf-8"))}
print(f"census over {len(tasks)} tasks")


def safe_name(symbol):
    return symbol.replace("=", "_").replace("^", "_")


def pair_of(task):
    r = reqs.get(task["id"])
    if r and (r["yf_symbol"] != task["yf_symbol"] or r["timeframe"] != task["timeframe"]):
        return (r["yf_symbol"], r["timeframe"]), "requirements-override"
    return (task["yf_symbol"], task["timeframe"]), "consistent"


pairs = {}
task_rows = []
for t in tasks:
    (sym, tf), src = pair_of(t)
    pairs.setdefault((sym, tf), []).append(t["id"])
    task_rows.append({"id": t["id"], "difficulty": t.get("difficulty"), "symbol": sym, "tf": tf, "binding": src})
print(f"distinct (symbol, timeframe) pairs: {len(pairs)}")

pair_status = {}
for (sym, tf) in sorted(pairs):
    fname = FROZEN / f"{safe_name(sym)}_{tf}.pkl"
    if fname.exists():
        pair_status[(sym, tf)] = "frozen-pilot"
        continue
    try:
        df = build_cache.download_pair(sym, tf)
        if df is None or len(df) == 0:
            pair_status[(sym, tf)] = "dead"
            print(f"  DEAD {sym}@{tf}")
            continue
        with open(fname, "wb") as fh:
            pickle.dump(df, fh)
        dest = THEIR_CACHE / fname.name
        dest.write_bytes(fname.read_bytes())
        pair_status[(sym, tf)] = "downloaded"
        print(f"  ok {sym}@{tf} rows={len(df)}")
        time.sleep(1.0)   # be polite to yahoo
    except Exception as e:
        pair_status[(sym, tf)] = f"dead: {str(e)[:80]}"
        print(f"  DEAD {sym}@{tf}: {str(e)[:80]}")

for row in task_rows:
    row["data_status"] = pair_status[(row["symbol"], row["tf"])]

cache_man = {}
for (sym, tf), st in pair_status.items():
    f = FROZEN / f"{safe_name(sym)}_{tf}.pkl"
    if f.exists():
        cache_man[f"{sym}@{tf}"] = {"status": st, "sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "bytes": f.stat().st_size}
    else:
        cache_man[f"{sym}@{tf}"] = {"status": st}

alive = [r for r in task_rows if not str(r["data_status"]).startswith("dead")]
census = {
    "generated_for": "full-corpus census phase 1 (owner order 2026-08-19; zero LLM calls)",
    "n_tasks": len(tasks), "n_pairs": len(pairs),
    "auditable_denominator": len(alive),
    "dead_tasks": [r["id"] for r in task_rows if str(r["data_status"]).startswith("dead")],
    "difficulty_hist": dict(Counter(r["difficulty"] for r in task_rows)),
    "binding_overrides": sum(1 for r in task_rows if r["binding"] == "requirements-override"),
    "pair_status_hist": dict(Counter(str(v).split(":")[0] for v in pair_status.values())),
    "tasks": task_rows,
}
(HERE / "PHASE1-CENSUS.json").write_text(json.dumps(census, indent=1), encoding="utf-8")
(HERE / "census_cache_manifest.json").write_text(json.dumps(cache_man, indent=1), encoding="utf-8")
print(json.dumps({k: census[k] for k in ("n_tasks", "n_pairs", "auditable_denominator", "difficulty_hist", "pair_status_hist", "binding_overrides")}, indent=1))
