"""P2 - the pre-registered judge-leniency experiment (paper Section 7, P2).

Pre-registration (main.tex, frozen before this script existed): "The 12
audited programs will be rejudged under (a) the released prompt with the
leniency instructions removed and (b) a strict-wording variant, holding
everything else fixed. Hypothesis: approvals of behaviorally incorrect
programs persist above one half, because the judge reads code and description
but never execution; refuted if strict wording alone brings judge decisions
into majority agreement with the answer key."

Design, mirroring the proven judge_stability.py exactly where possible:
- the SAME 12 candidate programs (tasks 59/249/388 x {haiku,sonnet} x 2)
- 3 prompt variants x 3 repetitions each = 108 judge calls
    original  the released template verbatim (within-experiment control;
              stability already showed 0 flips in 30 calls on this prompt)
    stripped  the released template minus its three leniency devices, and
              NOTHING else changed
    strict    the same rubric reworded to penalize material deviation
- same judge family and invocation (judge_repl.judge's path: cli.call_claude,
  model "sonnet"), same parser (judge_repl.parse_alignment)
- answer key: compare.primary_match from each frozen gens/ record
- majority verdict per (program, variant) across the 3 reps

The three leniency devices, removed by ASSERTED byte-exact edits (an edit that
does not land exactly once aborts the run - the silent str.replace no-op rule):
  1. line-17 relevance clause: "The code must explicitly ignore ALL conditions
     of the assignment to receive 0."
  2. the 0-rating definition: "if the code COMPLETELY DOES NOT COMPLY (ignores
     the main idea)"
  3. the IMPORTANT paragraph: "Be LENIENT with simplifications ..."

Resume-safe: each call's transcript is written before its row; rows append to
results/judge_leniency.rows.jsonl and completed (cand, variant, rep) triples
are skipped on rerun. Run:  python driver/judge_leniency.py
"""
import concurrent.futures
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import judge_repl  # noqa: E402
from cli import call_claude, SessionLimitError  # noqa: E402

RESULTS = common.RESULTS
OUT_DIR = RESULTS / "judge_leniency"
ROWS = RESULTS / "judge_leniency.rows.jsonl"
TEMPLATE = judge_repl.TEMPLATE
DETERMINATE = {59, 249, 388}
REPS = 3


def edit(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"TEMPLATE EDIT {label} matched {n} times, need exactly 1")
    return text.replace(old, new)


def build_stripped():
    t = TEMPLATE
    t = edit(t,
             " The code must explicitly ignore ALL conditions of the assignment to receive 0.",
             "", "relevance-clause")
    t = edit(t,
             "- X = 0 if the code COMPLETELY DOES NOT COMPLY (ignores the main idea)",
             "- X = 0 if the code does not implement the assignment",
             "zero-definition")
    t = edit(t,
             "IMPORTANT: Be LENIENT with simplifications. Penalize ONLY if the code clearly ignores the main task or uses completely different indicators/logic WITHOUT reason. If the assignment is technically impossible to implement exactly in Backtrader — accept reasonable simplifications.\n\n",
             "", "lenient-paragraph")
    return t


def build_strict():
    t = build_stripped()
    t = edit(t,
             "- X = 1 if the code implements the MAIN LOGIC of the assignment (even with simplifications)",
             "- X = 1 only if the code implements the assignment as specified, "
             "including its stated conditions and parameters",
             "one-definition")
    t = edit(t,
             'You MUST end your response with the line "Rating: [[X]]".',
             "Be STRICT: penalize any material deviation from the stated "
             "conditions, parameters, or trading logic of the assignment.\n\n"
             'You MUST end your response with the line "Rating: [[X]]".',
             "strict-instruction")
    return t


VARIANTS = {"original": TEMPLATE, "stripped": build_stripped(),
            "strict": build_strict()}


def load_candidates():
    cands = []
    for p in sorted(glob.glob(str(RESULTS / "gens" / "task*_*.json"))):
        if ".judge" in p:
            continue
        tid = int(re.match(r"task(\d+)_", os.path.basename(p)).group(1))
        if tid not in DETERMINATE:
            continue
        cands.append(json.loads(Path(p).read_text(encoding="utf-8")))
    if len(cands) != 12:
        raise SystemExit(f"expected the 12 audited programs, found {len(cands)}")
    return cands


