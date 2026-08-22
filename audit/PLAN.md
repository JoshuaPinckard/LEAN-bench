# QuantCode-Bench Head-to-Head Audit — Execution Plan

**Status:** pre-registered 2026-07-12, before any model runs.
**Deliverable:** two numbers over 20 QuantCode-Bench tasks:

1. **Determinacy rate** — fraction of tasks that admit a determinate reference
   implementation at all (a unique behavioral trace under the bench's own data
   binding and execution stack).
2. **Judge false-pass rate** — on determinate tasks, `P(candidate tape ≠ reference
   tape | their judge passes the candidate)`.

**Constraint:** all LLM calls (reference drafting, candidate generation, judging)
run over the claude CLI (subscription), never a raw API key. Backtests are local
subprocess executions of backtrader; yfinance data download is not an LLM call and
is permitted.

---

## Phase 0 — Pre-registered decisions (locked here, before any runs)

These are fixed now so results cannot be shaped post-hoc. Changing any of them
after Phase 2 starts must be logged in `results/deviations.md` with a reason.

**D1. Task selection.** 20 tasks drawn from the existing `sample_A.json` (40 tasks,
20 easy / 12 medium / 8 hard), stratified proportionally: **10 easy, 6 medium,
4 hard**. Draw: within each stratum sort by `id` ascending, then
`random.Random(20260712).sample(stratum, k)`. Script `select_sample.py` commits the
draw to `sample_20.json` with a SHA256 of both files. If a task's market data cannot
be downloaded (dead yfinance symbol), replace it with the next same-difficulty task
from the sample_A remainder in seeded order, and log the swap.

**D2. Ground-truth binding.** The reference implements the task **as their bench
binds it**: data = `yf_symbol` × `timeframe` from `task_data_requirements.json`
(even when that means a BTC task runs on AAPL bars), executor = their wrapper
semantics exactly (single `bt.feeds.PandasData` feed, cash 10000, commission 0.001,
`TradeAnalyzer`), via our instrumented replica `tape_exec.py`. The absurdity of the
binding is a reportable finding, not something we correct for them.

**D3. Tape-match key.** Primary correctness key = the ordered sequence of
`(fill_timestamp, side)` — identical to `tape_exec.tape_key()`. Timestamps
normalized to tz-naive UTC ISO strings by one shared function applied to both
tapes. Secondary sensitivity analysis reported with `(timestamp, side, size)`.
Prices are never compared (their stack pins fills deterministically given the same
pickle, so the primary key already separates semantic disagreement).

**D4. Determinacy protocol.** Per task: (a) a static screen against the
pin→probe→build rubric (entry rule pinned? exit pinned? indicator params pinned?
order sizing pinned? timeframe/asset coherent under D2 binding? hardcoded price
levels meaningful on the bound data?); (b) an empirical convergence test — **k = 3
independent strict-fidelity implementations**, each from a fresh claude CLI
context, each also emitting an explicit `ASSUMPTIONS` list of unpinned choices it
had to make; all executed on the frozen cache.
**Classification rule:** a tape divergence is an *implementation error* only if
explicit spec text contradicts the implementation — such an implementation gets
exactly one repair round. After repairs, the task is:
- **DETERMINATE** — all surviving (≥2) faithful implementations produce identical
  primary-key tapes. The converged tape is canonized to
  `results/tapes/ref_<id>.json`.
- **DETERMINATE-EMPTY** — implementations converge on a zero-trade tape (spec
  unsatisfiable on the bound data, e.g. orphaned price levels). Counts as
  determinate for metric 1 (the trace is unique), reported as its own row, and
  **stays in metric 2**: any candidate their judge passes is automatically a
  false-pass, since correct behavior is "never trade" and their gate 3 rejects it.
- **INDETERMINATE** — surviving faithful implementations diverge and the
  divergence traces to an unpinned spec choice (named ambiguity class).
**Metric 1 = (DETERMINATE + DETERMINATE-EMPTY) / 20**, Wilson 95% CI.

**D4a. Canonical environment defaults (addendum, recorded before Phase 2 began; no
reference had been generated yet).** Determinacy must measure whether the SPEC pins
behavior, not whether implementers happen to share environment conventions. The
reference prompt therefore fixes bench-canonical defaults, all taken from
QuantCode-Bench's own shipped example (`examples/sma_crossover.py`) and wrapper:
plain `self.buy()`/`self.sell()` (default sizer) when sizing is unstated;
`self.close()` for "exit the position"; at most one position, no pyramiding;
long-only unless the spec calls for shorting; pending-order guard reset in
`notify_order`; backtrader minperiod warm-up. Divergence on any of these is
implementation error (repairable); divergence on anything spec-level despite these
defaults is INDETERMINATE. Reference models: opus ×2 + sonnet ×1 per task (cross-
model convergence is stronger evidence than same-model convergence).

