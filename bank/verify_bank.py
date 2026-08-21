"""Bank integrity verifier — the canonical, committed check (council R2:
sonnet-1 #2 showed the earlier claim was stated in terms of run NAMES, which
renames break; the chain that actually matters is about SOURCE and PARAMS).

For every job in the current (deduped) job list, assert ALL of:
  1. a manifest exists and is complete;
  2. sha256(LEAN's own code/main.py copy of the executed program)
     == manifest.source_sha            [the manifest describes the executed source]
  3. the NONCE the algorithm logged from inside the container
     == the _nonce embedded in that executed source
                                        [the log came from that source]
  4. manifest params (minus _nonce) == the job's params
                                        [it is THIS experiment]
Names are bookkeeping and may change across spec renames; 2+3+4 are what the
scientific claim rests on. Exits non-zero on any failure.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bank_runner import job_list, BT, sha, BANK_DIR  # noqa: E402


def verify(verbose=False):
    jobs = {j["name"]: j for j in job_list()}
    ok = 0
    fails = []
    for name, j in jobs.items():
        mp = BANK_DIR / f"{name}.json"
        if not mp.exists():
            fails.append((name, "no-manifest")); continue
        r = json.loads(mp.read_text(encoding="utf-8"))
        if not r.get("complete"):
            fails.append((name, f"incomplete:{r.get('status')}")); continue
        cm = BT / name / "code" / "main.py"
        if not cm.exists():
            fails.append((name, "no-executed-source-copy")); continue
        src = cm.read_text(encoding="utf-8")
        if sha(src) != r["source_sha"]:
            fails.append((name, "source-sha-mismatch")); continue
        m = re.search(r'"_nonce":\s*"([^"]+)"', src)
        if not m or r.get("logged_nonce") != m.group(1):
            fails.append((name, "nonce-mismatch")); continue
        params = {k: v for k, v in r["params"].items() if k != "_nonce"}
        if params != j["params"]:
            fails.append((name, "params-mismatch")); continue
        ok += 1
    print(f"BANK INTEGRITY: {ok}/{len(jobs)} verified "
          f"(source copy == manifest, in-container nonce == that source's nonce, params == job)")
    for f in fails[:20]:
        print("  FAIL", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(verify("-v" in sys.argv))
