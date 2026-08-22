> **Retraction pointer (added 2026-08-13):** this dated snapshot contains the claim that tasks are graded on AAPL regardless of the asset named in the prose. That claim was later retracted (binding is honest, concentration is the finding) - see REPORT.md finding F2 and its correction note. The snapshot below is otherwise preserved as written.

# QuantCode-Bench Audit â€” Interim Findings v3

**Status as of 2026-07-12 ~12:45:** empirical convergence data in for **15 of 20
tasks** (46/60 reference implementations complete; batch running on the last 5
tasks). Supersedes v2. Structural findings F1â€“F5 unchanged (Â§4). Design:
[PLAN.md](PLAN.md), pre-registered. Raw evidence: `results/convergence_summary.json`,
`results/refs/`, `results/screen/`.

---

## 1. Headline: 13 of 15 measured tasks admit no determinate reference implementation â€” and the 2 that do prove the method works

Protocol (PLAN.md D4/D4a): three independent strict-fidelity reference
implementations per task (opus Ã—2, sonnet Ã—1; fresh CLI contexts; bench-canonical
environment defaults fixed; every forced choice declared), executed on frozen data
through a verified replica of the bench's wrapper. Determinate â‡” surviving
implementations produce the **exact same fill tape** (ordered timestamp+side).

| task | difficulty | proposal | refs ok | tape groups | fills per group |
|---|---|---|---|---|---|
| 44 | easy | DIVERGED | 3/3 | 3 | 146 / 158 / 9 |
| 47 | hard | DIVERGED | 2/2Â¹ | 2 | 25 / 2 |
| 59 | medium | **CONVERGED** | 2/3Â² | 1 | 14 |
| 66 | medium | DIVERGED | 3/3 | 3 | 9 / 7 / 19 |
| 68 | hard | DIVERGED | 2/3Â² | 2 | 1725 / 2073 |
| 97 | easy | DIVERGED | 3/3 | 3 | 2 / 1 / 2 |
| 113 | hard | DIVERGED | 3/3 | 3 | 543 / 254 / 74 |
| 129 | medium | DIVERGED | 3/3 | 3 | 6 / 6 / 1 |
| 131 | hard | DIVERGED | 3/3 | 3 | 6 / 6 / 2 |
| 136 | easy | DIVERGED | 3/3 | 3 | 17 / 20 / 1 |
| 146 | medium | DIVERGED | 3/3 | 3 | 5 / 1 / 0 |
| 172 | easy | DIVERGED | 3/3 | 3 | 2 / 2 / 0 |
| 187 | easy | DIVERGED | 3/3 | 3 | 4 / 10 / 0 |
| 249 | easy | **CONVERGED** | 3/3 | 1 | 26 |
| 291 | medium | DIVERGED | 2/2Â¹ | 2 | 16 / 8 |

Â¹ third reference pending. Â² one sonnet reference crashed at execution; â‰¥2 survivors
satisfy the protocol. Tasks 306, 309, 311, 388, 392 still in the batch.
Classifications are pre-adjudication proposals (final metric 1 comes after the
cited-spec-text adjudication pass over all 20).

**Task 249 is the audit's positive control, delivered by the bench itself.** Its spec
pins everything â€” numeric SMA(9/26/52) rules, entry "at the bar close, with the
closing price above both averages", both exit legs, and explicitly "Stop-loss and
take-profit are not used." All three references â€” including the cross-model sonnet
one â€” produced the **identical 26-fill tape**. Determinacy is achievable in this
bench's own format; 13 of 15 tasks just don't achieve it. (It was also the only task
of 20 the static screen predicted determinate.)

New divergence shapes since v2:

- **"Never fires" vs "fires often":** on tasks 146, 172, and 187 the strict sonnet
  reference legitimately traded **zero** times while opus references traded 1â€“10
  times â€” the starkest possible behavioral disagreement, and one their â‰¥1-trade gate
  would silently misread as a broken submission.
- **Count-match â‰  behavior-match** persists: tasks 97, 129, 131, 172 each contain
  two references agreeing on fill count but not on the actual (timestamp, side)
  tape.
