"""Phase 4: compute the two headline numbers with Wilson 95% CIs (PLAN.md D9).

metric 1 from results/metric1.json (adjudicated classifications)
metric 2 from results/gens/*.json (judge verdicts + tape comparisons)
Writes results/metric2.json and prints both metrics with exact counts.
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402


def wilson(k: int, n: int, z: float = 1.959964):
    """Wilson score interval for k successes of n."""
    if n == 0:
        return None, None, None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def fmt(k, n):
    p, lo, hi = wilson(k, n)
    if p is None:
        return f"{k}/{n} (n=0)"
    return f"{k}/{n} = {p:.1%} [95% CI {lo:.1%}–{hi:.1%}]"


def main():
    m1 = json.loads((common.RESULTS / "metric1.json").read_text(encoding="utf-8"))
    n_det = len(m1["determinate_ids"])
    print("METRIC 1 — determinacy rate:", fmt(n_det, m1["n_tasks"]))
    print("  classes:", m1["class_counts"])

    tasks = common.load_tasks()
    gens = sorted((common.RESULTS / "gens").glob("task*_*.json"))
    gens = [json.loads(p.read_text(encoding="utf-8")) for p in gens
            if not p.name.endswith(".judge.json")]

    rows = []
    for g in gens:
        if g.get("judge") is None:
            continue  # failed gates, never judged (their control flow)
        rows.append({
            "task_id": g["task_id"], "model": g["model"],
            "difficulty": tasks[g["task_id"]]["difficulty"],
            "judge_pass": bool(g["judge"]["judge_aligned"]),
            "judge_mode": g["judge"]["judge_mode"],
            "tape_match": bool(g["compare"]["primary_match"]),
            "secondary_match": bool(g["compare"]["secondary_match"]),
        })

    judged = len(rows)
    passes = [r for r in rows if r["judge_pass"]]
    false_passes = [r for r in passes if not r["tape_match"]]
    fails = [r for r in rows if not r["judge_pass"]]
    false_fails = [r for r in fails if r["tape_match"]]

    print(f"\ncandidates judged (gate survivors): {judged} of {len(gens)} generated")
    print("METRIC 2 — judge false-pass rate:", fmt(len(false_passes), len(passes)))
    print("  secondary (ts,side,size) false-pass:",
          fmt(len([r for r in passes if not r['secondary_match']]), len(passes)))
    print("  judge false-fail rate:", fmt(len(false_fails), len(fails)))

    by_diff = defaultdict(lambda: [0, 0])
    for r in passes:
        by_diff[r["difficulty"]][1] += 1
        if not r["tape_match"]:
            by_diff[r["difficulty"]][0] += 1
    for d, (k, n) in sorted(by_diff.items()):
        print(f"  false-pass [{d}]:", fmt(k, n))

    out = {"judged": judged, "generated": len(gens),
           "judge_passes": len(passes), "false_passes": len(false_passes),
           "judge_fails": len(fails), "false_fails": len(false_fails),
           "rows": rows}
    (common.RESULTS / "metric2.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\nwrote results/metric2.json")


if __name__ == "__main__":
    main()
