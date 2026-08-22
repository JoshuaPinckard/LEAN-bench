"""Grade one clean-room batch lane through the certified chain.
Usage: python bench-grade.py <batch-date> <lane-file-stem>
  e.g.  python bench-grade.py 2026-08-21 codex_gpt-5.6-luna_low_BL-01b
Reads  batches/<date>/<stem>.jsonl   (instruments/generate.js envelopes)
Writes batches/<date>/graded/<stem>.jsonl ; engine manifests to exec/.
Bank routing via grade.bank_for (VARIANT_BANKS): BL-02b' -> CROSS,
ER-01c -> ER-01, BL-00 -> DONOR, T1v0 -> baseline. Resume-safe.

ASK RULE (stated): a draw with no extractable program counts as
asks-clarifying iff its text ends with '?' OR matches ASK_RE below -
a question or a statement of need naming the withheld quantity. Empty
no-program text is excluded (unfinished; the generator retries it)."""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "instruments"))
import grade  # noqa: E402
from bank_runner import load_bank  # noqa: E402

DATE, STEM = sys.argv[1], sys.argv[2]
GENS = R / "batches" / DATE / f"{STEM}.jsonl"
GRADED_DIR = R / "batches" / DATE / "graded"
GRADED_DIR.mkdir(parents=True, exist_ok=True)
OUT = GRADED_DIR / f"{STEM}.jsonl"
grade.EXEC_DIR = R / "exec"
grade.EXEC_DIR.mkdir(exist_ok=True)

ASK_RE = re.compile(
    r"(?i)what .{0,60}(period|percent|number|threshold|value|definition|type|mean)"
    r"|please (provide|specify|clarify)|should .{0,50}use\?"
    r"|i need (the|a|an)?\s?.{0,70}(period|percent|number|threshold|value|definition|type)"
    r"|is(n.t| not) (specified|defined|stated)|unspecified|ambiguous"
    r"|is required but not|could you (provide|specify|clarify)")

done = set()
if OUT.exists():
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            done.add(json.loads(line)["i"])

store = grade.Bank(load_bank(current_only=True))
n_new = 0
with OUT.open("a", encoding="utf-8") as fh:
    for line in GENS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        env = json.loads(line)
        if env["i"] in done:
            continue
        if env["status"] == "harness-error" or (env["status"] == "no-program" and not (env.get("raw_text") or "").strip()):
            continue                       # unfinished: excluded + retried by the generator
        row = {"surface": env["surface"], "model": env["model"], "effort": env["effort"],
               "prompt_id": env["prompt_id"], "i": env["i"], "prompt_sha256": env["prompt_sha256"],
               "canary": env.get("canary")}
        if env["status"] != "program" or not env.get("program"):
            txt = (env.get("raw_text") or "").strip()
            asks = "?" in txt[-3:] or ASK_RE.search(txt) is not None
            row["status"] = "asks-clarifying" if asks else "no-program"
            if asks:
                row["ask_text"] = txt[:140]
        else:
            lookup_bank, named = grade.bank_for(env["prompt_id"])
            safe = re.sub(r"[^\w.-]", "", f"{env['model']}_{env['effort']}_{env['prompt_id']}_{env['i']}")
            rec = grade.grade_program(store, lookup_bank, env["program"], f"BENCH_{safe}", worker=8)
            row.update({"status": rec["status"], "code": rec.get("code"), "flags": rec.get("flags"),
                        "bank": lookup_bank, "exec_status": rec.get("exec_status"), "exec_secs": rec.get("exec_secs"),
                        "dofs": rec.get("dofs"), "numeric": (rec.get("numeric") or {}).get("value"),
                        "reason": rec.get("runtime_error")})
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        n_new += 1
        print(f"{STEM} #{env['i']}: {row['status']} code={row.get('code')}", flush=True)
print(f"GRADED {STEM}: +{n_new} (total {len(done) + n_new})")
