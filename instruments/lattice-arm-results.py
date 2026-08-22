"""Compute the professor's-arm results: per model x effort lattice statistics
and the effort curves. Writes arm/RESULTS.json and prints the table."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(r"C:\Users\joshp\Desktop\LEAN-Bench") / "arm"
PAIR = re.compile(r"^(SMA|EMA|WMA)(\d+)$")
EFFORT_ORDER = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4, "default": 5}

def V(codes):
    return None if len(codes) <= 1 else round((len(set(codes)) - 1) / (len(codes) - 1), 3)

def dist(codes):
    n = len(codes); c = Counter(codes)
    return {k: v / n for k, v in c.items()} if n else {}

def tv(p, q):
    return round(0.5 * sum(abs(p.get(k, 0) - q.get(k, 0)) for k in set(p) | set(q)), 3) if p and q else None

results = {}
for gf in sorted(R.glob("graded/*.jsonl")):
    m = re.match(r"(.+)_(low|medium|high|xhigh|max|default)$", gf.stem)
    model, effort = m.group(1), m.group(2)
    rows = [json.loads(l) for l in gf.read_text(encoding="utf-8").splitlines() if l.strip()]
    cells = {}
    for v in ("T1v0", "BL-01a", "BL-01b", "BL-01c"):
        cell = [r for r in rows if r["variant"] == v]
        coded = [r["code"] for r in cell if r["status"] == "coded" and r.get("code") not in (None, "DRIFT", "AMBIGUOUS-AT-TUPLE", "AMBIGUOUS-ACROSS-TUPLES", "other")]
        cells[v] = {"n": len(cell), "statuses": dict(Counter(r["status"] for r in cell)),
                    "codes": dict(Counter(r.get("code") for r in cell if r["status"] == "coded")),
                    "named_coded": coded, "V": V(coded),
                    "ask_rate": round(sum(1 for r in cell if r["status"] == "asks-clarifying") / len(cell), 2) if cell else None,
                    "drift": sum(1 for r in cell if r.get("code") == "DRIFT")}
    jc = [(g.group(1), "p" + g.group(2)) for c in cells["BL-01c"]["named_coded"] if (g := PAIR.match(c))]
    j0 = [(g.group(1), "p" + g.group(2)) for c in cells["T1v0"]["named_coded"] if (g := PAIR.match(c))]
    ja, jb = cells["BL-01a"]["named_coded"], cells["BL-01b"]["named_coded"]
    entry = {
        "n_total": len(rows), "partial": len(rows) < 40, "cells": cells,
        "compliance_T1v0": (round(sum(1 for t, p in j0 if t == "SMA" and p == "p100") / len(j0), 2) if j0 else None),
        "descent_tv_type": tv(dist([t for t, _ in jc]), dist(ja)),
        "descent_tv_period": tv(dist([p for _, p in jc]), dist(jb)),
        "V_a": cells["BL-01a"]["V"], "V_b": cells["BL-01b"]["V"], "V_c": cells["BL-01c"]["V"],
        "monotone_C2": (cells["BL-01c"]["V"] >= max(cells["BL-01a"]["V"], cells["BL-01b"]["V"])
                        if None not in (cells["BL-01a"]["V"], cells["BL-01b"]["V"], cells["BL-01c"]["V"]) else None),
        "ask_lattice": {v: cells[v]["ask_rate"] for v in ("T1v0", "BL-01a", "BL-01b", "BL-01c")},
    }
    results.setdefault(model, {})[effort] = entry

(R / "RESULTS.json").write_text(json.dumps(results, indent=1), encoding="utf-8")

hdr = f'{"model/effort":22s} {"n":>3s} {"cmpl":>5s} {"askB":>5s} {"askC":>5s} {"V_b":>5s} {"V_c":>5s} {"TVper":>6s} {"drift":>5s} {"period codes":24s} {"union codes"}'
print(hdr); print("-" * len(hdr))
for model in sorted(results):
    for eff in sorted(results[model], key=lambda e: EFFORT_ORDER[e]):
        r = results[model][eff]
        c = r["cells"]
        pc = ",".join(f"{k}x{v}" for k, v in c["BL-01b"]["codes"].items()) or "-"
        uc = ",".join(f"{k}x{v}" for k, v in c["BL-01c"]["codes"].items()) or "-"
        drift = sum(c[v]["drift"] for v in c)
        star = "*" if r["partial"] else " "
        print(f'{model + "/" + eff + star:22s} {r["n_total"]:3d} {str(r["compliance_T1v0"]):>5s} {str(r["ask_lattice"]["BL-01b"]):>5s} {str(r["ask_lattice"]["BL-01c"]):>5s} {str(r["V_b"]):>5s} {str(r["V_c"]):>5s} {str(r["descent_tv_period"]):>6s} {drift:5d} {pc:24s} {uc}')
print("* = partial lane (generation stopped at quota)")
