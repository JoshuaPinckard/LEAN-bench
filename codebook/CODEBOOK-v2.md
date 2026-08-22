# CODEBOOK v2 — PIN-v5 §6 (dated amendment 2026-08-16, vetting-council round 1)

Supersedes CODEBOOK-v1 (whose hash stays in CODEBOOK-HASHES.txt as the
record of what round 1 vetted). Every rule below is implemented in
`dof_extract.py` (AST-first, comments/docstrings stripped) and validated by
`validate_extractor.py` against committed fixtures with TAPE-IMPLIED ground
truth (fixtures/real: the 4 pinned-T1 model programs) plus off-pin
adversarial fixtures (fixtures/synthetic). Result and misses are written to
VALIDATION-REPORT.json; the registered acceptance floor is 0.90 overall
(current: see report). The extractor NEVER gates tape matching (§4.4 v2 —
tuple-free lookup); it feeds (i) the §4.7 extractor-vs-tape validity report,
(ii) no-cue DOF reference coding for the baseline arm and the two placebo
TOSTs, (iii) the numeric codes for numeric blanks. Anything the rules cannot
decide returns `unresolved` — never a guess.

## A. Coded dimensions (behavioral definitions)

**A1 `dof_rsi_smoothing`** — `wilder`: LEAN `RSI(...)`/`RelativeStrengthIndex`
with default or `MovingAverageType.Wilders`, or a hand-rolled recursive
`(avg*(n-1)+x)/n`. `simple`: `MovingAverageType.Simple` or a window mean of
gains/losses. `ema`: `MovingAverageType.Exponential` or an EMA of gains/
losses. Else `unresolved`.

**A2 `dof_warmup`** — `strict`: `SetWarmUp(...)` is called (ANY length; the
presence of IsReady checks is irrelevant — a warmed program trades from bar
1 exactly like the strict oracle; the length is recorded as `warmup_bars`
and matters only for EMA transients, §4.1.4). `ready_check`: no SetWarmUp;
ONE global readiness gate — an early `return` at OnData top level guarded by
IsReady/len tests, directly or through a helper method. `ready_per_rule`:
no SetWarmUp; readiness tested inside strategy-specific conditions (each
leg trades when its own indicators are formed). `none`: neither.

**A3 `dof_a_exec`** — mechanism, INDEPENDENT of the sizing literal:
`set_holdings` (SetHoldings with any numeric/variable target);
`calc_shares` (share count from TotalPortfolioValue arithmetic + a market
order); `pct_cash` (sizing from Portfolio.Cash); else `unresolved`.

**A4 `dof_same_bar_reentry`** — `wait_bar`: the buy gate reads FILL-BASED
state (`Portfolio[..].Invested/Quantity/HoldStock/IsLong`), or a
last-action-bar/date guard, or the buy branch is structurally unreachable
on the sell bar (if/elif, if/else, return-after-sell). `allowed`: the buy
gate reads an OWN flag/share counter that the sell branch resets at
submission. Else `unresolved`.

**A5 `dof_input_field`** — explicit `DataNormalizationMode.{Raw,
SplitAdjusted, TotalReturn}`; otherwise `adjusted` (LEAN default).

**A6 `a_buy_dir` / `a_sell_dir`** — from the A-leg buy/sell condition text:
`up` (crosses above / > MA), `down` (below / <), `any` (both), `unresolved`.

**A7 `dof_rsi_exit`** — `cross`: the exit condition compares a PREVIOUS and
the CURRENT RSI value (or an alias assigned from it) against the threshold
(prev ≤ T and cur > T, or window[1]/[0]); `level`: current value only.

**A8 `dof_cross_timing`** — `both_days`: a previous MA value is kept and
used (prev-variable, `.Previous`, RollingWindow on the MA, index [1]);
`today_ma`: only the current MA is compared with both closes.

## B. Role in matching (§4.4 v2)

