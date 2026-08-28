# O1 oracle-bank run plan

## Registered windows

Class separation uses **2023-07-01 through 2023-09-30**. This quarter is fixed
before oracle execution. It contains repeated weekly and monthly option-expiry
rolls and includes the July advance followed by the August-September decline,
so both rising and falling SPY trend regimes are represented. The purpose is
class separation, not estimation precision or statistical power.

The pinned reference tuple is additionally run over the full donor window,
**2023-04-01 through 2026-06-30**, as one stability check. The full window is
not multiplied across readings or conditioning tuples.

Before accepting the quarter, the data preflight must confirm:

- at least one completed weekly expiry roll and one monthly expiry roll;
- both positive and negative 20-session SPY close-to-close regimes;
- qualifying 5/20 crossover opportunities in both regimes; and
- complete underlying coverage for every regular session used.

Failure is a data-validity failure of the registered window, not permission to
search for a quarter that gives more convenient class separation.

## Conditioning discipline

Each per-void bank crosses the void's own readings with only other DOFs that
can structurally interact on its registered projection. The exact inclusion
and exclusion arguments are registered beside each bank in
`bank_spec_o1.py`.

For every excluded other DOF, every non-reference level is run OAT with all
remaining parameters at reference. Each reading also receives one
all-excluded-off-reference spot check. Movement on the registered projection
invalidates that exclusion: stop the bank, expand only the demonstrated
interaction, update the registered count, and retain the 2,500-run ceiling.

The projections deliberately classify void-local behavior:

| Bank | Projection | Condition only on |
|---|---|---|
| O1e1 | selected contracts | expiry, no-match |
| O1e2 | selected contracts | strike, no-match |
| O1e3 | selected option right | strike, expiry, no-match |
| O1e4 | entry quantity | strike, expiry, right |
| O1e5 | profit-exit behavior | strike, expiry, right |
| O1e6 | exercise-event disposition | right |
| O1e7 | no-match outcome | strike, expiry |
| O1e8 | entry timestamps | profit exit |

O1e4 classification is conditional on a successfully selected contract. O1e5
is conditional on an entered trade. O1e6 begins at a registered exercise event
and classifies its handler; strike, expiry, entry, and exit choices affect event
reachability but not the handler's semantics. O1e7 begins at a registered empty
candidate set. These event-conditioned projections are what permit small,
structurally justified banks rather than a full strategy cross.

## Derived run count

For a bank reading, the count is:

`conditioning factorial + excluded non-reference OAT levels + one spot check`.

The void's own DOF is resolution-bearing and is neither crossed again nor
treated as an excluded OAT DOF.

| Bank | Readings | Conditioning product | OAT per reading | Spot per reading | Runs |
|---|---:|---:|---:|---:|---:|
| DONOR | 1 | 1 | 29 | 1 | 31 |
| DONOR full-window stability | 1 | 1 | 0 | 0 | 1 |
| O1e1 | 5 | 25 | 17 | 1 | 215 |
| O1e2 | 5 | 25 | 17 | 1 | 215 |
| O1e3 | 2 | 125 | 16 | 1 | 284 |
| O1e4 | 5 | 50 | 16 | 1 | 335 |
| O1e5 | 5 | 50 | 16 | 1 | 335 |
| O1e6 | 5 | 2 | 24 | 1 | 135 |
| O1e7 | 5 | 25 | 17 | 1 | 215 |
| O1e8 | 5 | 5 | 21 | 1 | 135 |
| **Total** |  |  |  |  | **1,901** |

Thus the complete registered plan is **599 runs below the 2,500-run ceiling**.

## Data validity and coverage limits

Freeze and hash the exact SPY DBN source list, converted LEAN ZIP list,
converter source, oracle source, LEAN image digest, CLI version, Git revision,
registered windows, and generated run manifest. Refuse an existing resume
target whose manifest differs. Refuse converted sessions whose row counts
differ from their decoded DBN inputs.

The DTE 15-35 SPY extension is being purchased. O1e2's
`nearest_calendar_dte_30` reading is therefore oracle-gradeable. It must be
run and classified normally; there is no `DATA_UNSUPPORTED` carve-out for
30 DTE. The freeze gate must nevertheless prove that the extension is present
for every required session before execution.

Owned strikes cover only each session's realized underlying range widened by
2%. Coverage is assessed per signal, not inferred from a nonempty daily ZIP:

- **O1e1 is coverage-limited for `delta_nearest_040`.** A 0.40-delta contract
  can lie outside the owned strike band. The preregistered engineering estimate
  is **3% of eligible signals**. Record the exact count of signals whose
  theoretical requested strike lies outside the band and report the observed
  rate beside the class result.
- **O1e7 is coverage-limited for `relax_strike`.** A deep fallback can request
  a strike outside the owned band. The preregistered engineering estimate is
  **1% of no-match events**. Record the exact affected-event numerator and
  denominator.
- O1e2's DTE extension does not extend strike coverage. Any O1e2 signal whose
  selected 30-DTE contract would require an unavailable out-of-band strike is
  flagged `COVERAGE_LIMITED`, while the DTE reading itself remains
  oracle-gradeable.
- O1e3-O1e6 and O1e8 inherit a `COVERAGE_LIMITED` flag whenever the conditioning
  contract-selection tuple requests an out-of-band strike. Such cells remain
  in the manifest but cannot supply negative evidence of reading equivalence.
- `gte_101pct`, `nearest_101pct`, `nearest_otm`, and `nearest_spot` are expected
  to remain inside a session range widened by 2% when evaluated at an in-session
  SPY spot. Audit this assertion rather than assuming it.
- Delta selection additionally requires point-in-time Greeks computed only from
  frozen contemporaneous inputs. Missing or look-ahead-contaminated Greeks are
  a separate validity failure.

Before oracle execution, run a candidate-selection coverage audit over the
registered quarter. Replace the engineering estimates in the report with exact
observed frequencies without changing the registered expectations. Coverage
loss must never be interpreted as an ordinary empty-chain strategy result.

The bridge emits no missing minutes. CBBO observations become constant-OHLC
QuoteBars for the observed minute because cbbo-1m lacks intraminute extrema.
Record that semantic limitation in the freeze manifest.

## Execution order

1. Freeze inputs, implementations, image, versions, windows, and manifest.
2. Verify the purchased DTE 15-35 extension and run the strike-coverage audit.
3. Smoke-test ten sessions, including a holiday-adjacent expiry.
4. Run the short-window donor reference and the full-window stability reference.
5. Run every reading at the all-reference conditioning tuple.
6. Run all excluded-DOF OAT checks and all-off-reference spot checks.
7. Stop and revise a bank if an excluded DOF moves its projection.
8. Run the remaining conditioning factorial cells only after invariance passes.

## Acceptance checks

- Re-run the donor and at least one non-reference cell from clean result
  directories; require identical ordered fills and projected outputs.
- Verify no observation later than algorithm time influenced contract selection.
- Confirm the first completed regular-session five-minute bar ends at 09:35 ET
  across daylight-saving transitions.
- Confirm missing source minutes remain missing and are not forward-filled.
- Preserve selected expiry, strike, right, entry price, quantity, ordered fills,
  exact decimal P&L, terminal holdings, and coverage flags.
- Preserve every reading's matched set; use the registered tuple-invariant class
  label only for naming collapsed classes.
- A reading that never separates on valid, covered cells is not oracle-gradeable;
  flag it rather than scoring it.
- Require zero open orders at the end of every successful run. Nonzero terminal
  holdings are permitted only where the registered O1e6 reading requires them.