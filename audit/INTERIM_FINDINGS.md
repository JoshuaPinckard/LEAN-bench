> **Retraction pointer (added 2026-08-13):** this dated snapshot contains the claim that tasks are graded on AAPL regardless of the asset named in the prose. That claim was later retracted (binding is honest, concentration is the finding) - see REPORT.md finding F2 and its correction note. The snapshot below is otherwise preserved as written.

# QuantCode-Bench Audit â€” Interim Findings

**Status as of 2026-07-12:** Phase 1 (infrastructure, data freeze, verification) complete.
Phase 2 static screen complete (20/20 tasks). Phase 2 reference batch running (3/60
reference implementations done). Headline metrics not yet computed â€” everything below
is either verified from their source code, verified empirically on the frozen data, or
labeled as prediction.

Audit design: [PLAN.md](PLAN.md) (pre-registered before any model runs). Sample: 20
tasks drawn seed=20260712, stratified 10 easy / 6 medium / 4 hard from the 40-task
`sample_A.json`; final IDs 44, 47, 59, 66, 68, 97, 113, 129, 131, 136, 146, 172, 187,
249, 291, 306, 309, 311, 388, 392 (zero data-availability swaps). All LLM calls run
over the claude CLI; market data frozen and SHA256-hashed
(`frozen_cache/cache_manifest.json`, built 2026-07-12).

---

## 1. What QuantCode-Bench actually grades (verified from source)

QuantCode-Bench (LimexAILab, 400 tasks) asks a model to turn a natural-language
strategy description (sourced Reddit 183 / TradingView 100 / StackExchange 90 /
GitHub 19 / synthetic 8) into one self-contained Backtrader `bt.Strategy` class.
Scoring is four binary gates (`reward.py`):

1. **Structure**: regex for `import backtrader`, a `bt.Strategy` subclass, `def next(self)`.
2. **Execution**: the code runs on a pickled yfinance DataFrame (cash $10,000,
   commission 0.001, single feed) in an unsandboxed subprocess.
3. **Activity**: at least one completed trade.
4. **LLM judge**: binary, single call.

**There is no ground truth anywhere in the pipeline.** No reference implementations,
no expected trades, no expected P&L. `total_return` is computed and recorded in
metadata but never used for scoring. The only shipped code artifact is one format
example (`examples/sma_crossover.py`).

The judge is lenient **by explicit design** (verbatim from `judge.py`):

- "IMPORTANT: Be LENIENT with simplifications."
- "Simplifying to SMA/StdDev for Z-score is ACCEPTABLE."
- Score 0 only if the code "COMPLETELY DOES NOT COMPLY (ignores the main idea)."
- If the judge API call throws, the candidate **passes** (`reward.py`: "Don't
  penalize for judge failures").
- If no rating is parsed, a positive-vs-negative keyword count over the last 300
  characters decides; if no judge endpoint exists at all, a keyword grep of the code
  for indicator names (sma/ema/rsi/macd/bollinger/vix) decides.

The generation-side system prompt also instructs: "If task is complex, SIMPLIFY it to
use only available indicators" â€” the bench *tells* the model to deviate from the spec,
then grades it with a judge told to accept deviations.

## 2. Structural findings (each verified empirically in this audit)

**F1 â€” Most tasks are graded on the wrong asset's data.** 360/400 tasks (31/40 in
sample_A) are bound to AAPL bars regardless of the asset the prose describes: gold,
BTC, forex, and named-stock strategies all execute against AAPL unless the binding
file says otherwise. Any price level, volatility regime, or session logic in the
prose is evaluated against an unrelated series.

**F2 â€” Benchmark data is non-reproducible by construction.** No data cache ships with
the repo. Their build script downloads *trailing* windows for intraday data (1m: last
7 days; 5m/15m: last 60 days; 1h: last 730 days). Two runs on different days grade on
different data; published scores cannot be compared or reproduced. (This audit froze
and hashed one snapshot, 2026-07-12.)

**F3 â€” The â‰¥1-trade gate is unpassable on BTC-USD tasks with the bench's own
conventions.** Verified: an SMA-crossover with default sizing (the style of their own
shipped example) completes **zero** orders on their BTC-USD data â€” backtrader's
default sizer buys 1 unit, and 1 BTC ($58kâ€“82k in the frozen window) exceeds the
$10,000 cash, so every order is rejected. The identical strategy with `size=0.01`
completes 358 trades. A model is silently required to invent fractional sizing the
task never states; a faithful implementation fails their gate 3.