Tape lookup is TUPLE-FREE: a generation's projection is matched against
every registered oracle run of its bank (all conditioning tuples); the
matched-resolution set → class label via the pre-registered class registry
(bank_spec.CLASSES); no match at any tuple → DRIFT. **Cross-tuple rule
(2026-08-16, opus-1 R2 #1):** when the matched resolutions span more than
one CORE label, the grader distinguishes (i) a collision that occurs at a
SINGLE conditioning tuple — a registered within-window collapse, coded as
the merged class — from (ii) resolutions that coincide only ACROSS
different tuples, which are distinct conventions that merely agree under
different free-DOF settings. In case (ii) the generation's own extracted
DOFs restrict the candidate tuples; if that yields a unique core it is
coded with a `tuple-restricted` flag, otherwise the draw is
`AMBIGUOUS-ACROSS-TUPLES` (ineligible as an agreeing category, reported in
the §4.5 breakout). Measured on the v2 bank: case (ii) exists only for
OM-C (race vs shared_state, 39 projections); CROSS/BL-04/OM-B cross-core
collisions are all case (i). The extractor's DOF
reads are recorded per draw and compared with the tape-implied tuple in
the §4.7 validity report (disagreement rate reported); they never decide
the primary code. Unsupported levels therefore cannot discard a draw.

## C. Numeric extraction (BL-01b, BL-03, BL-05, BL-08; anchor BL-07; PX-01)

`numeric(blank, text)` → `{value, comparator, status}`. Names are resolved
through single-assignment constants (module-level `X = 3`, `self.X = 3`);
`Decimal("0.40")`, `20_000`, `20,000` parse exactly; fractions ×100 →
percent. The COMPARATOR is recorded verbatim (`>`, `>=`, `==`), never
normalized silently: for BL-05 the registered resolution is (value,
comparator) with `> N` ≡ `>= N+1` stated in the analysis, and for BL-08 a
`>=` reading is a distinct convention flagged beside the value. Two
distinct candidates → `unresolved`; leg present but no literal →
`unresolved`; leg absent → `no-implementation`. Value in the registered
support → that oracle ID (tape mismatch = orthogonal implementation-drift
flag); out of support → `other` (value recorded, clustered exactly).

## D. Registered candidate supports — the SINGLE source of truth is
`bank/bank_spec.py`: `BLANKS[bank]["resolutions"]` (the enumerated readings)
and `CLASSES[bank]` (core labels, naming priority, absorbed cores). This
section does not restate them (a duplicated list is how v1's §D drifted from
the registry — opus-1 R2 #4). As of 2026-08-16 the registry holds: CROSS =
10 cores {CONV, INV, SYM-CHURN, LEVEL, UU, DD, UA, AU, DA, AD} over 20
enumerated resolutions (SYM-WAIT absorbed, annotation only); OM-B =
{PRIVATE, INVESTED_GATE, NETTING, BUYS_FIRST}; OM-C = {PARALLEL, RACE,
SEQUENCE, SHARED_STATE}; BL-09 = {ALL, HALF_DOWN_LASTSELL, HALF_DOWN_HOLD,
HALF_UP}; numeric supports per §C. Any change to the registry is a dated
amendment and re-hash of this file plus bank_spec.py.

## E. Statuses (pre-match, all ineligible as agreeing category)
`harness-error` (transport/CLI/spawn failure — retried; never a model
result), `harness-truncation` (MAX_TOKENS with no program), `no-program`,
`non-runnable` (nonzero exit / timeout / runtime error), `EMPTY-TAPE`
(completed, zero fills), `NO-IMPLEMENTATION` (the blank's strategy leg
produced no fills), `unresolved`, `uncodable`, `EXECUTION-NONDETERMINISTIC`
(flag), `implementation-drift` (flag).

## F. Acceptance — validate_extractor.py is the committed evidence; the §6
two-coder κ/PABAK floor applies to the HUMAN reference coding of the
no-cue DOFs on the 100-sample validation; blinding as §6.
