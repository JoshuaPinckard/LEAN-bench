"""Execution + coding pipeline v2 — PIN-v5 SS4.4/4.6 (vetting-council R1).
- iterates ENVELOPES (every draw gets a graded record; count asserted)
- binds the program to its envelope (sha of env.program), records arm/
  model/effort/cell from the envelope, refuses mismatches
- statuses BEFORE matching: harness-error / harness-truncation / no-program
  / non-runnable / EMPTY-TAPE / NO-IMPLEMENTATION (leg has no fills)
- TUPLE-FREE lookup: projection matched against every registered oracle
  run of the bank (all tuples); matched set -> pre-registered class label;
  none -> DRIFT (projection hash kept for clustering)
- numeric blanks: extracted value = code (+comparator); tape mismatch vs
  that value's oracles (any tuple) = implementation-drift FLAG
- extractor reads recorded per draw for the SS4.7 report (never a gate)
- --control: (a) lookup control over ALL bank runs; (b) EXECUTION control:
  fresh engine runs of a registered subset (every 'ref' oracle source, the
  donor, the 4 real pinned-T1 programs) through THIS pipeline; exit non-zero
  on any miss; control_report.json written
- --stride: per model x effort stratum, every 25th draw run twice; both
  tape hashes + EXECUTION-NONDETERMINISTIC flag persisted
- arms: variant id -> bank via bank_spec.VARIANT_BANKS (ER-01c expected R1)
"""
import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "bank")); sys.path.insert(0, str(R / "codebook"))
from bank_runner import (engine_exec, worker_project, completion, raw_tape, all_projections,  # noqa: E402
                         BT, load_bank, verify_freeze, build_source, executed_source_sha)
from bank_spec import BLANKS, VARIANT_BANKS, EXPECTED_CONTROL, DONOR, CLASSES, class_name  # noqa: E402
import dof_extract  # noqa: E402

NUMERIC = {b for b, s in BLANKS.items() if s.get("coded_by") == "numeric"}
NUMERIC_KEY = {
    "BL-01b": ("a_ma_period", lambda v: f"p{v}"), "BL-03": ("a_size_pct", lambda v: f"pct{v}"),
    "BL-05": ("b_red_days", lambda v: f"d{v}"), "BL-08": ("b_rsi_thresh", lambda v: f"t{v}"),
    "BL-07": ("b_rsi_period", lambda v: f"p{v}"), "PX-01": ("b_cash_amt", lambda v: f"c{v}"),
}
LEG_OF = {"A_entries_exits": "SPY", "A_full": "SPY", "A_sell_ratio": "SPY", "B_entries": "AAPL", "B_exits": "AAPL", "B_full": "AAPL",
          "dates_all": None, "full": None}
EXEC_DIR = R / "exec"
EXEC_DIR.mkdir(exist_ok=True)


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def armPrompt(arm):
    """The FROZEN prompt for an arm, resolved exactly as the runner resolves it
    (probes/<arm>.txt, the baseline donor, else the frozen variant id) — so
    binding checks compare against the artifact, not against the envelope's
    own claim about itself."""
    p = R / "probes" / f"{arm}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    if arm == "T1v0":
        return (R / "prompts" / "T1v0.txt").read_text(encoding="utf-8")
    vs = json.loads((R / "prompts" / "variants-v5.json").read_text(encoding="utf-8"))
    for v in vs["variants"]:
        if v["id"] == arm:
            return v["prompt"]
    raise KeyError(f"no frozen prompt artifact for arm {arm!r}")


def binding_error(env, file_stem, arm, expect_prompt):
    """None if the envelope is bound to this arm and its own contents, else the
    refusal reason. Implements the pin's registered claim ('the graded record
    is BOUND to its envelope ... mismatches are refused'), which was asserted
    and never enforced (B9). Factored out so it can be shown to refuse."""
    if env.get("schema") != "lb-envelope-v2":
        return f"schema {env.get('schema')!r} != lb-envelope-v2"
    if env.get("arm") is not None and env.get("arm") != arm:
        return f"envelope arm {env.get('arm')!r} != {arm!r} (would grade against the wrong bank)"
    if env.get("stem") is not None and env.get("stem") != file_stem:
        return f"envelope stem {env.get('stem')!r} != filename stem {file_stem!r}"
    if env.get("program") and env.get("program_sha256") and sha(env["program"]) != env["program_sha256"]:
        return "program does not hash to its own recorded program_sha256"
    if expect_prompt and env.get("prompt_sha256") and env["prompt_sha256"] != expect_prompt:
        return f"prompt_sha256 {str(env.get('prompt_sha256'))[:12]} != the frozen artifact {expect_prompt[:12]}"
    return None