**D5. Ambiguity taxonomy (pre-registered classes).** `unpinned-sizing`,
`unpinned-indicator-params`, `unpinned-entry-trigger`, `unpinned-exit`,
`orphaned-price-levels` (hardcoded prices vs AAPL binding),
`timeframe-mismatch` (task prose vs bound timeframe), `goal-directed` (optimize-X,
no unique trace), `external-data-required`, `multi-asset-required` (their wrapper
is single-feed), `other` (free text). One or more classes per INDETERMINATE task.

**D6. Whitelist policy.** References prioritize spec fidelity over their
generation-side 8-indicator whitelist (correctness is defined by the task text,
not by generation constraints). Separately record per task whether a
whitelist-compliant faithful implementation exists; "task unsatisfiable under
their own generation rules" is a side finding.

**D7. Candidate generation (metric 2).** Their pipeline replicated as shipped:
full re-extracted `SYSTEM_PROMPT_EN` + task text, single-shot (`max_turns=1`
semantics), their `_clean_code` applied to output. Models: **sonnet and haiku via
claude CLI, 2 samples each → 4 candidates/task** on all metric-1-determinate
tasks. Caveat logged: CLI cannot pin their temperature 0.1; sampling variance is
part of what n=2/model absorbs.

**D8. Judge replication.** Their judge prompt template extracted verbatim from
`judge.py`, filled per candidate, sent as a single message via claude CLI with
`--model sonnet` (their README's endorsed judge is a Claude Sonnet; their
run-script's gpt-5.4 pin is unavailable without an API and this deviation is
disclosed). Their parsing rules reproduced exactly: `Rating: [[1]]/[[0]]` regex,
then their keyword-count fallback. Their gate order preserved: only candidates
passing compile/run/≥1-trade gates are judged. A judge CLI failure after 2
retries is recorded as `judge_error` and — matching their code — scored as PASS
(exception→`judge_aligned=True`); these are flagged in analysis.
**Stability spot-check:** 10 random judged candidates re-judged ×3.

**D9. Metric 2 definition.** Over all judge-passed candidates on determinate
tasks: false-pass = primary-key tape mismatch vs the canonical reference tape.
Reported pooled and per-difficulty with Wilson 95% CI, plus secondaries:
false-fail rate (judge fails a tape-matching candidate), judge catch rate on
gate-surviving-but-wrong candidates, gate attrition table.

**D10. Data freeze.** Cache built once (Phase 1), pickles copied to
`frozen_cache/`, SHA256 manifest committed. Every execution — references,
candidates, everything — reads only the frozen copies. The trailing-window
irreproducibility of their pipeline is reported as a finding.

---

## Phase 1 — Infrastructure hardening and data freeze

*Goal: everything runnable end-to-end on one task before any batch. No LLM batch
work happens here except one smoke generation.*

1. **Re-extract the full system prompt.** `qcb_system_prompt.txt` is truncated
   (naive triple-quote scan lost `_CODE_EXAMPLES` and the OUTPUT FORMAT segment).
   Extract by importing/AST-evaluating `generator.py`'s `SYSTEM_PROMPT_EN` value →
   `prompts/system_prompt_full.txt`; verify the tail contains the output-format
   rules.
2. **Extract the judge prompt template** verbatim from `judge.py` →
   `prompts/judge_prompt_template.txt` (with `{task}` / `{code}` placeholders),
   plus a faithful port of their parsing/fallback logic into the driver.
3. **Build and freeze data.** Run their `scripts/build_cache.py` restricted to the
   (symbol, timeframe) pairs used by `sample_20.json`; apply D1 replacement policy
   on failures; copy pickles to `frozen_cache/`; write `cache_manifest.json`
   (file, SHA256, rows, index tz, date range).
4. **Validate `tape_exec.py` on real pickles** (known gap: smoke test was
   tz-naive). Run `examples/sma_crossover.py` against frozen `AAPL_1d.pkl`; fix tz
   normalization in tape extraction if needed; add the shared timestamp
   normalizer (D3).
5. **Write the driver** (`driver/`): `tasks.py` (task → frozen cache path via
   `task_data_requirements.json`), `cli.py` (hardened claude invocation: direct
   `claude.exe` path, real file handles, 900s timeout, 2 retries, <1000-byte
   quota-stub detection, driven from bash so `--tools ""` survives), `gates.py`
   (their structure/execution/trade gates via tape_exec), `judge.py` (D8),
   `tape_compare.py` (D3), and an append-only `results/ledger.jsonl` keyed by
   `(phase, task_id, role, model, sample_idx)` so every batch is resumable and
   idempotent.
