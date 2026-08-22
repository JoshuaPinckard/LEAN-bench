> **Retraction pointer (added 2026-08-13):** this dated snapshot contains the claim that tasks are graded on AAPL regardless of the asset named in the prose. That claim was later retracted (binding is honest, concentration is the finding) - see REPORT.md finding F2 and its correction note. The snapshot below is otherwise preserved as written.

# QuantCode-Bench Audit â€” Interim Findings v2

**Status as of 2026-07-12 ~12:20:** Phase 2 empirical convergence data is now in for
**11 of 20 tasks** (31/60 reference implementations complete; batch still running).
This supersedes [INTERIM_FINDINGS.md](INTERIM_FINDINGS.md) (v1); v1's structural
findings F1â€“F5 are unchanged and restated in Â§4. Design: [PLAN.md](PLAN.md),
pre-registered. Raw evidence: `results/convergence_summary.json`,
`results/refs/task*_ref*.json`, `results/screen/*.json`.

---

## 1. Headline preliminary result: 10 of 11 measured tasks have no determinate reference implementation

Protocol (PLAN.md D4/D4a): per task, three independent strict-fidelity reference
implementations (opus Ã—2, sonnet Ã—1; fresh CLI context each; bench-canonical
environment defaults fixed; every forced choice declared), executed on frozen data
through a verified replica of the bench's own wrapper. A task is determinate only if
the surviving implementations produce the **exact same fill tape** (ordered
timestamp+side sequence).

| task | difficulty | proposal | successful refs | tape groups | fills per group |
|---|---|---|---|---|---|
| 44 | easy | **DIVERGED** | 3/3 | 3 | 146 / 158 / 9 |
| 47 | hard | **DIVERGED** | 2/2Â¹ | 2 | 25 / 2 |
| 59 | medium | **CONVERGED** | 2/3Â² | 1 | 14 |
| 66 | medium | **DIVERGED** | 3/3 | 3 | 9 / 7 / 19 |
| 68 | hard | **DIVERGED** | 2/3Â² | 2 | 1725 / 2073 |
| 97 | easy | **DIVERGED** | 3/3 | 3 | 2 / 1 / 2 |
| 113 | hard | **DIVERGED** | 3/3 | 3 | 543 / 254 / 74 |
| 129 | medium | **DIVERGED** | 3/3 | 3 | 6 / 6 / 1 |
| 131 | hard | **DIVERGED** | 3/3 | 3 | 6 / 6 / 2 |
| 136 | easy | **DIVERGED** | 3/3 | 3 | 17 / 20 / 1 |
| 146 | medium | **DIVERGED** | 2/2Â¹ | 2 | 5 / 1 |

Â¹ third reference still pending (one CLI timeout to retry; batch in flight).
Â² one sonnet reference crashed at execution; â‰¥2 survivors satisfy the protocol.

Nine tasks (172, 187, 249, 291, 306, 309, 311, 388, 392) await their references.
Classifications are **pre-adjudication proposals**: per the pre-registered rule, a
divergence only becomes INDETERMINATE if it traces to an unpinned spec choice rather
than an implementation error contradicting explicit spec text (those get one repair
round). The declared-assumptions evidence in Â§2 makes wholesale reversals unlikely,
but final metric-1 numbers come after adjudication of all 20.

Three details worth quoting:

- **Fill-count agreement is not behavior agreement.** Tasks 97 (2/1/2 fills), 129
  (6/6/1), and 131 (6/6/2) each split into **three** distinct tape groups â€” even the
  references that agree on how *many* trades disagree on *which* trades. Coarse
  statistics would mask this; exact tapes don't.
- **Divergence magnitude is enormous.** Same spec, same fidelity instructions: task
  44 spans 9â†’158 fills; task 113 spans 74â†’543; task 68 spans 1725â†’2073.
- **The judge cannot see any of this.** Task 44's bench-prompt candidate (sonnet)
  traded 3 times and passed their judge with "Rating: [[1]]" â€” while faithful
  implementations of the same text trade 9, 146, or 158 times.

The one convergence (task 59) is instructive in the other direction: the static
screen had predicted it indeterminate, but its two surviving references produced
byte-identical 14-fill tapes â€” the empirical test overrides analyst prediction in
both directions, which is exactly why the metric is defined on tapes, not opinions.

## 2. Why they diverge: the implementers' own declared assumptions

Each reference implementation declared every choice the spec forced it to make.
Across the 11 measured tasks, references declared roughly **15â€“35 forced choices per
task**. Recurring classes (verbatim topics from `results/refs/`):

- **Undefined pattern geometry**: "neckline definition", "which lows form the
  pattern", "cup U-shape quantification", "FVG definition", "MSS (bullish)", "order
  block", "swing detection" â€” chart-pattern language with no computable definition.
