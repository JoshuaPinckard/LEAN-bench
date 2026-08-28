"""Cell-by-cell completion status for the options arm (O1) draw lanes.

A lane's ROW TOTAL is not evidence that the lane is finished: a total can look
healthy while individual cells sit short of target. This reports every cell
against its target and refuses to call a lane complete unless every cell meets
it. It also counts draws that produced no program, since those do not count as
observations and are what a resume must refill.

Targets follow the arm design as the completed cells actually ran it: eligible
voids (O1e1..O1e8) n=60 per condition in the harness lanes and n=30 bare,
anchor/control prompts n=20, donor and pins n=10.

Read-only. Run: python arm-o1-status.py [batches_dir ...]
"""
import collections
import glob
import io
import json
import os
import sys

ROOT = r"C:\Users\joshp\Desktop\LEAN-Bench\batches"
# ALL dated folders + h5, always. A single-folder default caused a false
# "core lanes never started" report on 2026-08-28: lanes that ran on earlier
# dates were invisible, and generate.js folders every lane by its UTC start
# date, so single-folder scans are structurally wrong for multi-day lanes.
import glob as _glob
DIRS = sys.argv[1:] or sorted(
    d for d in _glob.glob(os.path.join(ROOT, "*"))
    if os.path.isdir(d) and (os.path.basename(d).startswith("20")
                             or os.path.basename(d) == "h5"))

ELIGIBLE = {f"O1e{i}" for i in range(1, 9)}
ANCHORS = {"O1a1", "O1a2", "O1c1"}


def target(prompt_id, surface):
    # REGISTERED targets (arm-options/MODELS.md): eligible 30 per condition,
    # anchors 20, donor/pins 10 - for every lane. luna_medium drew to 60 per
    # eligible cell under an earlier wrong target; the overdraw is kept as
    # extra data, but completion is judged against the registration.
    if surface == "bare":
        return 30 if prompt_id in ELIGIBLE else 10
    if prompt_id in ELIGIBLE:
        return 30
    if prompt_id in ANCHORS:
        return 20
    return 10


def parse(name):
    base = os.path.basename(name)[:-len(".jsonl")]
    cond = "noask" if base.endswith("_noask") else "base"
    if cond == "noask":
        base = base[:-len("_noask")]
    m = base.split("_O1")
    if len(m) < 2:
        return None
    pid = "O1" + m[1]
    lane = m[0]
    surface = "bare" if lane.startswith("bare_") else "harness"
    return lane, pid, cond, surface


cells = {}
for d in DIRS:
    for f in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
        if "quarantine" in f:     # quarantined rows are not cells
            continue
        info = parse(f)
        if not info:
            continue
        lane, pid, cond, surface = info
        rows = [json.loads(l) for l in io.open(f, encoding="utf-8") if l.strip()]
        usable = sum(1 for r in rows if r.get("status") == "program"
                     or r.get("status") == "coded" or r.get("program"))
        cells[(lane, pid, cond)] = {
            "rows": len(rows), "usable": usable,
            "target": target(pid, surface), "path": f,
        }

by_lane = collections.defaultdict(list)
for (lane, pid, cond), v in cells.items():
    by_lane[lane].append((pid, cond, v))

overall_ok = True
for lane in sorted(by_lane):
    items = sorted(by_lane[lane])
    short = [(p, c, v) for p, c, v in items if v["usable"] < v["target"]]
    tot_rows = sum(v["rows"] for _, _, v in items)
    tot_use = sum(v["usable"] for _, _, v in items)
    tot_tgt = sum(v["target"] for _, _, v in items)
    verdict = "COMPLETE" if not short else f"INCOMPLETE ({len(short)} cells short)"
    if short:
        overall_ok = False
    print(f"\n== {lane}: {len(items)} cells | {tot_use}/{tot_tgt} usable draws "
          f"({tot_rows} rows) -> {verdict}")
    for p, c, v in short:
        print(f"     short: {p:6s} {c:5s} {v['usable']:>3}/{v['target']}"
              f"   ({v['rows']} rows recorded)")

print("\nALL LANES COMPLETE" if overall_ok else
      "\nNOT COMPLETE - the cells above still need draws")
