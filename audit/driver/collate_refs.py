"""Phase 2.4 input: collate reference tapes per task and compute convergence.

For each task: load its 3 reference JSONs, group successful runs by primary tape
key, propose a classification per PLAN.md D4:
  - CONVERGED           all successful refs share one non-empty tape
  - CONVERGED-EMPTY     all successful refs share the empty tape
  - DIVERGED            successful refs split across tape groups (adjudicate)
  - INSUFFICIENT        fewer than 2 successful refs (adjudicate/repair)
Writes results/convergence_summary.json and prints a table. Proposals only —
adjudication (with cited spec text) makes the final call.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from tape_compare import primary_key  # noqa: E402

REFS_DIR = common.RESULTS / "refs"


def main():
    tasks = common.load_tasks()
    summary = {}
    for tid in sorted(tasks):
        refs = []
        for idx in range(3):
            p = REFS_DIR / f"task{tid}_ref{idx}.json"
            if p.exists():
                refs.append(json.loads(p.read_text(encoding="utf-8")))
        ok = [r for r in refs if r.get("success") and r.get("code")]
        groups = defaultdict(list)
        for r in ok:
            groups[json.dumps(primary_key(r["tape"]))].append(
                f"ref{r['ref_idx']}({r['model']})")

        if len(ok) < 2:
            proposal = "INSUFFICIENT"
        elif len(groups) == 1:
            proposal = "CONVERGED-EMPTY" if not ok[0]["tape"] else "CONVERGED"
        else:
            proposal = "DIVERGED"

        summary[tid] = {
            "n_refs": len(refs), "n_success": len(ok),
            "errors": [{"ref": r["ref_idx"], "model": r["model"], "error": (r.get("error") or "")[:200]}
                       for r in refs if not (r.get("success") and r.get("code"))],
            "tape_groups": {k[:120] + ("..." if len(k) > 120 else ""): v
                            for k, v in groups.items()},
            "n_groups": len(groups),
            "fills_per_group": [len(json.loads(k)) for k in groups],
            "assumption_topics": sorted({a.get("topic", "?") for r in refs
                                         for a in r.get("assumptions", [])}),
            "proposal": proposal,
        }
        print(f"task {tid:>3}: {proposal:<16} success={len(ok)}/{len(refs)} "
              f"groups={len(groups)} fills={summary[tid]['fills_per_group']} "
              f"assumptions={summary[tid]['assumption_topics']}")

    (common.RESULTS / "convergence_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    counts = defaultdict(int)
    for s in summary.values():
        counts[s["proposal"]] += 1
    print("\nproposals:", dict(counts))


if __name__ == "__main__":
    main()