- **Unpinned exits**: "exit priority within a bar", "take-profit reference
  (multi-entry)", "trailing stop comparison price", "same-bar take-profits",
  "stop_tp_trigger_price".
- **Unpinned entries**: "recent high definition", "breakout definition", "'price has
  started to recover' criterion", "crossover interpretation".
- **Sizing/risk conflation**: "position sizing / fractional shares", "risk
  percentage", "4% total risk cap" (task 44 demands 1%-of-capital positions â‰ˆ $100 â€”
  which rounds to 0 AAPL shares much of 2020â€“2025).
- **Outright infeasibility under the bench's binding** (marked "infeasible" by the
  implementers): task 113 is a multi-asset **portfolio optimization** with a factor
  covariance model, sector constraints, and an impact-cost term â€” bound to a single
  AAPL feed; task 68 is an **XAUUSD** strategy requiring an **LSTM model** and a
  news-blackout calendar â€” bound to GC=F futures bars; task 131 is an ES-futures
  strategy requiring **NVDA** price/earnings cross-conditions â€” bound to the single
  ES=F feed with no NVDA data and no earnings calendar.

That last class is the AAPL-substitution finding (F1) biting in practice: the bench
publishes tasks whose stated conditions cannot even be *evaluated* against the data
it grades on.

## 3. Static screen (complete, 20/20) vs empirical outcomes so far

Twenty rubric-based analyst screens predicted **19/20 INDETERMINATE** (sole
exception: task 249, whose spec pins everything numerically and even states
"Stop-loss and take-profit are not used"). Predicted ambiguity class counts:
unpinned-exit 19, unpinned-entry-trigger 16, unpinned-sizing 11,
unpinned-indicator-params 8, timeframe-mismatch 5, external-data-required 4,
multi-asset-required 3, goal-directed 0.

Against the 11 empirical outcomes so far the screen is directionally right on 10
(all DIVERGED were predicted indeterminate) and wrong on one (59: predicted
indeterminate, converged). Task 249's references are still pending â€” if any task
converges cleanly, it should be that one.

## 4. Structural findings (unchanged from v1, all source- or empirically-verified)

1. **No ground truth in their pipeline** â€” grading is structure-regex â†’ unsandboxed
   execution â†’ â‰¥1 trade â†’ an LLM judge instructed to "Be LENIENT", to score 0 only
   for code that "COMPLETELY DOES NOT COMPLY", to **pass** candidates when the judge
   call errors, with a keyword-grep fallback. Returns are computed but never scored.
   The generation prompt itself instructs "If task is complex, SIMPLIFY it".
2. **360/400 tasks are graded on AAPL data** regardless of the asset in the prose
   (31/40 in sample_A); Â§2 shows this makes some tasks unevaluable as stated.
3. **Data is non-reproducible by construction** â€” no shipped cache; trailing
   download windows (1m: 7d, 5m/15m: 60d, 1h: 730d). This audit froze and hashed one
   snapshot (2026-07-12).
4. **The â‰¥1-trade gate is unpassable on BTC-USD tasks** with the bench's own default
   sizing conventions (verified: 0 fills with default sizer, 358 with `size=0.01` â€”
   $10k cash cannot buy 1 BTC).
5. **`__main__` blocks in generated code execute inside their harness** (their own
   format example ships one performing a live network download); execution is
   unsandboxed by design. The stack **is** deterministic on frozen data (verified) â€”
   exact ground truth was possible; the bench doesn't use it.

## 5. What remains

- ~29 reference implementations (9 untouched tasks + stragglers), then one automatic
  retry pass for the CLI-timeout case (task 47 ref2) â€” batch is resumable by ledger.
- Adjudication of all 20 tasks with cited spec text (repair round where an
  implementation contradicts explicit text) â†’ final metric 1 with Wilson CI.
- Phase 3 on the determinate set (their exact pipeline: sonnet Ã—2 + haiku Ã—2 per
  task, their gates, their judge verbatim) â†’ metric 2. **Expected-size caveat:** with
  determinacy trending near 1â€“2 tasks of 20, metric 2's denominator will be small;
  the informative framing is metric 1 itself â€” a benchmark whose tasks
  overwhelmingly admit no exact ground truth cannot support a correctness judge, and
  its judge demonstrably passes behaviorally divergent implementations (Â§1).

## 6. Threats to validity (current)

n=20 tasks; 2 tasks currently proposed on 2-reference evidence (third pending);
reference implementations are model-written (mitigated: strict-fidelity prompt,
cross-model k=3, declared assumptions, adjudication with cited spec text and a repair
round); static screen is advisory only; single frozen data snapshot (forced by their
design); judge replication uses a Sonnet judge (their README's endorsed family)
rather than the gpt-5.4 their run-script pins, and the CLI cannot pin temperature.
