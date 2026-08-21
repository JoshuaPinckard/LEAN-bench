"""Oracle-bank specification v2 — PIN-v5 SS4 (vetting-council round 1).
Single source of truth: DOF levels, per-projection CONDITIONING sets with
the structural invariance argument stated, resolution enumerations, the
pre-registered CLASS registry (tuple-invariant labels + absorption
priority), probe banks, and the derived count table.

Grid rule per bank: FULL FACTORIAL over the bank's conditioning set
(interactions covered), plus for every EXCLUDED DOF an OAT run per
resolution at reference (invariance evidence), plus one random
all-off-reference interaction spot-check per resolution.
"""
import itertools

DONOR = {
    "a_ma_type": "SMA", "a_ma_period": 100,
    "a_buy_dir": "up", "a_sell_dir": "down",
    "a_size_pct": 40.0, "a_sell_frac": "all",
    "er01_sell": "none",
    "b_red_def": "prev_close", "b_red_days": 3,
    "b_cash_rule": "skip", "b_cash_amt": 20000.0,
    "b_rsi_period": 14, "b_rsi_thresh": 60.0,
    "missing_bar": "skip_all", "lots": "private", "eval_order": "sells_first",
    "slot_mode": "parallel",
    "dof_rsi_smoothing": "wilder", "dof_rsi_exit": "level",
    "dof_warmup": "strict", "dof_warmup_bars": None,
    "dof_a_exec": "calc_shares", "dof_same_bar_reentry": "allowed",
    "dof_input_field": "adjusted", "dof_cross_timing": "both_days",
}

# Registered free DOFs and levels (reference level FIRST). These are the
# implementation choices the donor prompt leaves open; every level is a
# reading real programs exhibit (evidence: the 4 pinned-T1 programs +
# council simulations).
DOFS = {
    "dof_rsi_smoothing": ["wilder", "simple"],
    "dof_rsi_exit": ["level", "cross"],
    "dof_warmup": ["strict", "ready_check", "ready_per_rule"],
    "dof_a_exec": ["calc_shares", "set_holdings"],
    "dof_same_bar_reentry": ["allowed", "wait_bar"],
    "dof_input_field": ["adjusted", "raw"],
    "dof_cross_timing": ["both_days", "today_ma"],
}
# strict-warmup EMA transient: SetWarmUp length matters for EMA only
# (first-value seed); precomputed lengths, others on demand (SS4.1.4)
EMA_WARMUP_BARS = [None, 150, 200, 252]

# Conditioning sets by projection, with the structural argument (recorded
# per SS4.1.3; the excluded DOFs are ALSO OAT-checked per resolution).
A_DATES = ["dof_warmup", "dof_input_field", "dof_cross_timing"]
A_DATES_WHY = ("A's entry/exit DATES depend only on SPY closes, the MA and the "
               "readiness/timing convention; RSI smoothing/exit, A sizing and "
               "re-entry cannot move them (a bar cannot cross both ways under a "
               "directional reading; A never fails a buy with $1M).")
B_DATES = ["dof_rsi_smoothing", "dof_rsi_exit", "dof_warmup",
           "dof_same_bar_reentry", "dof_input_field"]
B_DATES_WHY = ("B's entry/exit dates depend on AAPL closes, the RSI convention "
               "(smoothing, level-vs-cross), readiness, and same-bar re-entry; "
               "A's sizing/timing cannot reach them (B's $20k gate never binds).")
ALL_DATES = sorted(set(A_DATES) | set(B_DATES))
ALL_DATES_WHY = "Both legs' dates: union of the two arguments above."

# Projections (bank_runner.project). Every run stores ALL kinds.
PROJECTIONS = ["full", "dates_all", "A_entries_exits", "A_full",
               "A_sell_ratio", "B_entries", "B_exits", "B_full"]

ALL = list(DOFS.keys())

def _cross_res():
    """buy_dir x sell_dir over {up, down, any} (9 pairs; sol-1 R1 #3: BL-02c's
    identical clauses admit every pairing) + the level relation, x re-entry."""
    r = {}
    names = {("up", "down"): "conv", ("down", "up"): "inv", ("any", "any"): "sym",
             ("up", "up"): "uu", ("down", "down"): "dd", ("up", "any"): "ua",
             ("any", "up"): "au", ("down", "any"): "da", ("any", "down"): "ad",
             ("level_above", "level_below"): "level"}
    for dirs, tag in names.items():
        for re_, rtag in (("allowed", "reent"), ("wait_bar", "wait")):
            r[f"{tag}_{rtag}"] = {"a_buy_dir": dirs[0], "a_sell_dir": dirs[1],
                                  "dof_same_bar_reentry": re_}
    return r

