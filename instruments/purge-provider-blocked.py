"""Quarantine rows that banked a PROVIDER message as a model observation.

A quota/sign-in/rate-limit notice arrives as ordinary assistant text with no
program, so the old classifier stored it as 'no-program' - which grading reads
as a refusal or a clarifying question. Measured 2026-08-27: 59 of 62
claude-sonnet-5 draws on the options arm were the single string "You've hit
your session limit", banked as observations.

Rows are MOVED to a quarantine file beside the lane, never deleted, and the
lane file is rewritten without them so a resume redraws those indices.

Run: python purge-provider-blocked.py <dir> [--apply]
"""
import argparse
import glob
import io
import json
import os
import re

PROVIDER_BLOCKED = re.compile(
    r"limits?|quota|resets?|Not signed in|please (?:sign|log) ?in|"
    r"credit balance|insufficient_quota|Overloaded|too many requests|429",
    re.I)

ap = argparse.ArgumentParser()
ap.add_argument("directory")
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

total_bad = 0
for f in sorted(glob.glob(os.path.join(args.directory, "*.jsonl"))):
    if ".quarantine" in f:
        continue
    rows = [json.loads(l) for l in io.open(f, encoding="utf-8") if l.strip()]
    bad, keep = [], []
    for r in rows:
        txt = r.get("raw_text") or ""
        # Only short, program-free bodies: a real answer that merely mentions
        # a rate limit in passing must not be discarded.
        if (not r.get("program")) and len(txt) < 600 and PROVIDER_BLOCKED.search(txt):
            bad.append(r)
        else:
            keep.append(r)
    if not bad:
        continue
    total_bad += len(bad)
    print(f"{os.path.basename(f)}: {len(bad)} provider-blocked of {len(rows)}")
    if args.apply:
        q = f.replace(".jsonl", ".quarantine-provider-blocked.jsonl")
        with io.open(q, "a", encoding="utf-8") as fh:
            for r in bad:
                r["quarantined_reason"] = "provider message banked as observation"
                fh.write(json.dumps(r) + "\n")
        with io.open(f, "w", encoding="utf-8") as fh:
            for r in keep:
                fh.write(json.dumps(r) + "\n")

print(f"\ntotal provider-blocked rows: {total_bad}")
print("APPLIED - rows moved to .quarantine-provider-blocked.jsonl beside each lane"
      if args.apply else "DRY RUN - re-run with --apply")