def bank_for(arm_or_variant):
    b = VARIANT_BANKS.get(arm_or_variant)
    if not b:
        raise KeyError(f"no bank mapping for {arm_or_variant}")
    if BLANKS[b].get("alias_of"):
        return BLANKS[b]["alias_of"], b
    return b, b


class Bank:
    """Index: projection -> {(resolution, conditioning-tuple)} over ALL grid
    runs. Matching is tuple-free (a generation is compared against every
    registered run), but the TUPLE is retained so a merge that only happens
    ACROSS tuples is never silently treated as a within-tuple collapse
    (opus-1 R2 #1: measured — OM-C race vs shared_state, 39 projections)."""
    def __init__(self, recs):
        self.recs = recs
        self.idx = {}      # bank -> kind -> proj -> {(res, tuple)}
        self.by_res = {}   # bank -> res -> set(proj) (numeric drift flag)
        for r in recs.values():
            # grid AND oat/spot: every completed run is a legitimate
            # (resolution, settings) pair a generation could reproduce
            # (sol-1 R2: 329 registered runs were omitted from the index)
            if not r["complete"] or r["projections"] is None:
                continue
            b = r["bank"]
            cond = BLANKS[b]["conditioning"]
            tup = tuple(sorted((d, r["params"][d]) for d in cond))
            for k, p in r["projections"].items():
                self.idx.setdefault(b, {}).setdefault(k, {}).setdefault(p, set()).add((r["resolution"], tup))
            pk = BLANKS[b]["projection"]
            self.by_res.setdefault(b, {}).setdefault(r["resolution"], set()).add(r["projections"][pk])

    def pairs(self, bank, kind, proj):
        return set(self.idx.get(bank, {}).get(kind, {}).get(proj, set()))

    def match(self, bank, kind, proj):
        return {res for res, _ in self.pairs(bank, kind, proj)}


def code_generation(bank_store, bank_id, program_text, tape, exec_status, runtime_error=None):
    spec = BLANKS[bank_id]
    pk = spec["projection"]
    rec = {"bank": bank_id, "status": None, "code": None, "flags": [], "matched": None}
    if program_text is None:
        rec["status"] = "no-program"; return rec
    if exec_status == "timeout":
        rec["status"] = "non-runnable"; rec["exec"] = "timeout"; return rec
    if tape is None or exec_status != "ok" or runtime_error:
        rec["status"] = "non-runnable"; rec["exec"] = exec_status; rec["runtime_error"] = runtime_error; return rec
    projs = all_projections(tape)
    proj = projs[pk]
    rec["projection_sha"] = sha(proj); rec["fills"] = len(tape)
    rec["dofs"] = dof_extract.extract(program_text)   # recorded, never a gate
    if len(tape) == 0:
        rec["status"] = "EMPTY-TAPE"; return rec
    leg = LEG_OF[pk]
    if leg and not any(e["symbol"] == leg for e in tape):
        rec["status"] = "NO-IMPLEMENTATION"; rec["leg"] = leg; return rec
    if bank_id in NUMERIC:
        nx = dof_extract.numeric(bank_id, program_text)
        rec["numeric"] = nx
        if nx["status"] != "ok":
            rec["status"] = nx["status"]; return rec
        pname, to_id = NUMERIC_KEY[bank_id]
        v = nx["value"]
        rid = to_id(int(v) if float(v).is_integer() else v)
        rec["extracted_value"] = v; rec["comparator"] = nx.get("comparator")
        if rid in spec["resolutions"]:
            rec["status"] = "coded"; rec["code"] = rid
            oracle_projs = bank_store.by_res.get(bank_id, {}).get(rid, set())
            if proj not in oracle_projs:
                rec["flags"].append("implementation-drift")
        else:
            rec["status"] = "coded"; rec["code"] = "other"
        return rec
    pairs = bank_store.pairs(bank_id, pk, proj)
    hits = {res for res, _ in pairs}
    if not hits:
        rec["status"] = "coded"; rec["code"] = "DRIFT"; return rec
    rec["matched"] = sorted(hits)
    reg = CLASSES.get(bank_id)
    cores = {(reg["core"].get(h, h) if reg else h) for h in hits}
    if len(cores) > 1:
        # A1 FIX (owner-approved session, D8 default = refuse-as-ambiguous).
        # When the tape matches several core readings, NEVER pick a winner:
        # within-tuple collisions used to fall through to class_name(), whose
        # priority order relabelled 241/2,017 known-answer runs INTO the
        # donor's readings (measured on the bank; ground truth by construction).
        # Both collision kinds now take the same path: restrict by the draw's
        # OWN extracted settings; if that fails, the draw is AMBIGUOUS and
        # ineligible. A refused draw costs a data point; a mislabelled one
        # corrupts the result.
        by_tuple = {}
        for res, tup in pairs:
            by_tuple.setdefault(tup, set()).add(reg["core"].get(res, res) if reg else res)
        within = any(len(cs) > 1 for cs in by_tuple.values())
        dofs = rec.get("dofs") or {}
        consistent = set()
        for tup, cs in by_tuple.items():
            if all(dofs.get(d) in (None, "unresolved", v) for d, v in tup):
                consistent |= cs
        if len(consistent) == 1:
            rec["status"] = "coded"; rec["code"] = consistent.pop()
            rec["flags"].append("tuple-restricted")
            return rec
        rec["status"] = "coded"
        rec["code"] = "AMBIGUOUS-AT-TUPLE" if within else "AMBIGUOUS-ACROSS-TUPLES"
        rec["ambiguous_cores"] = sorted(cores)
        return rec
    rec["status"] = "coded"; rec["code"] = class_name(bank_id, hits)
    return rec


