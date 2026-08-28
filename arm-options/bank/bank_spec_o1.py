"""Small oracle-bank specification for OPTIONS donor O1v0.

Each void crosses its own fair readings with only the OTHER DOFs that can
structurally interact on that void's registered projection. Every excluded
other DOF receives one OAT run per non-reference level at reference, followed
by one all-excluded-off-reference spot check per reading.

Class separation uses one registered quarter. The pinned reference tuple also
runs over the full donor window as a stability check.
"""
import itertools

CLASS_WINDOW = {
    "start": "2023-07-01",
    "end": "2023-09-30",
    "purpose": "class_separation",
    "registration": "O1_BANK_WINDOW_V2",
}
FULL_DONOR_WINDOW = {
    "start": "2023-04-01",
    "end": "2026-06-30",
    "purpose": "reference_stability_only",
}

DONOR = {
    "start": CLASS_WINDOW["start"],
    "end": CLASS_WINDOW["end"],
    "timezone": "America/New_York",
    "cash": 100000.0,
    "underlying": "SPY",
    "equity_resolution": "minute",
    "option_resolution": "minute",
    "equity_normalization": "raw",
    "bar_minutes": 5,
    "bar_alignment": "ny_clock_first_end_0935",
    "fast_period": 5,
    "entry_start": "09:45",
    "entry_end": "14:30",
    "signal": "fast_prev<=slow_prev_and_fast_now>slow_now",
    "warmup": "in_range_completed_5m_only",
    "missing_5m": "do_not_synthesize",
    "entry_order": "market",
    "one_long_option_at_a_time": True,
    "exit_quote": "positive_bid_ask_midpoint",
    "time_stop": "15:45_previous_trading_day",
    "never_intentionally_hold_to_expiry": True,
    "dof_strike": "gte_101pct",
    "dof_expiry": "min_calendar_dte_7",
    "dof_right": "call",
    "dof_size": "fixed_1",
    "dof_profit": "gain_50pct",
    "dof_exercise": "liquidate_shares_now",
    "dof_no_match": "skip_signal",
    "dof_slow_period": "slow_20",
}

# Reference level FIRST. The DTE 15..35 SPY extension is purchased; therefore
# nearest_calendar_dte_30 is oracle-gradeable and has no DATA_UNSUPPORTED carve-out.
DOFS = {
    "dof_strike": [
        "gte_101pct",
        "nearest_101pct",
        "nearest_otm",
        "nearest_spot",
        "delta_nearest_040",
    ],
    "dof_expiry": [
        "min_calendar_dte_7",
        "nearest_available",
        "min_calendar_dte_1",
        "min_trading_dte_5",
        "nearest_calendar_dte_30",
    ],
    "dof_right": ["call", "put"],
    "dof_size": [
        "fixed_1",
        "fixed_10",
        "one_if_premium_le_1pct_equity",
        "premium_le_1pct_equity",
        "cash_fraction_5pct",
    ],
    "dof_profit": [
        "gain_50pct",
        "gain_25pct",
        "gain_100pct",
        "break_even",
        "time_stop_only",
    ],
    "dof_exercise": [
        "liquidate_shares_now",
        "retain_shares",
        "preempt_exercise",
        "do_not_exercise",
        "liquidate_shares_next_open",
    ],
    "dof_no_match": [
        "skip_signal",
        "retry_next_slice",
        "relax_strike",
        "relax_expiry",
        "raise_error",
    ],
    "dof_slow_period": [
        "slow_20",
        "slow_10",
        "slow_15",
        "slow_30",
        "slow_50",
    ],
}
ALL = list(DOFS)

PROJECTIONS = [
    "full",
    "contracts",
    "option_right",
    "entry_quantity",
    "profit_exit",
    "exercise_disposition",
    "no_match_outcome",
    "entry_times",
]


def _res(dof):
    return {
        level: ({dof: level} if level != DONOR[dof] else {})
        for level in DOFS[dof]
    }