BLANKS = {
    "DONOR": {"projection": "full", "conditioning": [], "why": "reference + OAT record only (baseline/BL-00 are code-read, not tape-coded)",
              "resolutions": {"pin": {}}, "coded_by": "none"},
    "BL-01a": {"projection": "A_entries_exits", "conditioning": A_DATES, "why": A_DATES_WHY, "coded_by": "tape",
               "resolutions": {"SMA": {}, "EMA": {"a_ma_type": "EMA"}, "WMA": {"a_ma_type": "WMA"}}},
    "BL-01b": {"projection": "A_entries_exits", "conditioning": A_DATES, "why": A_DATES_WHY, "coded_by": "numeric",
               "resolutions": {f"p{p}": ({} if p == 100 else {"a_ma_period": p}) for p in (10, 20, 50, 100, 200)}},
    "BL-01c": {"projection": "A_entries_exits", "conditioning": A_DATES, "why": A_DATES_WHY, "coded_by": "tape",
               "resolutions": {f"{t}{p}": {"a_ma_type": t, "a_ma_period": p}
                               for t in ("SMA", "EMA", "WMA") for p in (10, 20, 50, 100, 200)}},
    "CROSS": {"projection": "A_entries_exits", "conditioning": [d for d in A_DATES],  # re-entry is resolution-bearing
              "why": A_DATES_WHY + " Same-bar re-entry is RESOLUTION-BEARING here (SS4.1.2 named case).",
              "coded_by": "tape", "resolutions": _cross_res()},
    "BL-03": {"projection": "A_full", "conditioning": A_DATES + ["dof_a_exec"], "coded_by": "numeric",
              "why": A_DATES_WHY + " Quantities add the sizing mechanism; TPV path (B-side) affects share counts -> on-demand for other tuples (numeric blank: tape = drift FLAG only).",
              "resolutions": {f"pct{int(v)}": ({} if v == 40 else {"a_size_pct": float(v)}) for v in (10, 20, 25, 40, 50, 100)}},
    "BL-04": {"projection": "B_entries", "conditioning": B_DATES, "why": B_DATES_WHY, "coded_by": "tape",
              "resolutions": {"prev_close": {}, "open_close": {"b_red_def": "open_close"},
                              "prev_close_le": {"b_red_def": "prev_close_le"}}},
    "BL-05": {"projection": "B_entries", "conditioning": B_DATES, "why": B_DATES_WHY, "coded_by": "numeric",
              "resolutions": {f"d{k}": ({} if k == 3 else {"b_red_days": k}) for k in (2, 3, 4, 5)}},
    "BL-07": {"projection": "B_exits", "conditioning": B_DATES, "why": B_DATES_WHY, "coded_by": "numeric",
              "resolutions": {f"p{k}": ({} if k == 14 else {"b_rsi_period": k}) for k in (7, 9, 14, 21)}},
    "BL-08": {"projection": "B_exits", "conditioning": B_DATES, "why": B_DATES_WHY, "coded_by": "numeric",
              "resolutions": {f"t{int(v)}": ({} if v == 60 else {"b_rsi_thresh": float(v)}) for v in (50, 60, 70, 80)}},
    "BL-09": {"projection": "A_sell_ratio", "conditioning": ALL, "coded_by": "tape",
              "why": "Sold/held RATIO (2dp) removes magnitude but the HALF variants' rounding at small residual lots depends on lot size, hence on the whole TPV path (bank v2 OAT evidence) -> full 7-DOF conditioning.",
              "resolutions": {"all": {}, "half_down_lastsell": {"a_sell_frac": "half_down_lastsell"},
                              "half_down_hold": {"a_sell_frac": "half_down_hold"}, "half_up": {"a_sell_frac": "half_up"}}},
    "ER-01": {"projection": "A_entries_exits", "conditioning": A_DATES + ["dof_same_bar_reentry"], "coded_by": "tape",
              "why": A_DATES_WHY + " Same-bar re-entry ADDED (bank v2 OAT evidence): R2/R5 sell on the same cross direction as the buy, so a sell and rebuy can coincide.",
              "resolutions": {f"R{i}": {"er01_sell": f"R{i}"} for i in range(1, 7)}},
    "OM-B": {"projection": "dates_all", "conditioning": ALL_DATES, "why": ALL_DATES_WHY, "coded_by": "tape",
             "resolutions": {"private": {}, "invested_gate": {"lots": "invested_gate"},
                             "netting": {"lots": "netting"}, "buys_first": {"eval_order": "buys_first"}}},
    "OM-C": {"projection": "dates_all", "conditioning": ALL_DATES, "why": ALL_DATES_WHY, "coded_by": "tape",
             "resolutions": {"parallel": {}, "race": {"slot_mode": "race"}, "sequence": {"slot_mode": "sequence"},
                             "shared_state": {"lots": "shared_flag"}}},
    # probes (SS8.2): separately hashed manifests; PX-02 shares CROSS runs
    "PX-01": {"projection": "B_full", "conditioning": B_DATES, "why": B_DATES_WHY, "coded_by": "numeric",
              "resolutions": {f"c{int(v)}": ({} if v == 20000 else {"b_cash_amt": float(v)}) for v in (5000, 10000, 20000, 50000)}},
}
BLANKS["PX-02"] = dict(BLANKS["CROSS"], alias_of="CROSS")