def done_set():
    seen = set()
    if ROWS.exists():
        for l in ROWS.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                seen.add((r["task_id"], r["model"], r["sample_idx"],
                          r["variant"], r["rep"]))
    return seen


def judge_with(template, task_description, generated_code, out_path):
    prompt = (template
              .replace("{task_description}", task_description)
              .replace("{generated_code}", generated_code))
    text = call_claude(prompt, judge_repl.JUDGE_MODEL, out_path, min_bytes=100)
    aligned, score, parse_mode = judge_repl.parse_alignment(text)
    return {"judge_aligned": aligned, "judge_score": score,
            "parse_mode": parse_mode}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cands = load_candidates()
    tasks = common.load_tasks()
    seen = done_set()
    jobs = []
    for rec in cands:
        for variant in VARIANTS:
            for rep in range(REPS):
                key = (rec["task_id"], rec["model"], rec["sample_idx"], variant, rep)
                if key not in seen:
                    jobs.append((rec, variant, rep))
    print(f"{len(jobs)} judge calls to run ({len(seen)} already done)")

    def do_one(rec, variant, rep):
        tid, model, sidx = rec["task_id"], rec["model"], rec["sample_idx"]
        out = OUT_DIR / f"task{tid}_{model}_{sidx}_{variant}_rep{rep}.txt"
        j = judge_with(VARIANTS[variant], tasks[tid]["reformulated_task"],
                       rec["cleaned_code"], out)
        return {"task_id": tid, "model": model, "sample_idx": sidx,
                "variant": variant, "rep": rep,
                "behaviorally_correct": bool(rec["compare"]["primary_match"]),
                "orig_judge_aligned": rec["judge"]["judge_aligned"],
                "rep_aligned": j["judge_aligned"], "parse_mode": j["parse_mode"]}

    stop = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(do_one, *j): j for j in jobs}
        for f in concurrent.futures.as_completed(futs):
            if stop:
                continue
            try:
                r = f.result()
            except SessionLimitError as e:
                print(f"SESSION LIMIT: {e} - stopping; rerun to resume", flush=True)
                stop = True
                continue
            except Exception as e:
                print(f"call failed: {e}", flush=True)
                continue
            with open(ROWS, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(r) + "\n")
            print(f"task{r['task_id']} {r['model']}#{r['sample_idx']} "
                  f"{r['variant']} rep{r['rep']}: aligned={r['rep_aligned']} "
                  f"(key_correct={r['behaviorally_correct']})", flush=True)

    # ---- aggregate whatever is on disk (partial runs aggregate too)
    rows = [json.loads(l) for l in ROWS.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    agg = {}
    for variant in VARIANTS:
        vr = [r for r in rows if r["variant"] == variant]
        by = {}
        for r in vr:
            by.setdefault((r["task_id"], r["model"], r["sample_idx"]), []).append(r)
        conf = {"approved_correct": 0, "approved_incorrect": 0,
                "rejected_correct": 0, "rejected_incorrect": 0}
        complete = 0
        for key, reps in by.items():
            if len(reps) < REPS:
                continue
            complete += 1
            approved = sum(r["rep_aligned"] for r in reps) >= 2   # majority of 3
            correct = reps[0]["behaviorally_correct"]
            if approved and correct: conf["approved_correct"] += 1
            elif approved: conf["approved_incorrect"] += 1
            elif correct: conf["rejected_correct"] += 1
            else: conf["rejected_incorrect"] += 1
        correct_decisions = conf["approved_correct"] + conf["rejected_incorrect"]
        agg[variant] = {"programs_complete": complete, "confusion": conf,
                        "correct_decisions": correct_decisions,
                        "calls": len(vr)}
        print(f"{variant:9s}: {complete:2d}/12 programs | confusion {conf} "
              f"| correct decisions {correct_decisions}/{complete}")
    (RESULTS / "judge_leniency.json").write_text(json.dumps({
        "preregistration": "main.tex P2: hypothesis - incorrect approvals persist "
                           "above one half without the leniency instructions; "
                           "refuted if strict wording alone reaches majority "
                           "agreement with the answer key",
        "reps_per_program": REPS, "majority_rule": "2 of 3",
        "variants": {k: {"sha_note": "derived from released template by asserted "
                                     "edits; see build_stripped/build_strict"}
                     for k in VARIANTS},
        "aggregate": agg, "n_rows": len(rows),
    }, indent=2), encoding="utf-8")
    print("written: results/judge_leniency.json")


if __name__ == "__main__":
    main()
