"""Failure map for the O1 arm lanes: which cells fail, how, and how fast.

Distinguishes the failure modes that need different responses:
  program        - a usable draw
  no-program     - the model answered but committed no code (may be an ask, a
                   refusal, or a provider message such as a usage limit)
  harness-error  - the call itself did not return usable output

Wall time separates causes that share a status: a harness-error at ~3 s is the
CLI refusing immediately (auth, quota, bad invocation), while one at ~1,200 s is
the 20-minute timeout being hit.

Read-only. Run: python arm-o1-failures.py
"""
import collections
import glob
import io
import json
import os

D = r"C:\Users\joshp\Desktop\LEAN-Bench\batches\2026-08-27"

print("%-40s %5s %6s %5s  %-10s %s" %
      ("cell", "prog", "nopro", "herr", "med_err_ms", "sample message"))
for f in sorted(glob.glob(os.path.join(D, "*.jsonl"))):
    if "quarantine" in f:
        continue
    rows = [json.loads(l) for l in io.open(f, encoding="utf-8") if l.strip()]
    if not rows:
        continue
    c = collections.Counter(r.get("status") for r in rows)
    errs = sorted(r.get("wall_ms", 0) for r in rows
                  if r.get("status") == "harness-error")
    med = errs[len(errs) // 2] if errs else 0
    msg = ""
    for r in rows:
        if r.get("status") in ("no-program", "harness-error"):
            t = (r.get("raw_text") or "").strip().replace("\n", " ")
            if t:
                msg = t[:60]
                break
    b = os.path.basename(f)[:-6]
    b = b.replace("codex_gpt-5.6-luna_medium_", "luna:") \
         .replace("claude_claude-sonnet-5_max_", "sonnet:")
    print("%-40s %5d %6d %5d  %-10d %s" %
          (b, c.get("program", 0), c.get("no-program", 0),
           c.get("harness-error", 0), med, msg))
