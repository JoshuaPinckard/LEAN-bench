"""Targeted reference retries for infrastructure/output-corruption failures only
(usage: python retry_refs.py <task_id> <ref_idx> [<ref_idx> ...]).

Justification per PLAN.md: retries are limited to cases where NO valid deliverable
was produced (empty/truncated model output, CLI failure) — never to re-roll a
reference that ran and diverged. Each retry appends a fresh ledger row.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import run_phase2  # noqa: E402

tid = int(sys.argv[1])
idxs = [int(a) for a in sys.argv[2:]]
task = common.load_tasks()[tid]
reqs = common.load_requirements()
for idx in idxs:
    print(f"retrying task {tid} ref{idx} ({run_phase2.REF_MODELS[idx]}) ...", flush=True)
    try:
        print(run_phase2.do_ref(task, idx, reqs), flush=True)
    except Exception as e:
        print(f"retry task {tid} ref{idx} FAILED: {e}", flush=True)
print("RETRIES DONE")
