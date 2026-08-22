"""Grade one lattice-arm lane (model x effort) through the certified chain.
Usage: python lattice-arm-grade.py <model> <effort>
Engine manifests go to lattice_arm/exec/ (kept out of harness/exec); compact
graded records to lattice_arm/graded/<model>_<effort>.jsonl. Resume-safe."""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(__file__).resolve().parent.parent
for p in ("instruments", "bank", "codebook"):
    sys.path.insert(0, str(R / p))
import grade  # noqa: E402
from bank_runner import load_bank  # noqa: E402

MODEL, EFFORT = sys.argv[1], sys.argv[2]
NOASK = "noask" in sys.argv[3:]
_safe_model = re.sub(r"[^\w.-]", "", MODEL)
LANE = f"{_safe_model}_{EFFORT}"
GENS = R / "arm" / ("gens_noask" if NOASK else "gens") / f"{LANE}.jsonl"
EXEC = R / "arm" / "exec"
GRADED = R / "arm" / ("graded_noask" if NOASK else "graded")
EXEC.mkdir(parents=True, exist_ok=True)
GRADED.mkdir(parents=True, exist_ok=True)
grade.EXEC_DIR = EXEC          # arm manifests live with the arm, not in harness/exec
OUT = GRADED / f"{LANE}.jsonl"

CODE_AS = {"T1v0": "BL-01c", "BL-01a": "BL-01a", "BL-01b": "BL-01b", "BL-01c": "BL-01c"}
# an ask can be phrased as a question OR a statement of need ("I need the SMA
# lookback period; it isn't specified") — sampling caught the statement form
ASK_RE = re.compile(
    r"(?i)what .{0,50}(period|type)|please (provide|specify)|should .{0,40}use\?"
    r"|i need (the|a|an)?\s?.{0,60}(period|type)"
    r"|is(n.t| not) (specified|defined)|unspecified|is required but not")

done = set()
if OUT.exists():
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            j = json.loads(line)
            done.add((j["variant"], j["i"]))

store = grade.Bank(load_bank(current_only=True))
n_new = 0
with OUT.open("a", encoding="utf-8") as fh:
    for line in GENS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        env = json.loads(line)
        key = (env["variant"], env["replicate"])
        if key in done:
            continue
        # FAIRNESS RULE (owner, 2026-08-19): unfinished draws (harness-error,
        # or no-program with an empty response) are EXCLUDED from grading -
        # they never enter any cell's denominator; the generator retries them.
        if env.get("status") == "harness-error" or (env.get("status") == "no-program" and not (env.get("raw_text") or "").strip()):
            continue
        row = {"model": MODEL, "effort": EFFORT, "variant": env["variant"], "i": env["replicate"]}
        if env.get("status") != "program" or not env.get("program"):
            txt = (env.get("raw_text") or "").strip()
            asks = env.get("status") == "no-program" and ("?" in txt[-3:] or ASK_RE.search(txt) is not None)
            row["status"] = "asks-clarifying" if asks else f"gen:{env.get('status')}"
            if asks:
                row["ask_text"] = txt[:140]
        else:
            outname = f"{'LATN' if NOASK else 'LAT'}_{LANE}_{env['variant'].replace('-', '')}_{env['replicate']}"
            rec = grade.grade_program(store, CODE_AS[env["variant"]], env["program"], outname, worker=8)
            row.update({"status": rec["status"], "code": rec.get("code"), "flags": rec.get("flags"),
                        "exec_status": rec.get("exec_status"), "exec_secs": rec.get("exec_secs"),
                        "dofs": rec.get("dofs"), "numeric": (rec.get("numeric") or {}).get("value"),
                        "reason": rec.get("runtime_error")})
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        n_new += 1
        print(f"{LANE} {env['variant']}#{env['replicate']}: {row['status']} code={row.get('code')}", flush=True)
print(f"GRADED {LANE}: +{n_new} (total {len(done) + n_new})")
