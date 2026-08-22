# QuantCode-Bench: A Ground-Truth Audit

**Full report · 2026-07-12**

| | |
|---|---|
| Benchmark under audit | QuantCode-Bench (LimexAILab), commit `f8bda951` (2026-04-21), cloned 2026-07-12 |
| Audit design | [PLAN.md](PLAN.md), pre-registered before any model run |
| Deviations log | [results/deviations.md](results/deviations.md) |
| Raw evidence | `results/` — run ledger, 63 reference implementations, canonical tapes, 12 candidate records, 20 adjudication notes, 20 static screens, metric JSONs |
| Data snapshot | `frozen_cache/` — 8 (symbol, timeframe) pickles, SHA256-hashed, built 2026-07-12 |
| Execution constraint | All LLM calls via claude CLI (~120 calls); no API keys |

---

## 1. Executive summary

QuantCode-Bench asks language models to turn 400 natural-language trading-strategy
descriptions into executable Backtrader code, and scores them with three execution
gates plus a binary LLM judge. It ships no reference implementations, no expected
trades, and no expected outputs of any kind. This audit took a seeded, stratified
sample of 20 of its tasks and asked the two questions its design leaves open:

> **Q1. Does a task even have a correct answer?**
> **Determinacy rate: 3/20 = 15.0% (Wilson 95% CI 5.2%–36.0%).**
> For each task, three independently generated strict-fidelity reference
> implementations (opus ×2, sonnet ×1; every forced choice declared) were executed
> through a verified replica of the benchmark's own harness on frozen data. Only 3
> tasks converged to a single exact fill tape. On 16 tasks the implementations
> diverged, and every divergence was adjudicated back to quoted, unpinned task text
> — not to implementation error. One further task defeated reference production
> entirely (five failed attempts).

> **Q2. Where a correct answer exists, does the judge detect wrong ones?**
> **Judge false-pass rate: 9/10 = 90.0% (Wilson 95% CI 59.6%–98.2%).**
> Twelve candidates were generated under the benchmark's own pipeline on the three
> determinate tasks. All 12 passed all three execution gates. The replicated judge
> passed 10; nine of those ten produce a provably different trade tape than the
> verified reference (10/10 counting order sizes). The verdicts are systematic, not
> noisy: 0/30 flips on repeated judging. The judge never rejected a correct
> candidate (false-fail 0/2).

**Combined verdict: the benchmark cannot measure what it claims to measure.** 85% of
sampled tasks have no unique correct behavior to grade against; on the tasks that
do, the grading instrument passes wrong behavior 90% of the time with perfect
self-consistency. The failure is architectural: the pipeline contains no executable
ground truth even though its own execution stack is deterministic enough to support
exact behavioral oracles — which is precisely the mechanism this audit used to
measure it.

## 2. The benchmark under audit

**Task corpus.** 400 records in `data/benchmark_tasks_multiframe.json`. Each has a
`reformulated_task` (an English strategy description, median ~1,300 characters,
LLM-reformulated from scraped posts — sources: Reddit 183, TradingView 100,
StackExchange 90, GitHub 19, synthetic 8), a difficulty label (197 easy / 116
medium / 87 hard), and a data binding (`yf_symbol`, `timeframe`). The model must
emit one self-contained `TradingStrategy(bt.Strategy)` class using only an
8-indicator whitelist, single data feed, no pandas/numpy.

**Scoring pipeline** (`reward.py`, binary 1.0/0.0):

1. *Structure gate* — regex: `import backtrader`, a `bt.Strategy` subclass,
   `def next(self)`.
2. *Execution gate* — the code runs in an unsandboxed subprocess against a pickled
   yfinance DataFrame (single feed, $10,000 cash, commission 0.001), 120 s timeout.
3. *Activity gate* — at least one completed trade.
4. *Judge gate* — one LLM call, binary.

**The judge, verbatim** (`judge.py`): three criteria (indicator compliance, main
idea, relevance) and these instructions —

> "IMPORTANT: Be LENIENT with simplifications." · "Simplifying to SMA/StdDev for
> Z-score is ACCEPTABLE." · X = 0 only "if the code COMPLETELY DOES NOT COMPLY
> (ignores the main idea)."

