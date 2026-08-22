"""PLAN.md D8 stability spot-check: re-judge 10 random judged candidates x3.

Measures verdict flip rate across repeated CLI judge calls (temperature not
pinnable). Seeded selection; results to results/judge_stability.json + ledger.
"""
import concurrent.futures
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import judge_repl  # noqa: E402
from cli import SessionLimitError  # noqa: E402

GENS_DIR = common.RESULTS / "gens"
OUT_DIR = common.RESULTS / "judge_stability"

cands = sorted(p for p in GENS_DIR.glob("task*_*.json") if ".judge" not in p.name)
recs = [json.loads(p.read_text(encoding="utf-8")) for p in cands]
recs = [r for r in recs if r.get("judge")]
rng = random.Random(20260712)
picked = rng.sample(recs, min(10, len(recs)))

tasks = common.load_tasks()
jobs = [(r, k) for r in picked for k in range(3)]
print(f"{len(jobs)} stability judge calls")


def do_one(rec, k):
    tid, model, sidx = rec["task_id"], rec["model"], rec["sample_idx"]
    out = OUT_DIR / f"task{tid}_{model}_{sidx}_rep{k}.txt"
    j = judge_repl.judge(tasks[tid]["reformulated_task"], rec["cleaned_code"], out)
    return {"task_id": tid, "model": model, "sample_idx": sidx, "rep": k,
            "orig_aligned": rec["judge"]["judge_aligned"],
            "rep_aligned": j["judge_aligned"], "judge_mode": j["judge_mode"]}


OUT_DIR.mkdir(parents=True, exist_ok=True)
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
    futs = [ex.submit(do_one, r, k) for r, k in jobs]
    for f in concurrent.futures.as_completed(futs):
        try:
            res = f.result()
            results.append(res)
            print(f"task {res['task_id']} {res['model']}#{res['sample_idx']} rep{res['rep']}: "
                  f"{res['rep_aligned']} (orig {res['orig_aligned']})", flush=True)
        except SessionLimitError as e:
            print(f"SESSION LIMIT: {e}", flush=True)
            break
        except Exception as e:
            print(f"stability call failed: {e}", flush=True)

flips = sum(1 for r in results if r["rep_aligned"] != r["orig_aligned"])
(common.RESULTS / "judge_stability.json").write_text(
    json.dumps({"n_calls": len(results), "flips": flips, "rows": results}, indent=2),
    encoding="utf-8")
print(f"STABILITY: {flips}/{len(results)} verdict flips vs original")
