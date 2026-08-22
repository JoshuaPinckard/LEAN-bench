# CODEBOOK v1 — PIN-v5-2026-08-15 §6 (hashed and committed BEFORE any probe)

Scope after §4: **resolution coding is the deterministic tape instrument**
(bank/bank_runner.py projections + bank/bank.json lookups; this document
does not govern it). This codebook governs exactly three things:
(A) the **no-cue DOF reference coding** (baseline arm; both placebo TOSTs);
(B) the **mechanical DOF extractor** that conditions the tape lookup
(§4.1.4); (C) the **numeric extractor** for BL-01b/03/05/08 + anchor BL-07
+ PX-01 (§4.4). Every rule below is a program-text rule; a coder cites the
line(s). Codes are closed sets; anything outside is the named residual.

## A. No-cue DOF reference coding (5 dimensions; every generation)

Each dimension is coded from the program text ONLY (blind to model,
effort, tape). Codes marked ⟂ are ineligible in every modal set.

### A1. `dof_rsi_smoothing` — how the 14-day RSI averages gains/losses
| code | rule (program text) |
|---|---|
| `wilder` | uses LEAN's `RSI(...)` / `RelativeStrengthIndex` with default MovingAverageType (Wilder), OR explicit `MovingAverageType.Wilders`, OR a hand-rolled recursive `(prev*(n-1)+x)/n` |
| `simple` | explicit `MovingAverageType.Simple`, OR a hand-rolled window mean of gains/losses, OR `pandas.rolling(n).mean()` on gains |
| `ema` | explicit `MovingAverageType.Exponential` or hand-rolled EMA of gains/losses (k=2/(n+1)) |
| `other-exact` ⟂ | any other identifiable formula (record verbatim) |
| `unresolved` ⟂ | RSI absent or not used by B's sell rule |

### A2. `dof_warmup` — how the program gates trading until indicators are formed
| code | rule |
|---|---|
| `strict` | `SetWarmUp(...)` present with `IsWarmingUp` return in OnData, no other readiness gate |
| `ready_check` | gates on indicator `.IsReady` (or window `.IsReady`/len ≥ n) with no `SetWarmUp`, OR both present |
| `none` | no warmup and no readiness gate (trades from bar 1; indicators may be unformed) |
| `other-exact` ⟂ | any other gate (record) |

### A3. `dof_a_exec` — how "invest 40% of total portfolio value" executes
| code | rule |
|---|---|
| `calc_shares` | computes `floor(0.40 * TPV / price)` (any equivalent arithmetic) and places a `MarketOrder` for that quantity |
| `set_holdings` | `SetHoldings(SPY, 0.40)` (or `0.4`) — LEAN targets the position, including fees/buffer |
| `pct_cash` | 40% of **cash** rather than TPV (any variant) |
| `other-exact` ⟂ | any other sizing (record) |