# The exclusion comments are part of the specification. An excluded DOF must
# remain invariant on the registered projection in its OAT and spot runs.
BLANKS = {
    "DONOR": {
        "projection": "full",
        "resolution_dof": None,
        "conditioning": [],
        "why": "Pinned reference, OAT record, interaction spot, and full-window stability.",
        "excluded_why": {
            dof: "No DOF is conditioned in the pinned-reference bank; OAT records sensitivity."
            for dof in ALL
        },
        "resolutions": {"pin": {}},
    },
    "O1e1": {
        "projection": "contracts",
        "resolution_dof": "dof_strike",
        "conditioning": ["dof_expiry", "dof_no_match"],
        "why": (
            "Strike selection interacts with expiry because the candidate chain is "
            "expiry-scoped, and with no-match handling because an absent target can "
            "be skipped, retried, relaxed, or raised."
        ),
        "excluded_why": {
            # Right changes the contract right, not the strike-ranking rule.
            "dof_right": "Right is a common partition; it cannot change strike ranking within that partition.",
            # Quantity is computed only after a contract has been selected.
            "dof_size": "Sizing is downstream of contract selection.",
            # Exit policy acts only after entry and cannot alter the selected contract for that entry.
            "dof_profit": "Profit handling is downstream on the contracts projection.",
            # Exercise handling occurs after expiration/assignment, not at selection.
            "dof_exercise": "Exercise disposition is downstream of contract selection.",
            # Slow period moves signal times but does not change the strike rule at a fixed decision.
            "dof_slow_period": "Signal timing supplies the decision spot but not the strike-rule semantics.",
        },
        "resolutions": _res("dof_strike"),
    },
    "O1e2": {
        "projection": "contracts",
        "resolution_dof": "dof_expiry",
        "conditioning": ["dof_strike", "dof_no_match"],
        "why": (
            "Expiry selection interacts with strike filtering through candidate-set "
            "availability, and with no-match handling when the requested DTE has no candidate."
        ),
        "excluded_why": {
            # Right is a parallel candidate partition and does not change DTE distance.
            "dof_right": "Right cannot change the registered expiry-ranking calculation.",
            # Quantity is computed after expiry and contract selection.
            "dof_size": "Sizing is downstream of expiry selection.",
            # Exit policy cannot alter the expiry selected for the current entry.
            "dof_profit": "Profit handling is downstream on the contracts projection.",
            # Exercise disposition occurs after the selected contract reaches its lifecycle event.
            "dof_exercise": "Exercise disposition is downstream of expiry selection.",
            # Slow period moves decisions but does not change calendar/trading-DTE arithmetic.
            "dof_slow_period": "Signal timing cannot change the expiry-rule semantics at a fixed decision.",
        },
        "resolutions": _res("dof_expiry"),
    },
    "O1e3": {
        "projection": "option_right",
        "resolution_dof": "dof_right",
        "conditioning": ["dof_strike", "dof_expiry", "dof_no_match"],
        "why": (
            "The chosen right is observed only when strike and expiry filters produce "
            "a candidate; no-match handling determines the outcome when that partition is empty."
        ),
        "excluded_why": {
            # Quantity is computed only after a right-bearing contract exists.
            "dof_size": "Sizing is downstream of option-right selection.",
            # Profit handling occurs after entry.
            "dof_profit": "Profit handling cannot change the selected right for an entry.",
            # Exercise handling occurs after contract selection and holding.
            "dof_exercise": "Exercise disposition is downstream of option-right selection.",
            # Slow period moves signal times but cannot reinterpret call versus put.
            "dof_slow_period": "Signal timing cannot change the right-selection rule.",
        },
        "resolutions": _res("dof_right"),
    },
    "O1e4": {
        "projection": "entry_quantity",
        "resolution_dof": "dof_size",
        "conditioning": ["dof_strike", "dof_expiry", "dof_right"],
        "why": (
            "Quantity depends on the selected contract's premium and multiplier; strike, "
            "expiry, and right can all change premium and buying-power consumption."
        ),
        "excluded_why": {
            # Profit handling starts after the entry quantity has been fixed.
            "dof_profit": "Profit handling is downstream of entry sizing.",
            # Exercise handling is exceptional post-entry disposition.
            "dof_exercise": "Exercise disposition is downstream of entry sizing.",
            # No-match changes whether an entry exists, not the sizing formula when one exists.
            "dof_no_match": "The quantity projection is conditional on a selected contract.",
            # Slow period changes entry time, but quantity classes are defined by the formula at that entry.
            "dof_slow_period": "Signal timing supplies inputs but cannot change the sizing-rule semantics.",
        },
        "resolutions": _res("dof_size"),
    },
    "O1e5": {
        "projection": "profit_exit",
        "resolution_dof": "dof_profit",
        "conditioning": ["dof_strike", "dof_expiry", "dof_right"],
        "why": (
            "Whether and when a profit rule fires depends on the selected option price "
            "path, which can change with strike, expiry, and right."
        ),
        "excluded_why": {
            # Percentage/break-even targets use per-contract entry price, not quantity.
            "dof_size": "Quantity scales P&L but cannot change a per-contract profit-trigger crossing.",
            # Exercise handling is reached only after ordinary profit-exit opportunities.
            "dof_exercise": "Exercise disposition is downstream of the profit-exit projection.",
            # The projection is conditional on an entered trade.
            "dof_no_match": "No-match handling controls entry existence, not an entered trade's profit rule.",
            # Slow period changes which trade is sampled, not the registered exit-rule semantics.
            "dof_slow_period": "Signal timing cannot change the profit-rule calculation for an entered trade.",
        },
        "resolutions": _res("dof_profit"),
    },
    "O1e6": {
        "projection": "exercise_disposition",
        "resolution_dof": "dof_exercise",
        "conditioning": ["dof_right"],
        "why": (
            "Exercise disposition interacts with right because calls and puts create "
            "opposite underlying-share effects. The projection begins at the registered "
            "exercise event, so pre-event selection and entry mechanics are outside it."
        ),
        "excluded_why": {
            # Strike affects whether exercise occurs, not how a registered event is handled.
            "dof_strike": "The projection is conditional on an exercise event; strike cannot change its handler.",
            # Expiry schedules the event but cannot change the registered disposition.
            "dof_expiry": "Expiry timing cannot change the event-handler semantics.",
            # Size scales resulting shares but cannot change retain/liquidate/preempt classification.
            "dof_size": "Quantity changes magnitude, not exercise-disposition class.",
            # Profit exit affects reachability, not handling once the event is presented.
            "dof_profit": "The projection is conditional on the exercise event.",
            # No-match affects entry reachability, not event handling.
            "dof_no_match": "No-match handling is upstream of the registered event.",
            # Slow period affects entry reachability, not event handling.
            "dof_slow_period": "Signal timing is upstream of the registered event.",
        },
        "resolutions": _res("dof_exercise"),
    },
    "O1e7": {
        "projection": "no_match_outcome",
        "resolution_dof": "dof_no_match",
        "conditioning": ["dof_strike", "dof_expiry"],
        "why": (
            "No-match behavior is invoked by an empty candidate set; strike and expiry "
            "filters jointly determine that emptiness and the available fallback."
        ),
        "excluded_why": {
            # Right is a common candidate partition and cannot change skip/retry/fail semantics.
            "dof_right": "Right may change availability but cannot change the no-match handler.",
            # No contract exists at the classified event, so quantity is not computed.
            "dof_size": "Sizing is unreachable at a no-match event.",
            # No position exists, so profit exit is unreachable.
            "dof_profit": "Profit handling is unreachable at a no-match event.",
            # No position exists, so exercise handling is unreachable.
            "dof_exercise": "Exercise handling is unreachable at a no-match event.",
            # Slow period schedules the event but cannot change its handler.
            "dof_slow_period": "Signal timing cannot change skip/retry/fallback/fail semantics.",
        },
        "resolutions": _res("dof_no_match"),
    },
    "O1e8": {
        "projection": "entry_times",
        "resolution_dof": "dof_slow_period",
        "conditioning": ["dof_profit"],
        "why": (
            "Slow period determines crossover times; profit exit interacts because the "
            "one-position gate can suppress a later crossover until the prior trade exits."
        ),
        "excluded_why": {
            # Contract moneyness cannot move the already-computed crossover timestamps.
            "dof_strike": "Strike selection is downstream of the entry signal.",
            # Expiry selection cannot move the already-computed crossover timestamps.
            "dof_expiry": "Expiry selection is downstream of the entry signal.",
            # Option right cannot move the underlying moving averages.
            "dof_right": "Right is downstream of the entry signal.",
            # Quantity cannot move a crossover or the one-position occupancy boundary.
            "dof_size": "Sizing is downstream and does not change entry eligibility when fills succeed.",
            # Exercise is excluded by the registered pre-expiry time stop in ordinary paths.
            "dof_exercise": "Exercise disposition cannot move ordinary entry timestamps.",
            # Entry-times comparison is conditional on candidate availability.
            "dof_no_match": "No-match policy cannot change the underlying crossover timestamps.",
        },
        "resolutions": _res("dof_slow_period"),
    },
}

