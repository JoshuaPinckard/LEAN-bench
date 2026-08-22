"""Phase 2.2-2.3: reference drafting (k=3 per task, opus/opus/sonnet) + tape execution.

Each reference: strict-fidelity prompt (prompts/ref_impl_prompt.txt) -> claude CLI
fresh context -> extract python + assumptions blocks -> execute on frozen cache via
tape_exec -> results/refs/task<id>_ref<idx>.json + ledger row.

Resumable: ledger rows already present are skipped. SessionLimitError halts cleanly.
"""
import concurrent.futures
import json
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import common  # noqa: E402
import tape_exec  # noqa: E402
from cli import SessionLimitError  # noqa: E402
from call_surfaces import call_drafter  # noqa: E402

# Owner ruling 2026-08-21: one drafter per FAMILY (was opus/opus/sonnet
# in the claude-only pilot, a quota accident not a design). ref2 (gemini)
# pends the Vertex word and is skipped until then; the ledger is
# resumable so ref2 back-fills per task later.
REF_FAMILIES = {0: "claude", 1: "codex", 2: "gemini"}
TEMPLATE = (common.PROMPTS / "ref_impl_prompt.txt").read_text(encoding="utf-8")
MANIFEST = json.loads((common.FROZEN / "cache_manifest.json").read_text(encoding="utf-8"))
REFS_DIR = common.RESULTS / "refs"


def extract_blocks(text: str):
    py = None
    assumptions = []
    m = re.search(r"```python\s*(.*?)```", text, re.S)
    if m:
        py = m.group(1).strip()
    mj = re.search(r"```json\s*(.*?)```", text, re.S)
    if mj:
        try:
            assumptions = json.loads(mj.group(1)).get("assumptions", [])
        except Exception:
            assumptions = [{"topic": "assumptions_parse_error",
                            "choice": mj.group(1)[:300], "reason": ""}]
    return py, assumptions


def do_ref(task, idx, reqs):
    family = REF_FAMILIES[idx]
    model = {"claude": "claude-sonnet-5", "codex": "gpt-5.6-terra(medium)", "gemini": "gemini-flash(vertex-pending)"}[family]
    cache = common.cache_path_for(task)
    m = MANIFEST[cache.name]
    r = reqs[task["id"]]
    prompt = (TEMPLATE
              .replace("{SYMBOL}", r["yf_symbol"])
              .replace("{TIMEFRAME}", r["timeframe"])
              .replace("{RANGE}", f"{m['index_min']} to {m['index_max']} ({m['rows']} bars)")
              .replace("{task}", task["reformulated_task"]))

    raw_path = REFS_DIR / f"task{task['id']}_ref{idx}.raw.txt"
    text = call_drafter(family, prompt, raw_path)
    code, assumptions = extract_blocks(text)

    if code:
        run = tape_exec.run_tape(code, str(cache))
    else:
        run = {"success": False, "error": "no python block in output"}

    rec = {"task_id": task["id"], "ref_idx": idx, "model": model,
           "code": code, "assumptions": assumptions,
           "success": run.get("success"), "error": run.get("error"),
           "total_trades": run.get("total_trades", 0),
           "tape": run.get("tape", [])}
    (REFS_DIR / f"task{task['id']}_ref{idx}.json").write_text(
        json.dumps(rec, indent=2), encoding="utf-8")

    common.ledger_append({
        "phase": "p2", "task_id": task["id"], "role": "ref", "model": model,
        "sample_idx": idx, "success": run.get("success"),
        "n_fills": len(run.get("tape", [])), "error": run.get("error"),
        "n_assumptions": len(assumptions),
    })
    return f"task {task['id']} ref{idx} ({model}): success={run.get('success')} fills={len(run.get('tape', []))}"


def main():
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    tasks = common.load_tasks()
    reqs = common.load_requirements()
    done = common.ledger_load()

    jobs = []
    for task in sorted(tasks.values(), key=lambda t: t["id"]):
        allowed = __import__('os').environ.get("AUDIT_FAMILIES", "claude,codex").split(",")
        for idx, family in REF_FAMILIES.items():
            if family == "gemini":
                continue          # pends the owner's Vertex word; ledger back-fills later
            if family not in allowed:
                continue          # e.g. AUDIT_FAMILIES=codex while the claude session is busy elsewhere
            model = {"claude": "claude-sonnet-5", "codex": "gpt-5.6-terra(medium)"}[family]
            key = f"p2|{task['id']}|ref|{model}|{idx}"
            if key in done:
                continue
            jobs.append((task, idx))

    print(f"{len(jobs)} reference jobs to run (of {len(tasks) * 3})")
    halted = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(__import__('os').environ.get('AUDIT_WORKERS', '3'))) as ex:
        futs = {ex.submit(do_ref, t, i, reqs): (t["id"], i) for t, i in jobs}
        for fut in concurrent.futures.as_completed(futs):
            tid, idx = futs[fut]
            try:
                print(fut.result(), flush=True)
            except SessionLimitError as e:
                print(f"SESSION LIMIT at task {tid} ref{idx}: {e} — halting (resume later)", flush=True)
                halted = True
                for f in futs:
                    f.cancel()
                break
            except Exception:
                print(f"task {tid} ref{idx} FAILED:\n{traceback.format_exc()}", flush=True)

    print("PHASE2 REF BATCH:", "HALTED (resumable)" if halted else "COMPLETE")
    sys.exit(2 if halted else 0)


if __name__ == "__main__":
    main()