# BL-06 / OM-A: cut by the 2026-08-15 OAT gate; per sol-1 R1 #35 they are
# re-gated on the FULL conditioning grid in v2 (the gate decides, not a
# hard-coded set). CUT is applied only by the v2 gate report.
CUT = set()
BLANKS["BL-06"] = {"projection": "B_full", "conditioning": B_DATES, "why": B_DATES_WHY, "coded_by": "tape",
                   "resolutions": {"skip": {}, "partial": {"b_cash_rule": "partial"}, "nocheck": {"b_cash_rule": "nocheck"}}}
BLANKS["OM-A"] = {"projection": "dates_all", "conditioning": ALL_DATES, "why": ALL_DATES_WHY, "coded_by": "tape",
                  "resolutions": {"skip_all": {}, "try_except": {"missing_bar": "try_except"}, "per_ticker": {"missing_bar": "per_ticker"}}}
# (no_guard crashes on the auxiliary slice by construction; recorded as a
#  crash class in the OM-A README, not enumerated as an oracle)

# Which frozen variants each bank serves (coding-time mapping).
VARIANT_BANKS = {
    "BL-00": "DONOR", "BL-02a": "CROSS", "BL-02b'": "CROSS", "BL-02b": "CROSS", "BL-02c": "CROSS",
    "BL-01a": "BL-01a", "BL-01b": "BL-01b", "BL-01c": "BL-01c",
    "BL-03": "BL-03", "BL-04": "BL-04", "BL-05": "BL-05",
    "BL-07": "BL-07", "BL-08": "BL-08", "BL-09a": "BL-09", "BL-09b": "BL-09",
    "ER-01": "ER-01", "ER-01c": "ER-01", "OM-B": "OM-B", "OM-C": "OM-C",
    "PX-01": "PX-01", "PX-02": "PX-02",
    # baseline arm (pinned donor): tape-compared against the DONOR reference;
    # its convention analysis is code-read from the per-draw DOF record (SS4.6.1)
    "T1v0": "DONOR",
}
EXPECTED_CONTROL = {"ER-01c": "R1"}  # the pinned control's expected reading

# CLASS REGISTRY (SS4.3.2/4.3.4, pre-registered, tuple-invariant labels).
# core: resolution -> core label; priority: which core NAMES a merged class;
# absorbed cores never name a class (recorded as annotation only).
CLASSES = {
    "CROSS": {"core": {**{f"conv_{r}": "CONV" for r in ("reent", "wait")},
                       **{f"inv_{r}": "INV" for r in ("reent", "wait")},
                       "sym_reent": "SYM-CHURN", "sym_wait": "SYM-WAIT",
                       **{f"level_{r}": "LEVEL" for r in ("reent", "wait")},
                       **{f"{t}_{r}": t.upper() for t in ("uu", "dd", "ua", "au", "da", "ad") for r in ("reent", "wait")}},
              "priority": ["CONV", "INV", "SYM-CHURN", "LEVEL", "UU", "DD", "UA", "AU", "DA", "AD"], "absorbed": ["SYM-WAIT"]},
    "BL-04": {"core": {"prev_close": "PREV_CLOSE", "prev_close_le": "PREV_CLOSE_LE", "open_close": "OPEN_CLOSE"},
              "priority": ["PREV_CLOSE", "OPEN_CLOSE", "PREV_CLOSE_LE"], "absorbed": []},
    "OM-B": {"core": {"private": "PRIVATE", "invested_gate": "INVESTED_GATE", "netting": "NETTING", "buys_first": "BUYS_FIRST"},
             "priority": ["PRIVATE", "BUYS_FIRST", "NETTING", "INVESTED_GATE"], "absorbed": []},
    "OM-C": {"core": {"parallel": "PARALLEL", "race": "RACE", "sequence": "SEQUENCE", "shared_state": "SHARED_STATE"},
             "priority": ["PARALLEL", "RACE", "SEQUENCE", "SHARED_STATE"], "absorbed": []},
    "BL-09": {"core": {"all": "ALL", "half_down_lastsell": "HALF_DOWN_LASTSELL", "half_down_hold": "HALF_DOWN_HOLD", "half_up": "HALF_UP"},
              "priority": ["ALL", "HALF_DOWN_LASTSELL", "HALF_DOWN_HOLD", "HALF_UP"], "absorbed": []},
}
CLASSES["PX-02"] = CLASSES["CROSS"]


