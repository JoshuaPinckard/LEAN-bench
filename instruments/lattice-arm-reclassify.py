"""Reclassify gen:no-program rows in graded lanes with the widened ASK_RE
(statement-form asks). Rewrites graded/*.jsonl in place; idempotent."""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(r"C:\Users\joshp\Desktop\LEAN-Bench") / "arm"
ASK_RE = re.compile(
    r"(?i)what .{0,50}(period|type)|please (provide|specify)|should .{0,40}use\?"
    r"|i need (the|a|an)?\s?.{0,60}(period|type)"
    r"|is(n.t| not) (specified|defined)|unspecified|is required but not")

for gf in sorted((R / "graded").glob("*.jsonl")):
    lane = gf.stem
    envs = {}
    src = R / "gens" / f"{lane}.jsonl"
    if src.exists():
        for line in src.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                envs[(e["variant"], e["replicate"])] = e
    out, changed = [], 0
    for line in gf.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["status"] == "gen:no-program":
            e = envs.get((r["variant"], r["i"]))
            txt = ((e or {}).get("raw_text") or "").strip()
            if txt and ("?" in txt[-3:] or ASK_RE.search(txt)):
                r["status"] = "asks-clarifying"
                r["ask_text"] = txt[:140]
                changed += 1
        out.append(json.dumps(r))
    gf.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{lane}: reclassified {changed}")