VARIANT_BANKS = {f"O1e{i}": f"O1e{i}" for i in range(1, 9)}
VARIANT_BANKS["O1v0"] = "DONOR"

CLASSES = {}
for bank, spec in BLANKS.items():
    dof = spec["resolution_dof"]
    if dof:
        labels = {level: level.upper() for level in DOFS[dof]}
        CLASSES[bank] = {
            "core": labels,
            "priority": [labels[level] for level in DOFS[dof]],
            "absorbed": [],
        }

# Owned strikes cover only each session's realized range widened by 2%.
# Frequencies are pre-run engineering estimates, not silently accepted loss:
# the manifest must replace them with exact signal-level coverage-audit rates.
COVERAGE_LIMITS = {
    "O1e1": {
        "readings": ["delta_nearest_040"],
        "expected_frequency": 0.03,
        "basis": (
            "Approximately 3% of eligible signals are expected to require a "
            "0.40-delta strike outside the owned +/-2% realized-session band."
        ),
        "action": "Flag COVERAGE_LIMITED per affected run and report exact numerator/denominator.",
    },
    "O1e7": {
        "readings": ["relax_strike"],
        "expected_frequency": 0.01,
        "basis": (
            "Approximately 1% of no-match events are expected to request a "
            "deeper fallback strike outside the owned band."
        ),
        "action": "Flag COVERAGE_LIMITED per affected run and report exact numerator/denominator.",
    },
}