### A4. `dof_same_bar_reentry` — may A's buy fire on the same bar its lot was sold?
| code | rule |
|---|---|
| `allowed` | buy reason is evaluated after the sell branch on the same bar with no bar-index/date guard (the contract's literal "evaluate sells before buys" reading) |
| `wait_bar` | any guard preventing a buy on the bar of a sell: `elif`, `return` after sell, last-action-bar/date check, or evaluating buys before sells |
| `unresolved` ⟂ | structure makes the question undecidable from text (record) |

### A5. `dof_input_field` — price series normalization
| code | rule |
|---|---|
| `adjusted` | LEAN default (no `SetDataNormalizationMode`), OR explicit `Adjusted` |
| `raw` | explicit `DataNormalizationMode.Raw` |
| `split_adjusted` / `total_return` | explicit those modes |
| `other-exact` ⟂ | anything else (record) |

## B. Mechanical DOF extractor (conditions the tape lookup, §4.1.4)

The extractor is a program (`codebook/dof_extract.py`, committed with this
file) applying regex/AST rules that mirror A1–A5 for the FIVE conditioning
DOFs. Its output per generation: `{dof: level | "EXTRACTION-FAILED"}`.
Precedence (§4.1.4): the human coder (A) governs reference and placebo
coding; the extractor governs match conditioning; disagreement rate is
reported in the §4.7 coder-validity report. Any DOF the extractor cannot
resolve → the generation is **EXTRACTION-FAILED** for matching, determined
BEFORE tape lookup, ineligible as agreeing, counted in the §4.5 breakout.
Levels the bank does not hold (e.g. `ema` smoothing, `none` warmup,
`pct_cash`) → the generation is coded at the NEAREST REGISTERED level
**only if** the bank's per-tuple gate proves that level's projection is
identical for the blank; otherwise EXTRACTION-FAILED (level unsupported).
That identity check is mechanical (bank lookup), never judgment.

## C. Numeric extractor (BL-01b, BL-03, BL-05, BL-08, BL-07, PX-01)

Rule: the resolution code IS the mechanically extracted value from the
program text — the literal that parameterizes the blanked quantity:
- BL-01b: the integer period argument of Strategy A's moving-average
  construction (`SMA("SPY", N)`, `SimpleMovingAverage(N)`, `RollingWindow(N)`
  used for A's average, or a hand-rolled window length).
- BL-03: the numeric fraction/percentage of TPV in A's sizing (0.40 ↔ 40).
- BL-05: the integer consecutive-red-day count in B's buy rule.
- BL-08: the numeric RSI threshold in B's sell comparison.
- BL-07: the integer RSI period.
- PX-01: the dollar amount in B's buy sizing.
Unit normalization: fractions ×100 → percent; `$20k` → 20000. Ambiguity
(two candidate literals) → `unresolved` ⟂. Absent → `no-implementation` ⟂.
Value in the registered support → that oracle ID (with tape-mismatch as
the orthogonal implementation-drift flag); out of support → `other` (value
recorded verbatim; clustered by exact value for §4.5 promotion).

## D. Registered candidate supports (closed; `other` collapses the rest)

| blank | support (integers unless noted) |
|---|---|
| BL-01a (type) | SMA, EMA, WMA |
| BL-01b (period) | 10, 20, 50, 100, 200 |
| BL-01c | type × period above |
| BL-03 (%) | 10, 20, 25, 40, 50, 100 |
| BL-04 (red def) | prev_close, open_close, prev_close_le |
| BL-05 (days) | 2, 3, 4, 5 |
| BL-07 (RSI period) | 7, 9, 14, 21 |
| BL-08 (RSI thresh) | 50, 60, 70, 80 |
| BL-09 (sell frac) | all, half_down_lastsell, half_down_hold, half_up |
| CROSS (02b/02c) | post-gate classes: CONV, INV-PHASE, SYM-CHURN |
| ER-01 | R1..R6 |
| OM-B | private, shared, netting |
| OM-C | parallel, race, sequence |
| PX-01 ($) | 5000, 10000, 20000, 50000 |

Sources: bank/bank_spec.py (byte-identical enumerations); the bank holds
one oracle per cell. Any support change after this file's hash is a dated
amendment.

## E. Non-resolution statuses (determined BEFORE matching; all ⟂)

`uncodable` (no program / not Python / prose only) · `unresolved`
(program present but the blanked rule is not implemented decidably) ·
`non-runnable` (compile/runtime failure or timeout in the registered
execution pipeline) · `no-implementation` (the blanked strategy leg is
absent) · `EXTRACTION-FAILED` (B) · `EXECUTION-NONDETERMINISTIC` flag
(§4.6 draft policy 4; per-draw flag, not a status).

## F. Coder acceptance (§6, binding in full for A)

Two coders on a 100-generation validation sample drawn by seed 20260814
from the pilot+baseline pool; raw agreement ≥0.95 AND κ≥0.80 per dimension
else the automated coder is demoted to a screening aid and affected blanks
are hand-coded; PABAK reported beside κ; blinding: coders see program text
only, file names randomized.