6. **End-to-end smoke test:** one easy task through generation → gates → judge →
   tape compare. Sign off before Phase 2.

**Exit criteria:** full prompt verified; frozen cache manifest written; tape_exec
validated on tz-aware data; smoke task produces a complete ledger row.

## Phase 2 — Metric 1: determinacy audit (20 tasks)

1. **Static screen.** Each task scored against the D4(a) rubric →
   `results/screen/<id>.json` (rubric booleans + predicted ambiguity classes).
   Done by analyst agents reading the task text and the bound data's manifest row
   — predictions only; classification comes from tapes.
2. **Reference drafting.** 3 independent strict-fidelity implementations per task
   via claude CLI (fresh context each; strict prompt: implement EXACTLY, deviate
   from nothing, list every unpinned choice under `ASSUMPTIONS`; environment
   facts given: backtrader, single feed, cash/commission, bound symbol/timeframe/
   data range). 60 calls.
3. **Execute** all 60 through `tape_exec.py` on frozen cache → tapes + crash logs.
4. **Adjudicate** per D4: repairs (max 1 round/implementation, only on explicit
   spec-text contradiction, ~15 call budget), then classify every task
   DETERMINATE / DETERMINATE-EMPTY / INDETERMINATE(+classes). Canonize reference
   tapes. Every adjudication decision logged with the spec sentence it cites →
   `results/adjudication/<id>.md`.
5. **Compute metric 1** + taxonomy table → `results/metric1.json`.

**Exit criteria:** all 20 tasks classified with cited adjudications; canonical
tapes on disk for every determinate task.

## Phase 3 — Metric 2: judge false-pass rate

*Runs only on determinate tasks (incl. DETERMINATE-EMPTY).*

1. **Generate candidates** per D7: ≤ 20 tasks × 4 = 80 CLI calls.
2. **Run their gates** on every candidate (local, fast): structure check →
   execution on frozen cache → ≥1 trade. Record the attrition table.
3. **Judge gate survivors** per D8 (≤80 CLI calls + 30 stability re-judges).
4. **Tape-compare** every judged candidate vs canonical reference (primary key;
   secondary key logged too).
5. **Compute metric 2** + secondaries → `results/metric2.json`.

**Exit criteria:** every candidate has a complete ledger row
(gates, judge verdict, tape verdict); metrics computed with CIs.

## Phase 4 — Analysis and report

1. **REPORT.md** in `qcb_audit/`: methods (this plan by reference), the two
   headline numbers with exact counts and Wilson CIs, per-difficulty breakdowns,
   ambiguity taxonomy, gate attrition, judge stability check.
2. **Structural findings section** (evidence already in hand, confirmed by runs):
   360/400 tasks backtested on AAPL regardless of named asset; trailing-window
   non-reproducible data; judge instructed to be lenient; judge-exception→pass
   default; keyword-grep judge fallback; returns computed but never scored;
   whitelist-unsatisfiable tasks (D6).
3. **Threats to validity:** n=20; CLI temperature not pinnable (vs their 0.1/0.0);
   judge model is README-endorsed Sonnet rather than their run-script's gpt-5.4
   pin; single frozen data snapshot; adjudication involved judgment (mitigated by
   pre-registered rules + cited spec text).
4. Optional: results artifact page for readability.

---

## Budget & risks

**CLI call budget:** ~60 refs + ~15 repairs + ~80 generations + ~110 judge calls
+ ~20 analyst passes ≈ **285 calls**, 3 workers, mixed short/long — hours of wall
clock; all batches resumable via ledger.

| Risk | Mitigation |
|---|---|
| CLI session-limit exhaustion mid-batch | resumable ledger, stub-size detection, batches split across sessions |
| yfinance symbols dead / intraday window empty | D1 replacement policy, logged |
| tz-aware pickles break backtrader feed/num2date | Phase 1.4 validation gate before any batch |
| Model-generated code runs unsandboxed (their design) | subprocess + 120s timeout kept; code provenance is claude-only; noted in report |
| Judge nondeterminism via CLI | stability spot-check (D8) bounds it |
| Adjudication subjectivity | pre-registered rules, one repair round, cited spec text per decision |

## Directory layout (target)

```
qcb_audit/
  PLAN.md                  ← this file
  select_sample.py         sample_20.json
  prompts/                 system_prompt_full.txt, judge_prompt_template.txt,
                           ref_impl_prompt.txt, analyst_rubric.txt
  frozen_cache/            *.pkl + cache_manifest.json
  driver/                  cli.py, tasks.py, gates.py, judge.py, tape_compare.py
  results/                 ledger.jsonl, screen/, refs/, tapes/, gens/, judge/,
                           adjudication/, metric1.json, metric2.json, deviations.md
  REPORT.md                final deliverable
```
