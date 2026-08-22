"""Phase 3: candidate generation -> their gates -> their judge (replicated) -> tape compare.

Input:  results/metric1.json  {"determinate_ids": [...], ...}  (written by adjudication)
        results/tapes/ref_<id>.json  canonical reference tapes
Per determinate task: 4 candidates (sonnet x2, haiku x2), their exact single-shot
prompt, gates, judge only on gate survivors (their control flow), tape comparison
vs canonical tape. Everything to results/gens/ + ledger. Resumable.
"""
import concurrent.futures
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import gates  # noqa: E402
import judge_repl  # noqa: E402
import tape_compare  # noqa: E402
from cli import call_claude, SessionLimitError  # noqa: E402

GEN_MODELS = [("sonnet", 0), ("sonnet", 1), ("haiku", 0), ("haiku", 1)]
GENS_DIR = common.RESULTS / "gens"

SYSTEM = (common.PROMPTS / "system_prompt_full.txt").read_text(encoding="utf-8")
USER_SINGLE = (common.PROMPTS / "user_prompt_single.txt").read_text(encoding="utf-8")


def do_candidate(task, model, sample_idx):
    tid = task["id"]
    ref_tape = json.loads(
        (common.RESULTS / "tapes" / f"ref_{tid}.json").read_text(encoding="utf-8"))["tape"]

    gen_prompt = SYSTEM + USER_SINGLE.replace("{prompt}", task["reformulated_task"])
    raw_path = GENS_DIR / f"task{tid}_{model}_{sample_idx}.raw.txt"
    raw = call_claude(gen_prompt, model, raw_path, min_bytes=200)

    g = gates.run_gates(raw, common.cache_path_for(task))

    j = None
    if g["gates_pass"]:
        j = judge_repl.judge(task["reformulated_task"], g["cleaned_code"],
                             GENS_DIR / f"task{tid}_{model}_{sample_idx}.judge.txt")

    cmp_ = tape_compare.compare(g["tape"], ref_tape)

    rec = {"task_id": tid, "model": model, "sample_idx": sample_idx,
           "gates": {k: v for k, v in g.items() if k not in ("tape", "cleaned_code")},
           "cleaned_code": g["cleaned_code"], "tape": g["tape"],
           "judge": j, "compare": cmp_}
    (GENS_DIR / f"task{tid}_{model}_{sample_idx}.json").write_text(
        json.dumps(rec, indent=2), encoding="utf-8")

    common.ledger_append({
        "phase": "p3", "task_id": tid, "role": "gen", "model": model,
        "sample_idx": sample_idx, "gates_pass": g["gates_pass"],
        "judge_aligned": (j or {}).get("judge_aligned"),
        "judge_mode": (j or {}).get("judge_mode"),
        "primary_match": cmp_["primary_match"],
        "n_fills": cmp_["candidate_fills"],
    })
    verdict = ("FALSE-PASS" if j and j["judge_aligned"] and not cmp_["primary_match"]
               else "ok")
    return (f"task {tid} {model}#{sample_idx}: gates={g['gates_pass']} "
            f"judge={(j or {}).get('judge_aligned')} match={cmp_['primary_match']} {verdict}")


def main():
    GENS_DIR.mkdir(parents=True, exist_ok=True)
    metric1 = json.loads((common.RESULTS / "metric1.json").read_text(encoding="utf-8"))
    det_ids = metric1["determinate_ids"]
    tasks = common.load_tasks()
    done = common.ledger_load()

    jobs = []
    for tid in det_ids:
        for model, sidx in GEN_MODELS:
            if f"p3|{tid}|gen|{model}|{sidx}" not in done:
                jobs.append((tasks[tid], model, sidx))

    print(f"{len(jobs)} candidate jobs to run ({len(det_ids)} determinate tasks x 4)")
    halted = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(do_candidate, t, m, s): (t["id"], m, s) for t, m, s in jobs}
        for fut in concurrent.futures.as_completed(futs):
            tid, m, s = futs[fut]
            try:
                print(fut.result(), flush=True)
            except SessionLimitError as e:
                print(f"SESSION LIMIT at task {tid} {m}#{s}: {e} — halting", flush=True)
                halted = True
                for f in futs:
                    f.cancel()
                break
            except Exception:
                print(f"task {tid} {m}#{s} FAILED:\n{traceback.format_exc()}", flush=True)

    print("PHASE3 BATCH:", "HALTED (resumable)" if halted else "COMPLETE")
    sys.exit(2 if halted else 0)


if __name__ == "__main__":
    main()
