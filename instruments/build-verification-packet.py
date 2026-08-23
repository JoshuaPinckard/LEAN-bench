"""Build the owner's hand-verification packet.

Draws a seeded random sample from EVERY graded row in the study and writes,
for each draw, a self-contained folder the owner can check by hand:
  - the exact prompt the model saw (from the frozen set, hash shown)
  - the model's raw response
  - the program that was extracted (if any)
  - what the pipeline CLAIMED (status, code, numeric, bank)
  - a one-line command that re-grades that single draw from scratch

Plus a classifier packet: 20 rows the pipeline called asks-clarifying and
20 it did not, with the text shown and the decision blanked, so the owner
can mark agree/disagree without seeing the answer first.

Usage: python build-verification-packet.py [seed]
"""
import json
import glob
import random
import re
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20260823
OUT = R / "verification-packet"
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------- gather
rows = []
for f in sorted(glob.glob(str(R / "arm/graded/*.jsonl")) + glob.glob(str(R / "arm/graded_noask/*.jsonl"))):
    lane = Path(f).stem
    noask = "graded_noask" in f
    for line in open(f, encoding="utf-8"):
        r = json.loads(line)
        r["_source"] = "arm"
        r["_lane"] = lane
        r["_noask"] = noask
        r["_gens"] = str(R / ("arm/gens_noask" if noask else "arm/gens") / f"{lane}.jsonl")
        r["_prompt_id"] = r.get("variant")
        r["_i"] = r.get("i")
        rows.append(r)
for f in sorted(glob.glob(str(R / "batches/*/graded/*.jsonl"))):
    stem = Path(f).stem
    for line in open(f, encoding="utf-8"):
        r = json.loads(line)
        r["_source"] = "benchmark"
        r["_lane"] = stem
        r["_noask"] = stem.endswith("_noask")
        r["_gens"] = str(Path(f).parent.parent / f"{stem}.jsonl")
        r["_prompt_id"] = r.get("prompt_id")
        r["_i"] = r.get("i")
        rows.append(r)

_V = json.loads((R / "prompts" / "variants-v5.json").read_text(encoding="utf-8"))
_BY = {v["id"]: v["prompt"] for v in _V["variants"]}
_BY["T1v0"] = (R / "prompts" / "T1v0.txt").read_text(encoding="utf-8")
NOASK_SUFFIX = "You will NOT return anything except for the program."


def prompt_text(pid, noask):
    t = _BY.get(pid, f"(prompt id {pid} not found)")
    if noask:
        t = t.rstrip("\n") + "\n\n" + NOASK_SUFFIX + "\n"
    return t


rnd = random.Random(SEED)

# stratify: 12 coded (the load-bearing ones), 4 asks, 4 other statuses
coded = [r for r in rows if r["status"] == "coded"]
asks = [r for r in rows if r["status"] == "asks-clarifying"]
other = [r for r in rows if r["status"] not in ("coded", "asks-clarifying")]
sample = rnd.sample(coded, 12) + rnd.sample(asks, 4) + rnd.sample(other, 4)
rnd.shuffle(sample)


def raw_for(r):
    """The generation envelope behind a graded row.

    A (prompt, replicate) slot can appear MORE than once: an unfinished
    draw (harness-error / empty) stays on disk under the fairness rule and
    the retry is appended after it. The graded row always refers to the
    FINISHED draw, so prefer the last non-unfinished match - taking the
    first one yields an empty response (owner caught this as 'item 32 is
    missing', 2026-08-23)."""
    best = {}
    for line in open(r["_gens"], encoding="utf-8"):
        e = json.loads(line)
        pid = e.get("variant") or e.get("prompt_id")
        idx = e.get("replicate") if "replicate" in e else e.get("i")
        if pid != r["_prompt_id"] or idx != r["_i"]:
            continue
        unfinished = e.get("status") == "harness-error" or (
            e.get("status") == "no-program" and not (e.get("raw_text") or "").strip())
        if not unfinished:
            best = e                      # a finished draw always wins
        elif not best:
            best = e                      # keep something if that is all there is
    return best


