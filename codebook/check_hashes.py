"""Governing-artifact hash check (council R2, opus-3 #3: 4 of 17 registered
hashes were stale at HEAD because artifacts were edited after the record was
written, and NO checker existed).

`python check_hashes.py`          -> verify; exit 1 on any mismatch
`python check_hashes.py --refresh`-> rewrite the record (allowed ONLY pre-lock;
                                     it stamps the git rev and the date)

REGISTERED RULE: the hash record is refreshed as the LAST step before any
quota is spent, and verified again immediately before the probes and before
signature. A mismatch after lock is a dated amendment, never a silent
refresh.
"""
import hashlib
import subprocess
import sys
from datetime import date
from pathlib import Path

R = Path(__file__).resolve().parent.parent
REC = R / "codebook" / "CODEBOOK-HASHES.txt"

FILES = [
    "codebook/CODEBOOK-v2.md", "codebook/dof_extract.py", "codebook/validate_extractor.py",
    "bank/bank_spec.py", "bank/t1_ref_template.py", "bank/bank_runner.py", "bank/verify_bank.py",
    "harness/gen_drivers.js", "harness/run_probe.js", "harness/grade.py",
    "analysis/confirmatory.py", "analysis/probe_decide.py",
    "rung2/gen_variants_v5.py", "rung2/variants-v5.json",
    "probes/PX-01.txt", "probes/PX-02.txt", "probes/PROBES-MANIFEST.json",
]


def sha(p):
    return hashlib.sha256((R / p).read_bytes()).hexdigest()


def refresh():
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(R),
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        rev = "unknown"
    lines = [
        f"# GOVERNING-ARTIFACT HASHES — refreshed {date.today().isoformat()} at git {rev}",
        "# Every file that decides a code, a category, a prompt, or a statistic.",
        "# Verified by check_hashes.py; refreshed ONLY pre-lock, and re-verified",
        "# immediately before the probes and before signature (PIN §6 / §8.2).",
    ]
    lines += [f"{sha(f)}  {f}" for f in FILES]
    REC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"refreshed {len(FILES)} hashes at git {rev}")
    return 0


def verify():
    if not REC.exists():
        print("NO HASH RECORD"); return 1
    recorded = {}
    for line in REC.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        h, f = line.split(None, 1)
        recorded[f.strip()] = h
    bad, missing = [], []
    for f in FILES:
        if f not in recorded:
            missing.append(f); continue
        if sha(f) != recorded[f]:
            bad.append(f)
    extra = [f for f in recorded if f not in FILES]
    print(f"HASH CHECK: {len(FILES) - len(bad) - len(missing)}/{len(FILES)} match")
    for f in bad:
        print("  STALE  ", f)
    for f in missing:
        print("  MISSING", f)
    for f in extra:
        print("  EXTRA  ", f)
    return 1 if (bad or missing) else 0


if __name__ == "__main__":
    sys.exit(refresh() if "--refresh" in sys.argv else verify())