def grade_program(bank_store, bank_id, program_text, outname, worker=8, force=False):
    """Execute + code. Execution manifest under harness/exec/<outname>.json,
    keyed by program sha; stale/partial output is never reused."""
    psha = sha(program_text)
    mpath = EXEC_DIR / f"{outname}.json"
    outdir = BT / outname
    m = None
    if mpath.exists() and not force:
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            m = None
    # only a COMPLETE run is reusable: `is not None` cached failures forever,
    # branding a program non-runnable off one engine timeout (issue A7)
    if not (m and m.get("program_sha") == psha and m.get("complete") is True):
        if outdir.exists():
            shutil.rmtree(outdir, ignore_errors=True)
        status, rc, secs = engine_exec(worker_project(worker), program_text, outname)
        done, err = completion(outdir)
        exec_sha = executed_source_sha(outdir)
        if done and exec_sha != psha:
            done = False; status = "source-mismatch"   # LEAN's own copy of the executed code must equal the program
        tape = raw_tape(outdir) if done else None
        m = {"outname": outname, "program_sha": psha, "executed_source_sha": exec_sha, "status": status, "exit_code": rc,
             "secs": round(secs, 1), "complete": done, "runtime_error": err, "tape": tape, "ran_at": dt.datetime.now().isoformat()}
        mpath.write_text(json.dumps(m), encoding="utf-8")
    rec = code_generation(bank_store, bank_id, program_text, m["tape"], m["status"], m.get("runtime_error"))
    rec.update({"exec_status": m["status"], "exec_secs": m["secs"], "program_sha": psha,
                "tape_sha": sha(json.dumps(m["tape"])) if m["tape"] is not None else None})
    return rec


def grade_arm(bank_store, arm, limit=0, workers=1):
    lookup_bank, named_bank = bank_for(arm)
    gdir = R / "probes" / arm / "gens"
    envs = sorted(p for p in gdir.glob("*.json") if ".error." not in p.name)
    if limit:
        envs = envs[:limit]
    out = R / "probes" / arm / "graded.jsonl"
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            done.add(json.loads(line)["stem"])
    # B9: envelope binding enforced — refused envelopes are provenance
    # failures, excluded from the denominator and named, never repaired.
    try:
        expect_prompt = sha(armPrompt(arm))
    except KeyError as e:
        expect_prompt = None
        print(f"PROMPT BINDING DISABLED for {arm}: {e}; other binding checks still apply.", flush=True)
    refused = []
    n = 0
    for ep in envs:
        env = json.loads(ep.read_text(encoding="utf-8"))
        stem = env.get("stem") or ep.stem
        if stem in done:
            continue
        why = binding_error(env, ep.stem, arm, expect_prompt)
        if why:
            refused.append((stem, why))
            print(f"REFUSED {stem}: {why}", flush=True)
            continue
        rec = {"stem": stem, "arm": arm, "bank": lookup_bank, "named_bank": named_bank,
               "model": env.get("model"), "effort": env.get("effort_rank"), "cell": env.get("cell_index"),
               "surface": env.get("surface"), "prompt_sha256": env.get("prompt_sha256"), "used_tools": env.get("used_tools"),
               "env_status": env.get("status")}
        if env.get("status") in ("harness-error", "harness-truncation"):
            rec.update({"status": env["status"], "code": None, "flags": []})
        elif not env.get("program"):
            rec.update({"status": "no-program", "code": None, "flags": []})
        else:
            rec.update(grade_program(bank_store, lookup_bank, env["program"], f"PX_{stem}"))
        if arm in EXPECTED_CONTROL:
            rec["expected"] = EXPECTED_CONTROL[arm]
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        n += 1
        print(stem, rec["status"], rec.get("code"), rec.get("flags"), flush=True)
    clean = [p for p in gdir.glob("*.json") if ".error." not in p.name and ".rejected." not in p.name]
    total = sum(1 for _ in open(out, encoding="utf-8")) if out.exists() else 0
    errs = len([p for p in gdir.glob("*.error.*.json")])
    print(f"graded {n} new; records {total} / clean envelopes {len(clean)} "
          f"(error attempts: {errs}; refused for binding: {len(refused)})")
    if refused:
        print("REFUSED (provenance failures, not model results):")
        for s0, w0 in refused:
            print(f"  {s0}: {w0}")
    assert total + len(refused) == len(clean) or limit, \
        f"graded {total} + refused {len(refused)} != clean envelopes {len(clean)}"


