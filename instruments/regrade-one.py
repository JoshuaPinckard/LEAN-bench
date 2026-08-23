"""Re-grade ONE draw from scratch, printing what it computes.

Usage: python regrade-one.py <gens-file> <prompt-id> <replicate-index>

Runs the real engine against the verified oracle bank, exactly as the study
does, and prints status/code. Nothing is written into the study's graded
files - the exec manifest goes to exec/OWNERCHECK_*.json so an owner check
can never be mistaken for study data."""
import json
import re
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "instruments"))
import grade  # noqa: E402
from bank_runner import load_bank  # noqa: E402

gens_file, prompt_id, idx = sys.argv[1], sys.argv[2], int(sys.argv[3])
grade.EXEC_DIR = R / "exec"

env = None
for line in open(gens_file, encoding="utf-8"):
    e = json.loads(line)
    pid = e.get("variant") or e.get("prompt_id")
    i = e.get("replicate") if "replicate" in e else e.get("i")
    if pid == prompt_id and i == idx:
        env = e
if env is None:
    sys.exit(f"draw not found: {prompt_id} #{idx} in {gens_file}")

print(f"draw: {prompt_id} #{idx}  model={env.get('model')} effort={env.get('effort')}")
print(f"status recorded at generation: {env.get('status')}")
if not env.get("program"):
    print("\nNo program in this draw - nothing to execute.")
    print("Read the model's text and judge whether it asked for missing information:")
    print("-" * 70)
    print((env.get("raw_text") or "(empty)")[:1200])
    sys.exit(0)

# ENGINE CONTENTION GUARD. The LEAN container is a single shared resource;
# when several graders run at once a perfectly good program can come back
# exit=1 (this is the documented contention mode from the study's own
# execution controls - two runs timed out under load and reproduced their
# registered tapes exactly when re-run idle). A hand-check must never be
# confused by that, so refuse to run while other graders hold the engine.
import subprocess as _sp
_busy = _sp.run(["powershell", "-NoProfile", "-Command",
                 "@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'bench-grade|lattice-arm-grade' }).Count"],
                capture_output=True, encoding="utf-8").stdout.strip()
try:
    _n = int(_busy)
except (TypeError, ValueError):
    _n = 0
if _n > 0:
    print(f"\nWAIT: {_n} grading job(s) are using the engine right now.")
    print("Re-grading during contention can report a false failure.")
    print("Run this check again when the study's graders are idle.")
    sys.exit(3)

store = grade.Bank(load_bank(current_only=True))
CODE_AS = {"T1v0": "BL-01c", "BL-01a": "BL-01a", "BL-01b": "BL-01b", "BL-01c": "BL-01c"}
lookup = CODE_AS.get(prompt_id) or grade.bank_for(prompt_id)[0]
safe = re.sub(r"[^\w.-]", "", f"{env.get('model')}_{env.get('effort')}_{prompt_id}_{idx}")
rec = grade.grade_program(store, lookup, env["program"], f"OWNERCHECK_{safe}", worker=8)
print("\n=== INDEPENDENT RE-GRADE ===")
print(f"status : {rec['status']}")
print(f"code   : {rec.get('code')}")
print(f"numeric: {(rec.get('numeric') or {}).get('value')}")
print(f"bank   : {lookup}")
print("\nCompare these to 4-WHAT-THE-PIPELINE-CLAIMED.json in the draw folder.")