**F4 â€” Generated code's `__main__` blocks execute inside the harness.** Their wrapper
runs candidate code via `python -c`, where `__name__ == "__main__"`. Their own format
example ships a `__main__` block that performs a live yfinance download â€” code
following their example executes network calls during grading. (Related: execution is
unsandboxed by design.)

**F5 â€” The execution stack IS deterministic on frozen data.** Identical code produced
byte-identical fill tapes across repeated runs on all 8 frozen data pairs. This is
the one property that makes exact ground truth *possible* â€” the bench simply doesn't
use it.

## 3. Evidence on the two headline metrics (in progress)

**Metric 1 (determinacy) â€” static screen complete, prediction only.** Twenty
independent analysts scored each task against a pin rubric (entry trigger, exit,
indicator params, sizing, data-binding coherence, timeframe coherence), citing the
task's own phrasing. Result: **19/20 tasks predicted INDETERMINATE; 1/20 (task 249)
predicted DETERMINATE.** Predicted ambiguity classes across the 20 tasks:

| class | tasks affected |
|---|---|
| unpinned-exit | 19 |
| unpinned-entry-trigger | 16 |
| unpinned-sizing | 11 |
| unpinned-indicator-params | 8 |
| timeframe-mismatch | 5 |
| external-data-required | 4 |
| multi-asset-required | 3 |
| goal-directed | 0 |

Representative citation (task 44, easy): entry hinges on "a pullback equal to 1.5
ATR(14) from a recent high" with "recent high" undefined (no lookback, no swing
definition, no ATR anchor); take-profit "2.5 ATR(14) from the entry point" is
undefined once the spec's own scaling-in allows 4 entries. The sole
predicted-determinate task (249) pins everything numerically and even states
"Stop-loss and take-profit are not used. All signals are confirmed at the bar close."

These are predictions; the pre-registered decider is empirical â€” three independent
strict-fidelity reference implementations (opus Ã—2, sonnet Ã—1) per task must converge
to one fill tape (PLAN.md D4/D4a).

**First empirical convergence evidence agrees with the prediction.** Task 44's first
two reference implementations â€” same spec, same strict-fidelity prompt, same model
tier (opus) â€” produced **divergent tapes: 146 vs 158 fills**. Meanwhile the smoke-test
candidate for the same task (sonnet, under the bench's own lenient prompt) traded **3
times** â€” and **passed their judge** with "Rating: [[1]]" ("no deviation from the
assignment's main idea"). One task, three faithful-or-passing behaviors: 3, 146, and
158 trades. That is the entire pathology in miniature: the spec does not pin behavior,
and the judge cannot see behavior.

**Metric 2 (judge false-pass rate) â€” pending.** Requires the adjudicated determinate
set + canonical tapes (Phase 2 completion), then 4 candidates per determinate task
(sonnet Ã—2, haiku Ã—2) through their exact pipeline. NOTE: if the determinate set ends
up as small as the static screen predicts, metric 2's denominator will be small and
its confidence interval wide â€” that outcome is itself the finding (a benchmark whose
tasks mostly admit no exact ground truth cannot support a meaningful correctness
judge), and it is why metric 1 is reported first.

## 4. Audit-methodology notes for the draft

- Ground truth is defined **under the bench's own binding and environment** (AAPL
  substitution included): reference implementations run through a tape-instrumented
  replica of their exact wrapper (`tape_exec.py`; wrapper semantics verified
  line-for-line against `reward.py`, determinism verified empirically).
- Correctness key: ordered (fill-timestamp, side) sequence; sizes as sensitivity
  check (PLAN.md D3).
- Their judge is replicated verbatim (extracted prompt template, their parsing rules
  including the keyword fallback) over claude CLI with a Sonnet judge â€” their
  README's own endorsed judge family. Deviations logged: CLI cannot pin temperature
  (theirs: 0.0); their run-script pins gpt-5.4, unavailable without an API key.
- Also corrected during setup: the earlier scaffold's extracted system prompt was
  truncated (2,076 of 3,191 chars, missing the code example and output-format rules);
  the audit re-extracted it by importing their module.

## 5. Threats to validity (current)

n=20 tasks (Wilson CIs will be reported); static screen is LLM-analyst judgment
(mitigated: rubric pre-registered, spec text cited, and the final call is empirical
tape convergence, not the screen); reference implementations are model-written
(mitigated: strict-fidelity prompt, cross-model k=3, one cited-repair round,
assumptions declared); single frozen data snapshot (their design forces this â€” F2);
judge model is Sonnet-family rather than their run-script's gpt-5.4 pin.