If the judge API call throws, the candidate **passes** (`reward.py` comment: "Don't
penalize for judge failures"). If no `Rating: [[X]]` parses, a positive-vs-negative
keyword count over the last 300 characters decides. If no judge endpoint is
configured at all, a keyword grep of the code for indicator names
(sma/ema/rsi/macd/bollinger/vix) decides. The generation-side system prompt
additionally instructs: **"If task is complex, SIMPLIFY it to use only available
indicators"** — the benchmark mandates deviation and then grades with a judge
instructed to forgive deviation.

**What is absent.** No reference implementations (the sole shipped code artifact is
one format example). No expected tapes, trade counts, or P&L. `total_return` is
computed on every run and never used for scoring. No shipped data cache (see F3).

## 3. Audit design

**Pre-registration.** All decisions in [PLAN.md](PLAN.md) were fixed before any
model run: sample selection, ground-truth definition, tape-match key, determinacy
protocol, ambiguity taxonomy, judge replication, and data freeze. Changes are
logged in [results/deviations.md](results/deviations.md) (four entries, §7).

**Sample.** 20 tasks: seeded (20260712) stratified draw — 10 easy, 6 medium, 4 hard
— from the pre-existing 40-task `sample_A.json` (itself a 10% stratified draw of
the 400). Final IDs: 44, 47, 59, 66, 68, 97, 113, 129, 131, 136, 146, 172, 187,
249, 291, 306, 309, 311, 388, 392. All 8 required (symbol, timeframe) data pairs
downloaded on the first attempt — zero replacement swaps.

**Ground truth is defined on the benchmark's own terms.** References implement each
task *as the benchmark binds and executes it*: its data binding (including AAPL
substitution, F2), its wrapper semantics, its cash/commission. Execution runs
through `tape_exec.py`, a line-faithful replica of their `reward.py` wrapper that
additionally records every completed order as (timestamp, side, size, price).
Replica fidelity was verified against their source line-by-line; determinism was
verified empirically (identical code → byte-identical tapes on all 8 frozen pairs).
Correctness key: the ordered **(fill-timestamp, side)** sequence; (…, size) as a
pre-registered sensitivity key.

**Determinacy protocol (Q1).** Per task, k = 3 strict-fidelity reference
implementations from fresh claude-CLI contexts (opus ×2 + sonnet ×1 — cross-model
convergence is stronger evidence than same-model). The prompt fixes
*bench-canonical environment defaults* (PLAN.md D4a — default sizer, `self.close()`
exits, one position, long-only unless stated, pending-order guard, minperiod
warm-up — all taken from the benchmark's own example) so that determinacy measures
**spec**-level ambiguity, not environment noise; every choice the spec forces
beyond those defaults must be declared in a structured `ASSUMPTIONS` block. A task
is DETERMINATE iff all surviving implementations produce the exact same tape.
Divergences were adjudicated per task with quoted spec text under a strict rule: a
divergence counts as implementation error only if an explicit spec sentence
contradicts the code (one repair round available); otherwise the task is
INDETERMINATE with pre-registered ambiguity classes. Adjudicators instrumented and
re-executed references against the frozen data to trace every divergence.

**Judge replication (Q2).** Their prompt template, gate ordering, parsing rules,
and fallback heuristics were extracted verbatim from source and re-implemented over
claude CLI with a Sonnet-family judge (their own README's endorsed judge; their run
script's gpt-5.4 pin is unreachable without an API key — disclosed). Candidates
were generated with their exact single-shot request — `SYSTEM_PROMPT_EN` + their
user wrapper, one message — using sonnet ×2 + haiku ×2 per determinate task, then
run through their gates in their order (the judge sees only gate survivors, as in
their code). Stability: 10 random verdicts re-judged ×3.

**Independent cross-check.** Before any reference existed, 20 independent analyst
screens scored each task against a pin rubric (entry, exit, parameters, sizing,
binding coherence), predicting determinacy. The screens are advisory only; tapes
decide. (They agreed with the empirical outcome on 17 of 19 tape-measured tasks and
missed in both directions — see §4.4.)

## 4. Q1 — Determinacy: 3/20 = 15.0% [5.2%–36.0%]

### 4.1 Result table

| task | difficulty | source | binding | verdict | ref tapes (fills) |
|---|---|---|---|---|---|
| 44 | easy | reddit | AAPL@1d | INDETERMINATE | 146 / 158 / 9 |
| 47 | hard | reddit | BTC-USD@5m | INDETERMINATE | 25 / 2 (·)¹ |
| 59 | medium | reddit | AAPL@5m | **DETERMINATE** | 14 = 14 (·)² |
| 66 | medium | reddit | AAPL@1d | INDETERMINATE | 9 / 7 / 19 |
| 68 | hard | reddit | GC=F@1h | INDETERMINATE | 1725 / 2073 (·)² |
| 97 | easy | stackexchange | AAPL@1d | INDETERMINATE | 2 / 1 / 2* |
| 113 | hard | stackexchange | AAPL@1d | INDETERMINATE | 543 / 254 / 74 |
| 129 | medium | reddit | AAPL@1h | INDETERMINATE | 6 / 6 / 1* |
| 131 | hard | reddit | ES=F@1h | INDETERMINATE | 6 / 6 / 2* |
| 136 | easy | reddit | NVDA@1d | INDETERMINATE | 17 / 20 / 1 |
| 146 | medium | tradingview | AAPL@1d | INDETERMINATE | 5 / 1 / 0 |
| 172 | easy | tradingview | SPT@1h | INDETERMINATE | 2 / 2* / 0 |
| 187 | easy | stackexchange | AAPL@1d | INDETERMINATE | 4 / 10 / 0 |
| 249 | medium | synthetic | AAPL@1d | **DETERMINATE** | 26 = 26 = 26 |
| 291 | medium | reddit | AAPL@1d | INDETERMINATE | 16 / 8 / 10 |
| 306 | hard | stackexchange | AAPL@1m | INDETERMINATE | 0 valid³ |
| 309 | medium | stackexchange | AAPL@5m | INDETERMINATE | 355 = 355 / 364 |
| 311 | medium | stackexchange | AAPL@5m | INDETERMINATE | 1 / 2 / 494⁴ |
| 388 | medium | tradingview | AAPL@5m | **DETERMINATE** | 90 = 90 = 90 |
| 392 | hard | tradingview | AAPL@1h | not determinate⁵ | no valid refs |

¹ third reference: CLI infrastructure failure (0-byte/timeout), excluded as
non-evidence; verdict rests on 2 conclusively divergent faithful refs.
² one reference crashed on a backtrader API error (`MACD(period1=…)` is not a valid
kwarg) in dead or setup code — implementation error, excluded; ≥2 survivors decide.
³ all three references crashed identically at `import hmmlearn` (see capsule).
⁴ verdict issued after an executed diagnostic repair round — see capsule.
⁵ reference-production-failed after five attempts; counted in the denominator as
not-determinate (sensitivity: excluding it entirely gives 3/19 = 15.8%).
\* fill-count ties that are **not** tape ties — trades differ in time or side even
where counts agree (tasks 97, 129, 131, 172).

**Metric 1 = 3/20 = 15.0% (Wilson 95% CI 5.2%–36.0%).**

### 4.2 Ambiguity taxonomy (16 INDETERMINATE tasks, adjudicated)

| class | tasks | share |
|---|---|---|
| unpinned-exit | 13 | 81% |
| unpinned-entry-trigger | 13 | 81% |
| unpinned-sizing | 11 | 69% |
| unpinned-indicator-params | 6 | 38% |
| timeframe-mismatch | 5 | 31% |
| external-data-required | 4 | 25% |
| other (infeasible method / eval-protocol / truncated text) | 4 | 25% |
| multi-asset-required | 2 | 13% |
| goal-directed · orphaned-price-levels | 0 | — |

Recurring mechanisms, each adjudicated with quoted text (full capsules in
Appendix A):

- **Undefined chart-pattern geometry.** "Neckline", "cup and handle", "FVG",
  "order block", "3 consecutive lower highs and lower lows" — chartist vocabulary
  with no computable definition. Task 129's two opus references differ by *eight
  months* on the first entry depending on whether a "low" is a bar extreme or a
  swing pivot.
- **Pinned levels, unpinned mechanics.** Task 309 pins "a 2% hard stop-loss from
  entry on every trade" — but a resting stop order fills intrabar at the stop price
  while breach-detection-in-`next()` fills at the next bar's open. Eleven genuine
  stop events on the frozen data separate the two faithful readings. Task 311's
  spec even *licenses both* readings explicitly ("Execute stop exits as stop orders
  updated each bar (or equivalent logic in next())") — the disjunction itself is
  the indeterminacy.
- **Example-hedged parameters.** "For example, 100% of available capital" (97),
  "e.g., 1% or 2% per trade" (129), "an adjustable multiple (atr_mult)" (388) —
  the spec's own hedging words hand the implementer a free knob.
- **Sizing that interacts with the data binding.** Task 44's "1% of total trading
  capital" is ~$100 ≈ 0 whole AAPL shares — one reference's integer rounding
  killed its tape after 9 fills while fractional-sizing references traded for
  years. Task 291's 2% sizing floors to 0 shares once AAPL passes $200, silently
  deleting a trade — sizing reached the primary key.
- **Infeasibility under the binding** (overlaps F2): task 113 is a multi-asset
  portfolio optimization with a factor covariance model — bound to a single AAPL
  feed; task 68 delegates all entries to an LSTM over "62 independent features" —
  no weights, no features, no trainability in a backtrader-only harness; task 306
  *names its dependency verbatim* ("using hmmlearn") and all three faithful
  references crashed identically at import; task 131 requires NVDA prices and an
  earnings calendar on an ES=F-only feed. These tasks are not underspecified so
  much as **unimplementable as bound** — yet they sit in the benchmark being
  "passed" by whatever simplification the judge accepts.
- **Non-single-backtest evaluation protocols.** Task 187 demands a 50-run
  unseeded Monte-Carlo evaluation — there is no single-tape reading of it in a
  single-backtest harness at all; one faithful reference ran the whole protocol
  arithmetically in `stop()` and placed zero broker orders.

### 4.3 The three determinate tasks are the audit's positive controls

- **Task 249** (synthetic, AAPL@1d): SMA(9/26/52) "Ichimoku-style" momentum. The
  spec pins entry ("at the bar close, with the closing price above both averages
  … and SMA(26) > SMA(52)"), both exit legs ("the reverse cross … or when the
  price closes below the lower of SMA(26) and SMA(52)"), and explicitly negates
  the rest: "Stop-loss and take-profit are not used. All signals are confirmed at
  the bar close." All three cross-model references — with three *different* sizing
  mechanisms — produced identical 26-fill tapes.
- **Task 388** (tradingview, AAPL@5m): Williams %R/Momentum long-short. The spec
  pins its crossings operationally ("previous bar <= -80 and current bar > -80")
  and its stop formula. 3/3 exact convergence at 90 fills — with one disclosed
  fragility: the stop multiple is named but never valued ("an adjustable multiple
  (atr_mult)"); all three references chose the conventional 2.0. A sensitivity run
  shows 1.5 ⇒ 100 fills, 3.0 ⇒ 84 — the convergence is partly convention-borne,
  exactly as the static screen warned.
- **Task 59** (reddit, AAPL@5m): 30-minute aggregation of 5-minute bars with
  SMA-cross counting and RSI averaging. Pins its aggregation arithmetic
  per-condition ("The number of times the fast SMA(13) crossed the slow SMA(40)
  upward during these 30 minutes (based on 5-minute data)"). 2/3 exact convergence
  at 14 fills (the sonnet reference crashed on a backtrader API misuse in dead
  code — implementation error, excluded). Confidence: medium (both survivors are
  opus).

Two lessons: (i) determinacy **is achievable in this benchmark's own format** —
specs converge when they pin parameters numerically and state their tie-breakers
and negations; (ii) the audit's instrument is not too strict to ever pass a task —
when the text pins behavior, three independent implementations across two model
families land on one tape. Convergence is also visible *within* indeterminate
tasks: task 47's references converged exactly on everything its spec did pin (1%
risk sizing, partial-TP structure) and diverged only on the unpinned concepts, and
tasks 66/113's references agree on the pinned first entry before scattering.

### 4.4 Cross-checks

- **Static screen vs tapes:** 19/20 predicted indeterminate; of 19 tape-measured
  tasks the screen was directionally right on 17 and wrong in both directions
  (59: predicted indeterminate, converged; 388: predicted indeterminate on the
  atr_mult knob, converged by convention). Empirical tapes, not predictions,
  define the metric — the screen's misses are why.
- **Difficulty labels don't track specification quality:** determinate by their
  own labels — easy 0/10, medium 3/6, hard 0/4. The benchmark's "easy" tier
  (casual Reddit prose) is its least gradable.

## 5. Q2 — Judge false-pass rate: 9/10 = 90.0% [59.6%–98.2%]

### 5.1 Result table (12 candidates, benchmark's own pipeline, on the 3 determinate tasks)

| candidate | gates | judge | tape vs reference | verdict |
|---|---|---|---|---|
| 59 · sonnet#0 | pass | **pass** | 12 vs 14 fills; 1-share stake vs all-in; entries 14:00 vs 14:05 | **false-pass** |
| 59 · sonnet#1 | pass | **pass** | 238 vs 14; exits dribble ~33 one-share sells over 3 h | **false-pass** |
| 59 · haiku#0 | pass | **pass** | 16 vs 14; drops the 30-min aggregation entirely; holds 30 min vs 3 h | **false-pass** |
| 59 · haiku#1 | pass | **pass** | 8 vs 14; window phase-shifted; SL/TP can never fire | **false-pass** |
| 249 · sonnet#0 | pass | **pass** | 279 vs 26; 89-share positions unwound one share/day, never fully close | **false-pass** |
| 249 · sonnet#1 | pass | pass | **26 vs 26 — exact primary-key match** (sizes differ) | true pass |
| 249 · haiku#0 | pass | **pass** | 30 vs 26; 1-share stake lets two margin-rejected entries fill | **false-pass** |
| 249 · haiku#1 | pass | **pass** | 30 vs 26; same mechanism | **false-pass** |
| 388 · sonnet#0 | pass | **pass** | 86 vs 90; %R proxied via Stochastic; close-based stop | **false-pass** |
| 388 · sonnet#1 | pass | **pass** | 102 vs 90; required Momentum filter swapped for RSI | **false-pass** |
| 388 · haiku#0 | pass | fail | 171 vs 90; %R→RSI 30/70, momentum→1-bar change | true fail |
| 388 · haiku#1 | pass | fail | 106 vs 90; %R→Stochastic 20/80 + RSI filter | true fail |

- **False-pass rate (primary key): 9/10 = 90.0% [59.6%–98.2%].** Per model:
  sonnet 5/6, haiku 4/4. Per task: 59 → 4/4, 249 → 3/4, 388 → 2/2.
- **Secondary key** (timestamp, side, size): **10/10 = 100% [72.2%–100%]** — the
  single primary-key match still differs in share sizes.
- **False-fail rate: 0/2** — both rejections were genuinely wrong code. On this
  sample the judge is a one-sided instrument: it never blocks correct work; it
  waves through incorrect work.
- **Stability: 0/30 verdict flips** on re-judging 10 candidates ×3. The 90% is the
  instrument's systematic behavior, not sampling noise.
- **The execution gates filter nothing here:** 12/12 candidates passed all three.
  On determinate tasks the judge is the benchmark's *only* semantic instrument —
  and it approved 10 of the 12 codes shown to it.

### 5.2 The judge in its own words

The most revealing false-passes are the ones where the judge *sees* the deviation
and passes anyway — exactly as its rubric instructs:

> Task 59, haiku#0 (no 30-minute aggregation at all; holds 30 minutes instead of
> 3 hours): *"These are real deviations from the spec, but given Backtrader's
> complexity in implementing intra-bar sub-sampling and rolling window aggregation
> natively, they qualify as reasonable simplifications of the same underlying
> logic. Rating: [[1]]"* — the aggregation is implementable; two reference
> implementations did it and converged.

> Task 388, sonnet#1 (required Momentum filter replaced with RSI): *"Momentum is a
> directly available built-in in Backtrader, so this is not a justified
> simplification. … The substitution of RSI for Momentum degrades signal accuracy
> but does not invert or abandon the strategy's main idea. … Rating: [[1]]"* — the
> judge documents that the deviation is unjustified, then passes it.

> Task 249, sonnet#0 (89-share positions exited one share per day; 279 fills vs
> 26; position never fully closes): *"The code is directly and fully relevant to
> the assignment — every condition described in the strategy specification is
> explicitly implemented with no deviations or omissions. … Rating: [[1]]"* — the
> judge reads intent in the code text; it cannot see that the exit orders are
> unsized and the tape is unrecognizable.

The task-249 haiku pair shows the subtlest failure mode: their signal logic is
*correct*, but a default 1-share stake means two entries that the reference's
all-in orders had margin-rejected now fill — the tape gains two round trips the
spec'd strategy never takes. Correct-looking code, wrong behavior, invisible to a
text-reading judge.

## 6. Structural findings (verified from source or empirically)

**F1 — No ground truth exists anywhere in the pipeline.** Scoring is structure
regex → unsandboxed execution → ≥1 trade → a judge designed lenient (§2), with
exception ⇒ pass and keyword fallbacks. Computed returns are never scored. The
generation prompt mandates simplification of complex tasks.

**F2 — The benchmark's graded data is overwhelmingly concentrated on AAPL, and
some tasks state conditions that cannot be evaluated on the data they bind.**
Binding is honest: a task that names an asset is bound to that asset where the
pipeline can resolve it. The measured facts are concentration (31/40 of
sample_A and 15/20 of this sample graded on AAPL bars after binding) and
mismatch: tasks whose stated conditions cannot be evaluated on the bound data
at all — XAUUSD logic on GC=F bars (68), NVDA earnings conditions on an ES=F
feed (131), a multi-asset factor-model optimizer on one AAPL series (113).
*(Corrected 2026-08-13: an earlier revision of this finding claimed tasks are
graded on AAPL regardless of the asset named in the prose. That claim is false.
The paper retracts it in its section 6.3 ("binding is honest, concentration is
the finding") — the retraction is present in the drafts as of their 2026-07-17
last-modified date and was verified verbatim by the 2026-07-19 framing review.
This report's wording is now aligned.)*

**F3 — Benchmark data is non-reproducible by construction.** No cache ships;
intraday data is downloaded with *trailing* windows (1m: last 7 days; 5m/15m: 60;
1h: 730). Two runs on different days grade on different data; published scores
cannot be compared or reproduced. This audit froze and SHA256-hashed one snapshot
(2026-07-12) so all of its own numbers are replayable.

**F4 — The ≥1-trade gate is unpassable on BTC-USD tasks under the benchmark's own
conventions.** Verified: default sizing (the style of their shipped example)
completes zero orders — backtrader's default sizer buys 1 unit and 1 BTC
($58k–82k in the frozen window) exceeds the $10,000 cash, so every order is
rejected; the identical strategy with `size=0.01` completes 358 trades. Faithful
code fails the gate; only spontaneously invented fractional sizing passes.

**F5 — The execution stack contains silent traps that snared even frontier models
— invisibly to every gate.** Documented during adjudication:
(a) backtrader's broker notifies **cloned** order objects, so the natural guard
`if order is self.order:` never matches — on task 97, **3/3 references (opus ×2,
sonnet ×1) independently wrote this bug**, leaving stop-loss/take-profit code
silently dead and each strategy frozen after its first trade; the same bug
recurred in refs on tasks 129, 136, and 311.
(b) `broker.cancel()` silently no-ops on orders still in Submitted state — task
309's sonnet reference leaked six stale stop orders that later filled against
*different* trades at wrong prices.
(c) `bt.indicators.MACD(period1=…)` is not a valid constructor signature — two
references crashed on it.
All three failure modes produce code that reads as intended, runs, and trades ≥1
time: every benchmark gate passes them, and a text-reading judge cannot see them.
Candidate submissions in the benchmark's published leaderboards almost certainly
contain the same dead-risk-management pattern.

**F6 — Generated code's `__main__` blocks execute inside the harness.** The
wrapper runs candidates via `python -c`, so `__name__ == "__main__"`; the
benchmark's own format example ships a `__main__` block that performs a live
yfinance download. Execution is unsandboxed by design (their README acknowledges
subprocess isolation only).

**F7 — The execution stack is deterministic on frozen data.** Verified: identical
code ⇒ byte-identical fill tapes across repeated runs on all 8 frozen pairs. Exact
behavioral ground truth was always available to this benchmark at zero marginal
cost. It uses none of it.

## 7. Deviations and threats to validity

Four deviations, logged in full in [results/deviations.md](results/deviations.md):
task 47 measured on two references (third timed out; verdict already conclusive);
task 392 classified on reference-production failure after five attempts
(sensitivity: 3/19 = 15.8% excluding it — conclusion unchanged); judge model is
Sonnet-family (their README's endorsement) rather than their run script's gpt-5.4
pin; CLI cannot pin temperature (their 0.0/0.1) — mitigated by the 0/30-flip
stability result.

Threats and mitigations:

- **n = 20 tasks; metric 2's denominator is 10.** Wilson intervals are reported
  throughout; even the CI floors (5.2% determinacy ceiling-complement, 59.6%
  false-pass floor) support the conclusions. Metric 2's small n is *caused by*
  metric 1 — a benchmark with almost no gradable tasks cannot yield a large
  judged-against-truth sample. The coupling is the finding.
- **References are model-written.** Mitigated by: strict-fidelity prompting with
  declared assumptions; cross-model k = 3; bench-canonical defaults isolating
  spec-level ambiguity; per-task adjudication that quoted spec text, instrumented
  and re-executed references, and ran diagnostic repairs on every flagged defect
  (four tasks had confirmed reference bugs — in every case repair provably could
  not restore convergence, and in one case, task 311, the executed repair
  *converged the two buggy references with each other* while leaving the
  spec-licensed fork with the third intact).
- **Judge configuration differs from their run script** (model family, unpinned
  temperature). The replication preserves their prompt, gate order, parsing, and
  fallbacks verbatim; their README itself endorses a Claude Sonnet judge; verdicts
  were perfectly stable across repeats.
- **Single data snapshot.** Forced by F3 — their pipeline has no reproducible
  data. All audit numbers are replayable against the hashed snapshot.
- **Adjudication involves judgment.** Every verdict cites the spec sentence it
  rests on; all 20 notes are in `results/adjudication/` for independent review.

## 8. Conclusions

1. **QuantCode-Bench's headline metric — judge pass rate on executable strategies
   — is dominated by instrument leniency, not model capability.** 85% of its
   sampled tasks [64%–95%] admit no unique correct behavior; its judge passes
   behaviorally wrong code 90% of the time [60%–98%] where correctness is exactly
   checkable, and it does so deterministically.

2. **The failure is architectural and was avoidable.** The benchmark's own
   execution stack is deterministic (F7): shipping a reference implementation per
   task and comparing fill tapes would have produced an exact, judge-free
   correctness signal using machinery the benchmark already runs on every
   submission. Instead, correctness is delegated to a judge instructed to forgive,
   on tasks that mostly cannot be verified even in principle.

3. **Task curation, not model evaluation, is the binding constraint for NL-to-code
   trading benchmarks.** Scraped strategy prose is not a specification: 81% of
   indeterminate tasks have unpinned exits, 81% unpinned entries, 69% unpinned
   sizing, and several are outright unimplementable under the benchmark's own data
   bindings (F2) or dependency constraints (`hmmlearn`). The three tasks that do
   converge show the fix is achievable within the same format: numeric parameters,
   operational definitions of every trigger, explicit tie-breakers and negations —
   *pin → probe → build*.

4. **Execution gates are not semantic oracles.** All 12 wrong-or-right candidates
   passed all three gates; the gates also *reject faithful behavior* (a strict
   reading that legitimately never trades fails the ≥1-trade gate — tasks 146,
   172, 187 — and every unsized faithful strategy on BTC-USD fails it, F4) and
   *accept dead code* (F5's frozen strategies each traded once before freezing).

5. **For benchmark builders:** the audit's own protocol — k independent
   strict-fidelity implementations, exact tape convergence as the determinacy
   test, adjudication against quoted spec text — is a practical, automatable
   pre-flight for any execution-based codegen benchmark. A task that cannot pass
   it has no business being scored by any judge, human or LLM.

---

## Appendix A — Per-task adjudication capsules

Full notes with quoted text, per-reference analysis, and instrumentation logs:
`results/adjudication/<id>.md`.

**44 · ETF Trend-Following ATR Pullback (scale-in) — INDETERMINATE.** All 3 refs
faithful, 3 tapes (146/158/9). The scale-in anchor "from the next high" has no
determinate referent (in the spec's own falling-price scenario no new high forms):
frozen ladder vs reset-per-entry vs running max. "1% of total trading capital" is
< 1 AAPL share, so integer rounding kills one ref's tape after 9 fills while
fractional refs trade for years.

**47 · FVG Swing Failure Breakout — INDETERMINATE** (on n=2; third ref was CLI
infrastructure failure). Divergent from the first entry (25 vs 2 fills). "The body
of the last strong candle before a sharp price move" leaves "strong" and "sharp"
undefined; the dual 4h+5m design collapses onto a single 5m feed. Where the spec
*did* pin behavior (1% risk, partial-TP structure, RR 3.33) the refs converged
exactly — the divergence is spec-level.

**59 · 30-min Aggregated SMA-Cross/RSI — DETERMINATE** (canonical 14-fill tape;
confidence medium: both survivors opus). Per-condition aggregation arithmetic is
pinned to 5-minute data explicitly. Third ref crashed on `MACD(period1=…)` (dead
code) — excluded as implementation error.

**66 · Double Bottom — INDETERMINATE.** All 3 agree on the pinned first BUY, then
split (9/7/19). "Close the position upon reaching a take-profit of 2:1" pins
neither touch nor close; the pattern's lows and "intermediate peak" have no pivot
window, pairing rule, or expiry. 23 distinct declared-assumption topics.

**68 · "AI Trading Strategy" (LSTM, XAU/USD) — INDETERMINATE.** Entry logic
delegated to an LSTM over "62 independent features" — no weights, features, or
trainability; every faithful ref must invent a proxy and each invented a different
one (1725 vs 2073 fills, opposite first trades). XAUUSD prose on GC=F data; news
blackout needs an absent calendar; task text truncates mid-sentence.

**97 · EMA Forecasting — INDETERMINATE.** All three refs independently hit the
clone-identity trap (F5a) — SL/TP dead, strategies frozen (a repaired ref has 795
fills vs the shipped 2). Diagnostic repair proves divergence survives: the EMA(50)
filter is only "can be added" (omitted ×2, included ×1 — different first-trade
direction and date), and "for example, 100% of available capital" left 95/98/100%
choices whose margin interactions alone split repaired tapes (795 vs 785).

**113 · Portfolio Optimization with Costs — INDETERMINATE** (7 classes). λ and Θ
never valued (the spec hands them over: "Use this parameter to control…"); the
objective is internally contradictory between entry formula and exit prose; I(t)
has no closed form; multi-asset covariance spec on a single AAPL feed; text
truncates mid-sentence. 543/254/74 fills, agreeing only on the day-1 entry.

**129 · Falling Channel Breakout — INDETERMINATE.** Identical entries and computed
TP/SL levels, different monitoring: intrabar touch (sells 2024-11-22) vs close
basis (2024-11-25). "3 consecutive lower highs and lower lows" never defines a
high/low — swing-pivot reading enters eight months earlier. Third ref's exit code
dead via F5a (repair moot). Spec's H4 timeframe unsatisfiable under the 1h binding.

**131 · NVDA Pre-Earnings Momentum Breakout — INDETERMINATE.** The alternative
exit is an example ("for example, formation of a bearish candlestick pattern on
increased volume") — engulfing vs any-bearish readings split the opus pair;
"increased volume" has no baseline; the SMA-200 filter is "(optional for
confirmation)"; the earnings blackout needs an absent calendar on the ES=F feed.

**136 · NVDA Resistance Breakout, EMA Trailing Stop — INDETERMINATE.** "Lagging by
a distance equal to the value of the 8-period EMA" is degenerate read literally
(≈$179 distance on a $180 stock — never fires) yet feeds the 2%-risk sizing
formula: 1 share (literal) vs 49 shares (stop-at-EMA) — and "Close 50% of the
position" of a spec-forced 1-share position pins no rounding (fractional 0.5 vs
skip), splitting even the literal-reading pair (17 vs 20 fills). Third ref
confirmed F5a violator (holds its single BUY forever through 32 TP-crossing bars).

**146 · Cup and Handle — INDETERMINATE.** Pinned rules implemented identically by
all three; the pattern detector is qualitative only (no tolerances for depth,
symmetry, pivots; "at least 1 year" budget; volume window "or another reasonable
period"). Three defensible detectors ⇒ 5 / 1 / 0 fills.

**172 · RSI Divergence + Breakout (SPT, "4H") — INDETERMINATE.** Divergence and
breakout have no validity window linking them; "previous local low" has no pivot
definition; stop mechanics fork exists only because a 4h strategy is bound to a 1h
feed (same trade, SELLs an hour apart); strict conjunction reading trades 0×.

**187 · Single-Asset Periodic Rebalancing — INDETERMINATE.** The evaluation
protocol itself ("Select 50 random start dates… run a separate backtest") has no
single-tape reading in a single-backtest harness; "weekly (resampling from daily
data if needed)" leaves week-boundary semantics open; "buy again with 100% of the
current portfolio value" is not literally executable under next-open fills plus
commission. 4 / 10 / 0 fills.

**249 · SMA "Ichimoku-style" Momentum — DETERMINATE** (canonical 26-fill tape,
3/3 cross-model). Fully pinned entries, exits, filters, timing, and negations. The
only residual is secondary-key: 51 vs 52 shares on one short from commission
reservation under "100% of available capital per trade".

**291 · Breakout Retest — INDETERMINATE.** Silent on overlapping breakouts inside
the 5-day retest window (restart vs anchor — one extra BUY); the two stop
sentences contradict each other (dynamic "closes below the 10-day EMA" vs fixed
"at the level of the 10-day EMA at the time of entry"); 2% sizing floors to 0
shares once AAPL passes $200, deleting a trade from the primary key. 16/8/10.

**306 · MACD + 2-State Gaussian HMM — INDETERMINATE** (infeasible dependency). The
spec verbatim mandates "a 2-state Gaussian HMM (using hmmlearn) trained on a
rolling window of the last 390 bars" — a library absent from the environment and
inexpressible under the benchmark's own 8-indicator whitelist; all three faithful
refs crashed identically at import. Even hypothetically, seed/covariance/EM-count/
decode-algorithm are all unpinned.

**309 · Z-Score Mean Reversion, 2% Hard Stop — INDETERMINATE.** The stop *level*
is pinned; the *mechanism* is not: resting stop (intrabar fill at stop price) vs
monitoring in `next()` (next-open fill) differ on 11 real stop events. One ref
additionally leaked un-cancellable Submitted stops (F5b; 6 stale fills) — repair
recorded, provably moot. The exact 355-fill convergence is opus-with-opus; the
cross-model ref sat on the other side of the mechanism fork.

**311 · SMA Cross + 3×ATR Ratcheting Trail — INDETERMINATE, after an executed
repair round.** Both opus refs shared an F5a guard bug (frozen at 1–2 fills,
contradicting explicit re-entry text); the adjudicator's repair converges them
*with each other* exactly (528 = 528) — but the spec's own disjunction ("Execute
stop exits as stop orders updated each bar (or equivalent logic in next())")
leaves them split from the third ref (494): a gapped resting stop fills at the
09:30 open, the `next()` check closes at 09:35. Both licensed; neither repairable.

**388 · Williams %R / Momentum, ATR Stop — DETERMINATE** (canonical 90-fill tape,
3/3 cross-model), with a disclosed fragility: "an adjustable multiple (atr_mult)"
is never valued; all three chose the conventional 2.0 (sensitivity: 1.5 ⇒ 100
fills, 3.0 ⇒ 84). Convergence is real but partly convention-borne — flagged as a
false-pass threat for faithful candidates choosing a different multiple.

**392 · Multi-Timeframe Composite (1D/4H/60m) — reference-production-failed.**
Five attempts: no-code output, mid-method-truncated output, 2×900s timeout, hung
retry, unstarted retry. The sprawling Supertrend+VPT+SMA stack across three
timeframes on a single 1h feed generated 15–20+ declared assumptions in the
partial outputs. Counted not-determinate (conservative); not counted in the
divergence taxonomy.

## Appendix B — Artifact inventory and reproduction

```
qcb_audit/
  PLAN.md                     pre-registered design (D1–D10 + D4a addendum)
  REPORT.md                   this report
  INTERIM_FINDINGS{,_v2,_v3}.md   point-in-time snapshots (v3 table has two
                                  difficulty-label errors; this report is correct)
  sample_20.json / sample_20_final.json   seeded draw + final task list
  select_sample.py / freeze_cache.py / extract_prompts.py / validate_tape.py
  tape_exec.py                tape-instrumented replica of their executor
  prompts/                    their verbatim system/user/judge prompts + ref prompt
  frozen_cache/               8 hashed pickles + cache_manifest.json
  driver/                     cli.py (hardened claude.exe harness), gates.py,
                              judge_repl.py, tape_compare.py, run_phase2.py,
                              run_phase3.py, retry_refs.py, collate_refs.py,
                              judge_stability.py, metrics.py, common.py
  results/
    ledger.jsonl              append-only run ledger (all batches resumable)
    refs/                     63 reference implementations + raw CLI outputs
    tapes/ref_{59,249,388}.json   canonical tapes
    gens/                     12 candidate records incl. judge texts
    adjudication/             20 adjudication notes with quoted spec text
    screen/                   20 static screens
    convergence_summary.json  metric1.json  metric2.json  judge_stability.json
    deviations.md
```

Reproduction order: `select_sample.py` → `extract_prompts.py` → `freeze_cache.py`
→ `validate_tape.py` → `driver/run_phase2.py` → `driver/collate_refs.py` →
adjudication → `driver/run_phase3.py` → `driver/judge_stability.py` →
`driver/metrics.py`. All LLM batches are idempotent against `results/ledger.jsonl`
and halt resumably on CLI session limits. Note that exact tape reproduction
requires the shipped `frozen_cache/` (F3: their data pipeline is trailing-window
and non-reproducible from scratch).

## Appendix C — Pre-registered ambiguity classes (PLAN.md D5)

`unpinned-sizing` (position size unstated or example-hedged) ·
`unpinned-indicator-params` (named indicator without parameters) ·
`unpinned-entry-trigger` (entry condition without an operational definition) ·
`unpinned-exit` (exit rule or its trigger/monitoring mechanics unstated) ·
`orphaned-price-levels` (hardcoded prices meaningless on the bound data — 0 hits;
the AAPL-binding damage surfaced through other classes instead) ·
`timeframe-mismatch` (prose timeframe unimplementable on the bound bars) ·
`goal-directed` (optimize-X with no unique trace — 0 hits in this sample) ·
`external-data-required` (needs data outside the single OHLCV feed) ·
`multi-asset-required` (needs more than the single bound feed) ·
`other` (infeasible method/dependency, non-single-backtest evaluation protocol,
truncated task text).


---

*ADDENDUM 2026-08-14: the registered secondary-key sensitivity (PLAN.md; keyed on timestamp, side, size) was computed during the 2026-07 reviews but never reported in this document: metric 1 under the secondary key is 2/20 = 10.0% (Wilson 2.8-30.1); the flipped task is 249, via a 51-vs-52-share residual at 2 of 26 fills. Reported here for completeness; the primary-key 3/20 remains the registered headline and this is not a registration deviation.*