- Divergence magnitudes remain enormous: 9â†’158 (task 44), 74â†’543 (113), 1725â†’2073 (68).

Running tally: determinacy proposals 2/15 (â‰ˆ13%); screen-vs-empirical agreement
14/15 (the screen's one miss, task 59, converged â€” the empirical test overrides
prediction in both directions).

## 2. Why tasks diverge: the implementers' own declared assumptions

References declared ~15â€“35 forced choices per task. Recurring classes (verbatim
topics from `results/refs/`): undefined pattern geometry ("neckline definition",
"which lows form the pattern", "FVG definition", "MSS (bullish)", "cup U-shape
quantification"); unpinned exits ("exit priority within a bar", "take-profit
reference (multi-entry)", "trailing stop comparison price"); unpinned entries
("recent high definition", "'price has started to recover' criterion"); sizing/risk
conflation ("position sizing / fractional shares" â€” task 44's 1%-of-capital â‰ˆ $100
rounds to 0 AAPL shares much of 2020â€“2025); and **infeasibility under the bench's
data binding**: task 113 (multi-asset portfolio optimization with factor covariance
and sector constraints) is bound to a single AAPL feed; task 68 (XAUUSD strategy
requiring an LSTM and a news calendar) is bound to GC=F bars; task 131 (ES-futures
strategy with NVDA price/earnings cross-conditions) has no NVDA data and no earnings
calendar.

## 3. The judge angle (metric 2 preview)

Task 44's candidate under the bench's own lenient prompt traded 3 times and passed
their judge with "Rating: [[1]]" â€” faithful implementations of the same text trade
9, 146, or 158 times. Their judge design (verbatim from source): "Be LENIENT with
simplifications", score 0 only if code "COMPLETELY DOES NOT COMPLY", pass on judge
exception, keyword-grep fallback; the generation prompt itself instructs "If task is
complex, SIMPLIFY it". Metric 2 (false-pass rate vs exact tapes) runs on the
determinate set once adjudication closes; with determinacy trending â‰ˆ2/20, its
denominator will be small â€” the load-bearing number is metric 1, and the correct
framing is: **a benchmark whose tasks admit no exact ground truth cannot support a
correctness judge**, demonstrated at tape level in Â§1.

## 4. Structural findings (verified; unchanged from v1/v2)

1. **No ground truth in their pipeline** â€” structure regex â†’ unsandboxed execution â†’
   â‰¥1 trade â†’ lenient binary LLM judge (exception â‡’ pass; keyword fallback). Returns
   computed but never scored.
2. **360/400 tasks graded on AAPL bars** regardless of the asset in the prose; Â§2
   shows tasks that are unevaluable as stated because of it.
3. **Non-reproducible data by construction** (no shipped cache; trailing intraday
   windows). This audit froze + hashed its snapshot (2026-07-12).
4. **â‰¥1-trade gate unpassable on BTC-USD tasks** with bench-canonical default
   sizing (verified: 0 fills default vs 358 with size=0.01).
5. **`__main__` blocks execute inside their harness** (their own example ships one
   with a live download); unsandboxed by design. Stack is deterministic on frozen
   data (verified) â€” exact ground truth was possible; unused.

## 5. Remaining work

Last 5 tasks' references (~15 calls) + retry of one CLI-timeout (task 47 ref2);
adjudication over all 20 with cited spec text (repair round where implementations
contradict explicit text) â†’ final metric 1 + Wilson CI; Phase 3 (their exact
pipeline: sonnet Ã—2 + haiku Ã—2 per determinate task, their gates, their judge
verbatim) â†’ metric 2; final REPORT.md.

## 6. Threats to validity

n=20; two tasks currently on 2-reference evidence; model-written references
(mitigated: strict-fidelity prompt, cross-model k=3, declared assumptions,
adjudication + repair round); single frozen snapshot (their design forces it);
Sonnet-family judge (their README's endorsed family) instead of their run-script's
gpt-5.4 pin; CLI cannot pin temperature. The task-249 cross-model convergence is the
strongest available answer to "maybe strict-fidelity prompting just can't converge":
it can, when the spec permits it.