def control(bank_store, execute=True, subset="ref"):
    """(a) lookup control over ALL bank runs; (b) execution control."""
    # EVERY completed run, not just grid: production matches against grid AND
    # oat/spot, so those 329 oracles are live match targets too (issue A6)
    recs = bank_store.recs
    la = lt = 0; lookup_miss = []; by_kind = {}
    for name, r in recs.items():
        if not r["complete"]:
            continue
        b = r["bank"]; pk = BLANKS[b]["projection"]
        hits = bank_store.match(b, pk, r["projections"][pk])
        lt += 1
        k = by_kind.setdefault(r["kind"], {"ok": 0, "total": 0}); k["total"] += 1
        if r["resolution"] in hits:
            la += 1; k["ok"] += 1
        else:
            lookup_miss.append(name)
    kinds = " ".join(f"{k}={v['ok']}/{v['total']}" for k, v in sorted(by_kind.items()))
    print(f"LOOKUP CONTROL: {la}/{lt} bank runs find their own resolution (tuple-free) [{kinds}]")
    report = {"lookup": {"ok": la, "total": lt, "by_kind": by_kind, "misses": lookup_miss[:50]}, "execution": None}
    if execute:
        ea = et = 0; miss = []
        # (b1) every 'ref' oracle source freshly executed through this pipeline.
        # ONE criterion for every bank (numeric, tape, DONOR): the fresh tape's
        # projection must EXACTLY EQUAL the run's own registered projection.
        # The old branches used index MEMBERSHIP, which a wrong tape can satisfy
        # by matching a DIFFERENT run — worst on DONOR, whose 10 runs share one
        # resolution over 10 distinct tapes, so `or True` aside, a broken
        # template emitting an OAT tape still passed (issues A5/A2-of-control).
        for name, r in sorted(recs.items()):
            if r["kind"] != "grid" or r["tag"] != "ref" or not r["complete"]:
                continue
            src = build_source(r["params"])
            g = grade_program(bank_store, r["bank"], src, f"CTL_{name}", worker=8, force=True)
            et += 1
            pk = BLANKS[r["bank"]]["projection"]
            mm = json.loads((EXEC_DIR / f"CTL_{name}.json").read_text(encoding="utf-8"))
            proj = all_projections(mm["tape"])[pk] if mm.get("tape") is not None else None
            hit = proj is not None and proj == r["projections"][pk]
            got = "own-tape" if hit else ("no-tape" if proj is None else "TAPE-DIFFERS")
            ea += bool(hit)
            if not hit:
                miss.append((name, r["resolution"], got, g["status"]))
            print(f"  CTL {name}: {got} [{g['status']}] {'OK' if hit else 'MISS'}", flush=True)
        # (b2) the 4 real pinned-T1 programs, scored against REGISTERED
        # expectations (measured ground truth) — they used to be printed and
        # never counted, which hid a non-runnable fixture inside a clean 93/93.
        REAL_EXPECT = {
            "T1v0_gpt55_s0": ("coded", "PARALLEL"),
            "T1v0_gpt55_s1": ("non-runnable", None),   # Decimal/float TypeError in-engine, 0 events
            "T1v0_sonnet_s0": ("coded", "PARALLEL"),
            "T1v0_sonnet_s1": ("coded", "PARALLEL"),
        }
        real = R / "codebook" / "fixtures" / "real"
        seen = set()
        for p in sorted(real.glob("*.py")):
            txt = p.read_text(encoding="utf-8", errors="replace")
            g = grade_program(bank_store, "OM-C", txt, f"CTL_REAL_{p.stem}", worker=8, force=True)  # OM-C dates_all vs donor-family
            seen.add(p.stem)
            exp = REAL_EXPECT.get(p.stem)
            rhit = bool(exp) and g["status"] == exp[0] and (exp[1] is None or g.get("code") == exp[1])
            et += 1; ea += bool(rhit)
            if not rhit:
                miss.append((f"REAL:{p.stem}", exp, g.get("code"), g["status"]))
            print(f"  CTL real {p.name}: {g['status']} code={g.get('code')} fills={g.get('fills')} "
                  f"[expected {exp}] {'OK' if rhit else 'MISS'}", flush=True)
            report.setdefault("real_programs", []).append({"name": p.name, "status": g["status"], "code": g.get("code"),
                                                           "matched": g.get("matched"), "fills": g.get("fills"),
                                                           "expected": exp, "ok": bool(rhit)})
        for stem in REAL_EXPECT:
            if stem not in seen:   # a registered fixture missing from disk FAILS, never skips
                et += 1; miss.append((f"REAL:{stem}", "registered fixture MISSING", None, "absent"))
        print(f"EXECUTION CONTROL: {ea}/{et} = refs reproduce their own tapes + real fixtures match registered expectations")
        report["execution"] = {"ok": ea, "total": et, "misses": miss}
    # a lookup-only run must never overwrite the full control record that the
    # PIN cites (opus-3 R2 #2): it writes its own file
    name = "control_report.json" if execute else "control_report_lookup_only.json"
    (R / "harness" / name).write_text(json.dumps(report, indent=1), encoding="utf-8")
    ok = (la == lt) and (report["execution"] is None or report["execution"]["ok"] == report["execution"]["total"])
    return 0 if ok else 1