def class_name(bank, matched_resolutions):
    reg = CLASSES.get(bank)
    if not reg:
        return "+".join(sorted(matched_resolutions))
    cores = {reg["core"].get(r, r) for r in matched_resolutions}
    named = [core for core in reg["priority"] if core in cores]
    return named[0] if named else "+".join(sorted(cores))


def _excluded_other(spec):
    own = spec["resolution_dof"]
    return [
        dof for dof in ALL
        if dof != own and dof not in spec["conditioning"]
    ]


def validate_spec():
    for bank, spec in BLANKS.items():
        own = spec["resolution_dof"]
        assert own not in spec["conditioning"], bank
        excluded = set(_excluded_other(spec))
        assert excluded == set(spec["excluded_why"]), (
            bank,
            sorted(excluded - set(spec["excluded_why"])),
            sorted(set(spec["excluded_why"]) - excluded),
        )


def grid_for(bank_id):
    spec = BLANKS[bank_id]
    excluded = _excluded_other(spec)
    for resolution, override in spec["resolutions"].items():
        effective = [
            dof for dof in spec["conditioning"]
            if dof not in override
        ]
        products = itertools.product(*(DOFS[dof] for dof in effective))
        if not effective:
            products = [()]

        for combo in products:
            setting = dict(zip(effective, combo))
            params = dict(DONOR)
            params.update(override)
            params.update(setting)
            is_ref = all(params[dof] == DONOR[dof] for dof in effective)
            tag = "ref" if is_ref else "T_" + "_".join(
                f"{dof}={params[dof]}" for dof in effective
            )
            yield resolution, params, "grid", tag

        # One OAT run for every non-reference level of every excluded other DOF.
        for dof in excluded:
            for level in DOFS[dof][1:]:
                params = dict(DONOR)
                params.update(override)
                params[dof] = level
                yield resolution, params, "oat", f"OAT_{dof}={level}"

        # One simultaneous off-reference check for all excluded other DOFs.
        if excluded:
            params = dict(DONOR)
            params.update(override)
            for dof in excluded:
                params[dof] = DOFS[dof][1]
            yield resolution, params, "spot", "SPOT_all_excluded_off"

    # The single pinned reference tuple, not every resolution/tuple, receives
    # the expensive full-donor-window stability run.
    if bank_id == "DONOR":
        params = dict(DONOR)
        params.update(
            start=FULL_DONOR_WINDOW["start"],
            end=FULL_DONOR_WINDOW["end"],
        )
        yield "pin", params, "stability", "REF_full_donor_window"


def derived_table():
    validate_spec()
    rows, total = [], 0
    for bank, spec in BLANKS.items():
        runs = sum(1 for _ in grid_for(bank))
        rows.append(
            (bank, len(spec["resolutions"]), len(spec["conditioning"]), runs)
        )
        total += runs
    return rows, total


# Arithmetic:
# DONOR: 1 grid + 29 OAT + 1 spot + 1 full-window stability = 32
# O1e1: 5 * (5*5 grid + 17 OAT + 1 spot) = 215
# O1e2: 5 * (5*5 grid + 17 OAT + 1 spot) = 215
# O1e3: 2 * (5*5*5 grid + 16 OAT + 1 spot) = 284
# O1e4: 5 * (5*5*2 grid + 16 OAT + 1 spot) = 335
# O1e5: 5 * (5*5*2 grid + 16 OAT + 1 spot) = 335
# O1e6: 5 * (2 grid + 24 OAT + 1 spot) = 135
# O1e7: 5 * (5*5 grid + 17 OAT + 1 spot) = 215
# O1e8: 5 * (5 grid + 21 OAT + 1 spot) = 135
# TOTAL = 1,901 oracle runs.
assert derived_table()[1] == 1901
assert derived_table()[1] <= 2500

if __name__ == "__main__":
    print(f"{'bank':8s} res cond runs")
    for bank, resolutions, cond, runs in derived_table()[0]:
        print(f"{bank:8s} {resolutions:3d} {cond:4d} {runs:5d}")
    print("TOTAL runs", derived_table()[1])