index = []
for n, r in enumerate(sample, 1):
    d = OUT / f"draw{n:02d}"
    d.mkdir(exist_ok=True)
    env = raw_for(r)
    (d / "1-PROMPT.txt").write_text(
        f"prompt id: {r['_prompt_id']}\ncondition: {'no-ask instruction appended' if r['_noask'] else 'plain (base)'}\n"
        f"prompt sha256: {env.get('prompt_sha256')}\nmodel: {r.get('model')}   effort: {r.get('effort')}\n"
        f"{'-' * 70}\n" + prompt_text(r["_prompt_id"], r["_noask"]),
        encoding="utf-8")
    (d / "2-MODEL-RESPONSE.txt").write_text(env.get("raw_text") or "(empty)", encoding="utf-8")
    (d / "3-EXTRACTED-PROGRAM.py").write_text(env.get("program") or "# (no program extracted)", encoding="utf-8")
    claim = {k: r.get(k) for k in ("status", "code", "numeric", "bank", "flags", "exec_status", "ask_text")}
    (d / "4-WHAT-THE-PIPELINE-CLAIMED.json").write_text(json.dumps(claim, indent=1), encoding="utf-8")
    (d / "5-CHECK-IT-YOURSELF.txt").write_text(
        "To re-grade this ONE draw from scratch (runs the real engine, ~1-2 min):\n\n"
        f"  cd {R}\n"
        f"  python instruments/regrade-one.py \"{r['_gens']}\" {r['_prompt_id']} {r['_i']}\n\n"
        "It prints the status/code it computes. Compare to file 4.\n"
        "For asks-clarifying rows there is no program to run - read file 2 and\n"
        "judge whether the model asked a question or just refused/failed.\n", encoding="utf-8")
    index.append({"draw": n, "source": r["_source"], "lane": r["_lane"], "prompt_id": r["_prompt_id"],
                  "i": r["_i"], "claimed_status": r["status"], "claimed_code": r.get("code")})

(OUT / "INDEX.json").write_text(json.dumps(index, indent=1), encoding="utf-8")

# ---------------------------------------------------------------- classifier packet
cl = OUT / "classifier-check"
cl.mkdir(exist_ok=True)
# The classifier ONLY decides among draws where NO program was extracted:
# it reads the model's text and calls it an ask or not. Rows like
# `non-runnable` mean a program WAS written and then failed to execute -
# no classifier judgment was involved, so including them would pad the
# packet with trivial items (found 2026-08-23 when the owner flagged that
# full programs were showing up in the ask/not-ask check).
ask_sample = rnd.sample(asks, 20)
noask_pool = [r for r in rows if r["status"] in ("no-program", "gen:no-program")]
non_sample = noask_pool[:]           # small population - include every one
items = [{"row": r, "truth": "ASK"} for r in ask_sample] + [{"row": r, "truth": "NOT-ASK"} for r in non_sample]
rnd.shuffle(items)
def looks_truncated(t):
    """Cut-off code: reads as Python, not as prose to a human.

    Heuristic on the WHOLE response: code-ish lines (indentation, dotted
    calls, assignments, keywords) dominate. An ask is a sentence; a
    truncated program is not."""
    lines = [x for x in t.splitlines() if x.strip()]
    if not lines:
        return False
    codeish = sum(1 for x in lines if re.search(r"^\s{2,}|self\.|=\s|\(\)|:\s*$|def |import |return |if |for ", x))
    return codeish / len(lines) > 0.5


lines = ["# Classifier check - is this the model ASKING for missing information?",
         "#",
         "# Every item is a draw where the model produced NO program - only text.",
         "# That is the only case where the classifier makes a call. (A draw whose",
         "# program ran and failed involves no classifier decision, so it is not",
         "# here - that was a packet bug the owner caught on 2026-08-23.)",
         "#",
         "# Items marked [TRUNCATED CODE] are outputs that were cut off mid-program;",
         "# they are mechanical, skim them. The unmarked ones are the real judgment",
         "# calls - spend your attention there.",
         "#",
         "# Write ASK or NOT-ASK on each answer line. The pipeline's own decision",
         "# is in ANSWERS.json - don't open it until you're done.", ""]
answers = []
for n, it in enumerate(items, 1):
    r = it["row"]
    env = raw_for(r)
    raw = env.get("raw_text") or ""
    tag = " [TRUNCATED CODE]" if looks_truncated(raw) else ""
    txt = raw[:900].replace("\n", " ")
    lines += [f"## Item {n}{tag}  (prompt {r['_prompt_id']}, {r.get('model')}/{r.get('effort')})",
              f"model said: {txt}", "your call: ______", ""]
    answers.append({"item": n, "pipeline_said": it["truth"], "status": r["status"], "truncated_code": bool(tag)})
(cl / "QUESTIONS.md").write_text("\n".join(lines), encoding="utf-8")
(cl / "ANSWERS.json").write_text(json.dumps(answers, indent=1), encoding="utf-8")

print(f"packet written: {OUT}")
print(f"  {len(sample)} draws (12 coded / 4 asks / 4 other), {len(items)} classifier items")