def _stride_pick(model, effort, n=10, seed=20260814):
    """B3: ONE seeded replicate per model x effort cell. The registered 'every
    25th draw' is unimplementable over 10-draw cells (it always chose replicate
    0). This is deterministic, uniform over replicates, and auditable."""
    h = int(hashlib.sha256(f"{seed}|{model}|{effort}".encode()).hexdigest(), 16)
    return h % n


def stride(bank_store, arm):
    """Determinism check: one seeded replicate per model x effort cell executed
    twice; both tape hashes + flag persisted into graded.jsonl records."""
    out = R / "probes" / arm / "graded.jsonl"
    recs = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    gdir = R / "probes" / arm / "gens"
    changed = 0
    for rec in recs:
        if rec.get("status") not in ("coded", "EMPTY-TAPE", "NO-IMPLEMENTATION"):
            continue
        if rec.get("cell") is None or rec["cell"] != _stride_pick(rec.get("model"), rec.get("effort")):
            continue
        env = json.loads((gdir / f"{rec['stem']}.json").read_text(encoding="utf-8"))
        first = EXEC_DIR / f"PX_{rec['stem']}.json"
        t1 = json.loads(first.read_text(encoding="utf-8"))["tape"] if first.exists() else None
        g2 = grade_program(bank_store, rec["bank"], env["program"], f"PX_{rec['stem']}__rerun", worker=8, force=True)
        second = json.loads((EXEC_DIR / f"PX_{rec['stem']}__rerun.json").read_text(encoding="utf-8"))["tape"]
        same = (t1 == second)
        rec["stride"] = {"tape_sha_1": sha(json.dumps(t1)), "tape_sha_2": sha(json.dumps(second)), "identical": same}
        if not same:
            rec.setdefault("flags", []).append("EXECUTION-NONDETERMINISTIC")
        changed += 1
    out.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    print(f"stride: {changed} draws checked twice")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm"); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--control", action="store_true"); ap.add_argument("--no-exec", action="store_true")
    ap.add_argument("--stride", action="store_true")
    a = ap.parse_args()
    verify_freeze(strict=True)
    bank = Bank(load_bank())
    if a.control:
        sys.exit(control(bank, execute=not a.no_exec))
    if a.arm and a.stride:
        stride(bank, a.arm); return
    if a.arm:
        grade_arm(bank, a.arm, a.limit); return
    ap.print_help()


if __name__ == "__main__":
    main()
