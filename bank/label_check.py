"""Ground-truth label check: does the real coder give each bank run the label
of the reading it was BUILT from?

Every bank run's correct answer is known by construction, so this needs no
models and no engine. Each run's own tape is pushed through the REAL coding
path (grade.code_generation) with an empty program text — no program-side
evidence, the conservative case — and the emitted code is compared against
the label of the run's own resolution.

Outcomes: CORRECT (coded as built) · AMBIGUOUS (refused: the tape genuinely
matches several readings and nothing resolves it — an honest, counted loss)
· WRONG (coded as a DIFFERENT reading — the outcome that corrupts results;
the pre-fix coder produced 241 of these, biased into the donor's readings).

The registered assertion is WRONG == 0. Exit 1 otherwise.

Usage: python label_check.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "bank")); sys.path.insert(0, str(R / "harness")); sys.path.insert(0, str(R / "codebook"))
from bank_runner import load_bank                       # noqa: E402
from bank_spec import BLANKS, CLASSES, class_name        # noqa: E402
import grade as G                                        # noqa: E402


def main():
    recs = load_bank(current_only=True)
    store = G.Bank(recs)
    per = defaultdict(lambda: {"n": 0, "correct": 0, "ambiguous": 0, "wrong": 0})
    wrong_rows = []
    for r in recs.values():
        if not r["complete"] or r["projections"] is None or r["bank"] not in CLASSES:
            continue
        rec = G.code_generation(store, r["bank"], "", r["tape"], "ok")
        got = rec.get("code")
        want = class_name(r["bank"], {r["resolution"]})
        s = per[r["bank"]]; s["n"] += 1
        if isinstance(got, str) and got.startswith("AMBIGUOUS"):
            s["ambiguous"] += 1
        elif got == want:
            s["correct"] += 1
        else:
            s["wrong"] += 1
            wrong_rows.append({"name": r["name"], "built": r["resolution"], "want": want, "got": got})
    tot = {k: sum(v[k] for v in per.values()) for k in ("n", "correct", "ambiguous", "wrong")}
    print(f"LABEL CHECK (real coder path): {tot['n']} class-coded runs — "
          f"correct {tot['correct']} ({tot['correct']/tot['n']:.1%}), "
          f"ambiguous {tot['ambiguous']} ({tot['ambiguous']/tot['n']:.1%}), "
          f"WRONG {tot['wrong']}")
    for b in sorted(per):
        v = per[b]
        print(f"  {b:8} correct {v['correct']:4}  ambiguous {v['ambiguous']:4}  wrong {v['wrong']:4}")
    if wrong_rows:
        print("WRONG ROWS (first 10):")
        for w in wrong_rows[:10]:
            print(f"  {w['name']}: built={w['built']} want={w['want']} got={w['got']}")
    (Path(__file__).resolve().parent / "label_check_report.json").write_text(
        json.dumps({"totals": tot, "per_bank": {k: dict(v) for k, v in per.items()},
                    "wrong_rows": wrong_rows[:100]}, indent=1), encoding="utf-8")
    return 1 if tot["wrong"] else 0


if __name__ == "__main__":
    sys.exit(main())
