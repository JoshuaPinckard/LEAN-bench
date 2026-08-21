"""Oracle-bank runner v2 — PIN-v5 SS4.2/4.3 (vetting-council round 1).
- verifies the DATA FREEZE (aggregate sha over the exact file list) BEFORE
  any engine run; records data hash, engine image digest, lean CLI version,
  git rev, source sha, exit code, completion marker per run (MANIFEST)
- N parallel workers, each in its OWN LEAN project dir (no shared main.py)
- timeout -> kills the process tree AND stops the run's docker container
- completion detected from the result JSON / log, so a zero-order run is a
  tape [] (never 'not run', never 'ok' by mere file presence); stale or
  partial outputs are refused (manifest must match the source sha)
- stores the RAW fill list per run and ALL projection kinds (dates = ET
  calendar dates), so re-projection never needs the engine
- gate + tuple floors + class collapses derived IN CODE, fail-closed

Usage:
  python bank_runner.py --plan                # print job counts
  python bank_runner.py --build --workers 4   # build everything (resumable)
  python bank_runner.py --report              # gate/tuple/class report
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bank_spec import BLANKS, DONOR, DOFS, CUT, PROJECTIONS, grid_for, class_name  # noqa: E402

# Physical path (the Desktop\7.1 Research junction breaks the lean CLI)
BASE = Path(r"C:\Users\joshp\Desktop\8.14\school\7.1 Research\LLMDataAcquisition")
WS = BASE / "complexity_axis_spike" / "lean_ws"
BT = WS / "backtests"
DATA = WS / "data"
TEMPLATE_PATH = HERE / "t1_ref_template.py"
BANK_DIR = HERE / "bank_v2"
BANK_DIR.mkdir(exist_ok=True)
FREEZE_JSON = HERE / "DATA-FREEZE.json"

# ---------------------------------------------------------------- freeze

FREEZE_FILES = [
    "equity/usa/daily/aapl.zip", "equity/usa/daily/aig.zip", "equity/usa/daily/bac.zip",
    "equity/usa/daily/ibm.zip", "equity/usa/daily/spy.zip",
    "equity/usa/factor_files/aapl.csv", "equity/usa/factor_files/aig.csv",
    "equity/usa/factor_files/bac.csv", "equity/usa/factor_files/ibm.csv",
    "equity/usa/factor_files/spy.csv",
    "equity/usa/map_files/aapl.csv", "equity/usa/map_files/aig.csv",
    "equity/usa/map_files/bac.csv", "equity/usa/map_files/ibm.csv", "equity/usa/map_files/spy.csv",
    "alternative/interest-rate/usa/interest-rate.csv",   # E16 (Arm B) custom data
]
REGISTERED_T1_AGGREGATE = "5ae1bdb0e71af54f6c24c28a42bba431976348d40ca2a87ae9b75ec676094680"  # 15 T1 files, 2026-08-15


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def compute_freeze():
    """Aggregate = sha256 over the concatenation of per-file sha256 hex
    strings in FREEZE_FILES order (UTF-8); T1 aggregate = first 15 files."""
    per = {f: sha_file(DATA / f) for f in FREEZE_FILES}
    h_all = hashlib.sha256("".join(per[f] for f in FREEZE_FILES).encode()).hexdigest()
    h_t1 = hashlib.sha256("".join(per[f] for f in FREEZE_FILES[:15]).encode()).hexdigest()
    return per, h_t1, h_all


def engine_identity():
    cfg = json.loads((Path.home() / ".lean" / "config").read_text(encoding="utf-8"))
    img = cfg.get("engine-image", "")
    try:
        ver = subprocess.run(["lean", "--version"], capture_output=True, text=True, shell=True, timeout=60).stdout.strip()
    except Exception:
        ver = "unknown"
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(HERE.parent)).stdout.strip()
    except Exception:
        rev = "unknown"
    return {"engine_image": img, "lean_cli": ver, "git_rev": rev}


def verify_freeze(strict=True):
    per, h_t1, h_all = compute_freeze()
    ok = (h_t1 == REGISTERED_T1_AGGREGATE)
    rec = {"files": per, "t1_aggregate": h_t1, "all_aggregate": h_all,
           "registered_t1_aggregate": REGISTERED_T1_AGGREGATE, "match": ok,
           "engine": engine_identity(), "checked_at": dt.datetime.now().isoformat()}
    FREEZE_JSON.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    if strict and not ok:
        raise SystemExit(f"DATA FREEZE MISMATCH: t1 aggregate {h_t1} != registered {REGISTERED_T1_AGGREGATE}")
    return rec

# ---------------------------------------------------------------- engine

def build_source(params):
    return TEMPLATE_PATH.read_text(encoding="utf-8").replace("{{PARAMS}}", json.dumps(params))


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def run_name(bank, res, tag):
    return f"BANK2_{bank}_{res}__{tag}".replace("'", "q").replace("=", "-")


def worker_project(w=None):
    """Own LEAN project dir per PROCESS (keyed by pid — a job-index key let
    two pool processes share a main.py; council sol-1 #12, found live in
    bank v2 as 20 mixed-source runs). `w` is accepted for compatibility."""
    w = os.getpid() % 100000
    d = WS / f"AxisTestP{w}"
    if not d.exists():
        d.mkdir()
        shutil.copyfile(WS / "AxisTest" / "config.json", d / "config.json")
    return d


def stop_run_containers(outname):
    """Stop any lean_cli_ container whose mounts reference this run."""
    try:
        ids = subprocess.run(["docker", "ps", "-q", "--filter", "name=lean_cli_"],
                             capture_output=True, text=True, timeout=60).stdout.split()
        for cid in ids:
            info = subprocess.run(["docker", "inspect", cid], capture_output=True, text=True, timeout=60).stdout
            if outname in info:
                subprocess.run(["docker", "stop", cid], capture_output=True, timeout=120)
    except Exception:
        pass


def engine_exec(project_dir, src_text, outname, timeout=900):
    (project_dir / "main.py").write_text(src_text, encoding="utf-8")
    logf = project_dir / "engine_last.log"
    t0 = time.time()
    with open(logf, "w", encoding="utf-8", errors="replace") as fh:
        p = subprocess.Popen(["lean", "backtest", project_dir.name, "--output", f"backtests\\{outname}"],
                             stdout=fh, stderr=subprocess.STDOUT, cwd=str(WS), shell=True)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            stop_run_containers(outname)
            return "timeout", None, time.time() - t0
    return ("ok" if rc == 0 else f"exit={rc}"), rc, time.time() - t0


def executed_source_sha(outdir):
    """sha256 of the source LEAN actually executed (its own copy in code/)."""
    cm = Path(outdir) / "code" / "main.py"
    if not cm.exists():
        return None
    return sha(cm.read_text(encoding="utf-8"))


def logged_nonce(outdir):
    """The RUN-NONCE the algorithm logged from INSIDE the container — the
    definitive witness of which source the engine executed."""
    logp = Path(outdir) / "log.txt"
    if not logp.exists():
        return None
    for line in logp.read_text(encoding="utf-8", errors="replace").splitlines():
        if "RUN-NONCE " in line:
            return line.split("RUN-NONCE ", 1)[1].strip()
    return None


def completion(outdir):
    """(complete: bool, runtime_error: str|None). Complete = result JSON
    exists AND the log records LEAN exiting."""
    if not outdir.exists():
        return False, None
    res = list(outdir.glob("*-summary.json")) or [p for p in outdir.glob("*.json") if p.name[:-5].isdigit()]
    logp = outdir / "log.txt"
    exited = False
    err = None
    if logp.exists():
        txt = logp.read_text(encoding="utf-8", errors="replace")
        exited = "Exiting Lean" in txt
        for line in txt.splitlines():
            # "Runtime Error" catches mid-run failures; "exception has occurred"
            # catches initialization/loader failures, which LEAN logs WITHOUT the
            # "Runtime Error" marker (X2: 8/8 init-failed probe manifests carried
            # runtime_error=None while their logs held the exception)
            if "Runtime Error" in line or "exception has occurred" in line:
                err = line[-300:]
                break
    return (bool(res) and exited), err


def raw_tape(outdir):
    """Ordered fill list; None if the run did not complete; [] if it
    completed with zero orders (LEAN writes no order-events file then)."""
    done, _ = completion(outdir)
    if not done:
        return None
    oes = sorted(Path(outdir).glob("*order-events.json"))
    if not oes:
        return []
    evs = json.loads(oes[-1].read_text())
    out = []
    for e in evs:
        if e.get("status") not in ("filled", "partiallyFilled"):
            continue
        # exact ticker identity: LEAN symbol strings are "SPY R735QTJ8XC9X"
        # (ticker + security id); match the ticker token exactly (sol-1 R1 #30)
        sym = str(e.get("symbol", "")).split(" ")[0]
        out.append({"time": float(e["time"]), "symbol": sym, "qty": int(e["quantity"]),
                    "fill_qty": int(e.get("fillQuantity", e["quantity"])),
                    "price": str(e.get("fillPrice", "")), "order_id": int(e.get("orderId", 0)),
                    "status": e.get("status")})
    out.sort(key=lambda x: (x["time"], x["order_id"]))
    return out


def et_date(epoch):
    # fills occur 09:30-16:00 ET; UTC-5 maps both DST cases to the ET date
    return (dt.datetime.utcfromtimestamp(epoch) - dt.timedelta(hours=5)).date().isoformat()


def project(tape, kind):
    """Per-blank projection (SS4.1). Dates = ET calendar dates; quantities are
    the FILLED quantity (a partially filled order must project what actually
    traded, not what was requested — terra-2 R2; zero partial fills exist in
    the v2 bank, so this is a latent-path fix that changes no bank tape)."""
    if tape is None:
        return None
    d = lambda e: et_date(e["time"])
    q = lambda e: int(e.get("fill_qty", e["qty"]))
    side = lambda e: "B" if q(e) > 0 else "S"
    if kind == "full":
        return ";".join(f"{d(e)}|{e['symbol']}|{side(e)}|{abs(q(e))}" for e in tape)
    if kind == "dates_all":
        return ";".join(f"{d(e)}|{e['symbol']}|{side(e)}" for e in tape)
    if kind == "A_entries_exits":
        return ";".join(f"{d(e)}|{side(e)}" for e in tape if e["symbol"] == "SPY")
    if kind == "A_full":
        return ";".join(f"{d(e)}|{side(e)}|{abs(q(e))}" for e in tape if e["symbol"] == "SPY")
    if kind == "A_sell_ratio":
        held = 0; out = []
        for e in tape:
            if e["symbol"] != "SPY":
                continue
            if q(e) > 0:
                held += q(e); out.append(f"{d(e)}|B")
            else:
                sold = -q(e); r = round(sold / held, 2) if held > 0 else 0.0
                out.append(f"{d(e)}|S|{r:.2f}"); held = max(held - sold, 0)
        return ";".join(out)
    if kind == "B_entries":
        return ";".join(d(e) for e in tape if e["symbol"] == "AAPL" and q(e) > 0)
    if kind == "B_exits":
        return ";".join(d(e) for e in tape if e["symbol"] == "AAPL" and q(e) < 0)
    if kind == "B_full":
        return ";".join(f"{d(e)}|{side(e)}|{abs(q(e))}" for e in tape if e["symbol"] == "AAPL")
    raise ValueError(kind)


def all_projections(tape):
    return {k: project(tape, k) for k in PROJECTIONS}

# ---------------------------------------------------------------- jobs

def job_list():
    jobs = []
    for bank in BLANKS:
        if bank in CUT or BLANKS[bank].get("alias_of"):
            continue
        for res, params, kind, tag in grid_for(bank):
            jobs.append({"bank": bank, "res": res, "params": params, "kind": kind, "tag": tag,
                         "name": run_name(bank, res, tag)})
    # de-duplicate by NAME and by PARAMS: when a bank excludes exactly one
    # DOF, its all-off "SPOT" cell is the same experiment as that DOF's OAT
    # cell (identical params, identical tape) — two names for one run made
    # the params-keyed migration cross them (caught by the sha witness).
    seen_names, seen_params, out = set(), set(), []
    for j in jobs:
        pkey = (j["bank"], j["res"], json.dumps(j["params"], sort_keys=True))
        if j["name"] in seen_names or pkey in seen_params:
            continue
        seen_names.add(j["name"]); seen_params.add(pkey); out.append(j)
    return out


def manifest_path(name):
    return BANK_DIR / f"{name}.json"


def load_manifest(name):
    p = manifest_path(name)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def run_job(job, worker, ident, data_hash):
    """Executed in a worker process. Resumable: a manifest whose source sha
    matches and which is complete is reused; anything else is re-run."""
    params = dict(job["params"]); params["_nonce"] = job["name"]
    src = build_source(params)
    ssha = sha(src)
    core_sha = sha(build_source(job["params"]))   # nonce-free: survives renames
    m = load_manifest(job["name"])
    outdir = BT / job["name"]
    if m and m.get("complete") and m.get("data_hash") == data_hash             and (m.get("source_sha") == ssha or m.get("core_sha") == core_sha)             and m.get("source_verified", executed_source_sha(outdir) == m.get("source_sha")):
        return job["name"], "cached"
    if outdir.exists():
        shutil.rmtree(outdir, ignore_errors=True)
    proj = worker_project(worker)
    status, rc, secs = engine_exec(proj, src, job["name"])
    done, err = completion(outdir)
    exec_sha = executed_source_sha(outdir)
    nonce_ok = logged_nonce(outdir) == job["name"]
    src_ok = (exec_sha == ssha) and nonce_ok
    if done and not src_ok:
        done = False; status = "source-mismatch"   # never trust a tape from another job's source
    tape = raw_tape(outdir) if done else None
    rec = {
        "name": job["name"], "bank": job["bank"], "resolution": job["res"], "kind": job["kind"], "tag": job["tag"],
        "params": params, "source_sha": ssha, "core_sha": core_sha, "executed_source_sha": exec_sha, "logged_nonce": logged_nonce(outdir), "source_verified": src_ok,
        "status": status, "exit_code": rc, "complete": done,
        "runtime_error": err, "secs": round(secs, 1), "worker": worker,
        "data_hash": data_hash, "engine": ident, "ran_at": dt.datetime.now().isoformat(),
        "fills": (len(tape) if tape is not None else None),
        "tape": tape, "projections": all_projections(tape) if tape is not None else None,
    }
    manifest_path(job["name"]).write_text(json.dumps(rec), encoding="utf-8")
    return job["name"], f"{status} fills={rec['fills']} ({rec['secs']}s)"


def build(workers):
    fr = verify_freeze(strict=True)
    ident = fr["engine"]
    data_hash = fr["all_aggregate"]
    jobs = job_list()
    print(f"freeze OK t1={fr['t1_aggregate'][:12]} all={data_hash[:12]} engine={ident}", flush=True)
    print(f"jobs={len(jobs)} workers={workers}", flush=True)
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_job, j, i % workers, ident, data_hash): j for i, j in enumerate(jobs)}
        for f in as_completed(futs):
            name, msg = f.result()
            done += 1
            print(f"[{done}/{len(jobs)}] {name}: {msg}", flush=True)
    print("BUILD DONE", flush=True)

# ---------------------------------------------------------------- report

def load_bank(current_only=True):
    """Manifests for the CURRENT job list only. A spec change (e.g. widening
    a bank's conditioning) orphans old manifests; letting them into the gate
    would evaluate invariance against runs the spec no longer defines."""
    valid = {j["name"] for j in job_list()} if current_only else None
    recs = {}
    for p in BANK_DIR.glob("BANK2_*.json"):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if valid is not None and r["name"] not in valid:
            continue
        recs[r["name"]] = r
    return recs


def report():
    recs = load_bank()
    missing = [j["name"] for j in job_list() if j["name"] not in recs or not recs[j["name"]]["complete"]]
    if missing:
        print(f"GATE INCOMPLETE: {len(missing)} of {len(job_list())} registered runs missing/incomplete — e.g. {missing[:3]}")
    out = {"generated": dt.datetime.now().isoformat(), "runs": len(recs), "banks": {}}
    for bank, spec in BLANKS.items():
        if bank in CUT or spec.get("alias_of"):
            continue
        cond = spec["conditioning"]
        pk = spec["projection"]
        rows = [r for r in recs.values() if r["bank"] == bank]
        grid = [r for r in rows if r["kind"] == "grid"]
        expected = sum(1 for j in job_list() if j["bank"] == bank)   # deduped list, same source as the build
        incomplete = [r["name"] for r in rows if not r["complete"]]
        # per conditioning tuple: projection -> resolutions
        by_tuple = {}
        for r in grid:
            if not r["complete"]:
                continue
            key = tuple(sorted((d, r["params"][d]) for d in cond)) + (("wb", r["params"].get("dof_warmup_bars")),)
            key = tuple(sorted((d, r["params"][d]) for d in cond))
            by_tuple.setdefault(key, {}).setdefault(r["projections"][pk], set()).add(r["resolution"])
        floors, collapses, classes_seen = [], {}, set()
        for key, m in by_tuple.items():
            nondeg = {p: rs for p, rs in m.items() if p != ""}
            floors.append(len(nondeg))
            for p, rs in nondeg.items():
                if len(rs) > 1:
                    collapses.setdefault("+".join(sorted(rs)), 0)
                    collapses["+".join(sorted(rs))] += 1
                classes_seen.add(class_name(bank, rs))
        # OAT invariance: excluded DOFs must not move the projection vs reference
        oat_fail = []
        ref = {r["resolution"]: r["projections"][pk] for r in grid if r["tag"] == "ref" and r["complete"]}
        for r in rows:
            if r["kind"] in ("oat", "spot") and r["complete"]:
                if r["projections"][pk] != ref.get(r["resolution"]):
                    oat_fail.append((r["resolution"], r["tag"]))
        gate = "PASS" if (rows and not incomplete and floors and min(floors) >= 2
                          and len(rows) == expected) else ("INCOMPLETE" if len(rows) != expected else "FAIL")
        if len(spec["resolutions"]) == 1:
            gate = "N/A"
        out["banks"][bank] = {
            "resolutions": len(spec["resolutions"]), "runs": len(rows), "expected_runs": expected,
            "incomplete": incomplete, "tuples": len(by_tuple), "min_classes": (min(floors) if floors else None),
            "non_discriminating_tuples": sum(1 for f in floors if f < 2),
            "collapses": collapses, "class_labels": sorted(classes_seen),
            "oat_invariance_failures": oat_fail, "gate": gate,
        }
        print(f"{bank}: runs {len(rows)}/{expected} incomplete={len(incomplete)} tuples={len(by_tuple)} "
              f"min_classes={out['banks'][bank]['min_classes']} nondisc={out['banks'][bank]['non_discriminating_tuples']} "
              f"oat_fail={len(oat_fail)} classes={sorted(classes_seen)} -> {gate}")
    (HERE / "gate_report_v2.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--verify-freeze", action="store_true")
    a = ap.parse_args()
    if a.plan:
        jobs = job_list(); print("jobs", len(jobs))
        from collections import Counter
        print(Counter(j["bank"] for j in jobs))
        return
    if a.verify_freeze:
        print(json.dumps(verify_freeze(strict=False), indent=1)[:1200]); return
    if a.build:
        build(a.workers); return
    if a.report:
        report(); return
    ap.print_help()


if __name__ == "__main__":
    main()