def class_name(bank, matched_resolutions):
    """Tuple-invariant class label for a matched-resolution set."""
    ms = sorted(matched_resolutions)
    reg = CLASSES.get(bank)
    if not reg:
        return "+".join(ms) if len(ms) > 1 else (ms[0] if ms else "")
    cores = {reg["core"].get(r, r) for r in ms}
    named = [c for c in reg["priority"] if c in cores]
    if not named:
        return "+".join(sorted(cores))
    non_abs = [c for c in named if c not in reg["absorbed"]] or named
    # TUPLE-INVARIANT LABEL: the highest-priority core present. The matched
    # SET varies with the free DOFs (e.g. conv_reent matches only itself at
    # today_ma tuples but collides with level/ua/ad at both_days tuples), so
    # naming a class by the whole set split ONE convention across several
    # categories and corrupted the modal sets (opus-3 R2 #1, opus-4 R2 #1).
    # The full matched set is preserved per draw as an annotation, and the
    # share of draws whose match was ambiguous is reported beside every
    # modal-set figure.
    return non_abs[0]


def grid_for(bank_id):
    """Yield (resolution, params, kind, tag) for the full precompute plan."""
    spec = BLANKS[bank_id]
    if spec.get("alias_of"):
        return
    cond = spec["conditioning"]
    excluded = [d for d in ALL if d not in cond]
    for res, ov in spec["resolutions"].items():
        # DOFs the resolution itself pins are removed from the factorial
        cond_eff = [d for d in cond if d not in ov]
        levels = [DOFS[d] for d in cond_eff]
        for combo in itertools.product(*levels) if cond_eff else [()]:
            setting = dict(zip(cond_eff, combo))
            p = dict(DONOR); p.update(ov); p.update(setting)
            is_ref = all(v == DONOR[d] for d, v in setting.items())
            # FULL level names in the tag: the old [:6] truncation collided
            # ready_check/ready_per_rule and silently deduped every
            # ready_per_rule grid cell (caught by the execution control)
            tag = "ref" if is_ref else "T_" + "_".join(f"{d.replace('dof_','')}={v}" for d, v in sorted(setting.items()))
            yield res, p, "grid", tag
            # EMA transient lengths (strict warmup only)
            if p["a_ma_type"] == "EMA" and p["dof_warmup"] == "strict":
                for wb in EMA_WARMUP_BARS[1:]:
                    q = dict(p); q["dof_warmup_bars"] = wb
                    yield res, q, "grid", tag + f"_wb={wb}"
        # OAT invariance evidence for excluded DOFs (at reference otherwise)
        for d in excluded:
            if d in ov:
                continue
            for lvl in DOFS[d][1:]:
                p = dict(DONOR); p.update(ov); p[d] = lvl
                yield res, p, "oat", f"OAT_{d.replace('dof_','')}={lvl}"
        # interaction spot-check: every excluded DOF off-reference at once
        if excluded:
            p = dict(DONOR); p.update(ov)
            for d in excluded:
                if d not in ov:
                    p[d] = DOFS[d][1]
            yield res, p, "spot", "SPOT_all_excluded_off"


def derived_table():
    rows, total = [], 0
    for bank in BLANKS:
        n = sum(1 for _ in grid_for(bank))
        rows.append((bank, len(BLANKS[bank]["resolutions"]), len(BLANKS[bank]["conditioning"]), n))
        total += n
    return rows, total


if __name__ == "__main__":
    rows, total = derived_table()
    print(f"{'bank':8s} res cond  runs")
    for b, r, c, n in rows:
        print(f"{b:8s} {r:3d} {c:4d} {n:5d}")
    print("TOTAL runs", total)
