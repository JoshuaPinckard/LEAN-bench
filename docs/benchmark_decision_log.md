# LEAN-Bench Methodology Decision Log

This document records the methodology choices that are not derivable from the
code alone. Reviewers and the paper draft should refer here for the rationale
behind each protocol constant or exclusion. Decisions are intentionally short
and direct; the code is the source of truth for *what*, this is the source of
truth for *why*.

Benchmark version: `LEAN-Bench-v1.0`
Frozen date: see `harness/models.py:FROZEN_DATE`
Last revised: 2026-05-13

---

## 1. Prompt-set hash definition

**Decision.** The benchmark's prompt set is identified by the SHA-256 of a
canonical JSON serialization of all eligible prompts. Every result row
(`calls.prompt_set_sha256`) carries this hash; the orchestrator refuses to run
benchmark prompts when the live DB diverges from the on-disk frozen artifact
at `results/frozen/prompt_set_v1.json`.

**Canonical form** (`harness/prompt_freeze.py`):

- Allowlisted fields only: identity, original/reformulated text, provenance
  (source, source_date, is_post_cutoff), categorization, LEAN configuration
  (securities, resolution, indicators, universe, tickers, dates, cash),
  evaluation rules (mode, strictness, underspecification), leak-audit fields,
  and `excluded_from_benchmark`.
- Excluded from the hash: timestamps (`created_at`), UI/curator workflow
  telemetry (`ai_prepopulated`, `curator_modified_fields`), and any retired
  legacy column. Cosmetic edits to those fields do not invalidate the hash.
- Prompts are sorted by `prompt_id`; keys are sorted at every level;
  encoding is ASCII; whitespace is stripped (`separators=(",", ":")`).

**Why.** A canonical hash makes the prompt set a single, citable artifact.
Any reader of the paper can clone the repo, compute the hash from the
checked-in artifact, and confirm it matches the values stamped on every
published call.

**How to apply.** Run `python scripts/freeze_prompt_set.py` before any main
benchmark batch. Any later edit to a benchmark-eligible prompt requires
re-freezing AND a methodology note acknowledging the prompt-set change.

### What the hash does NOT cover

The hash fixes the *user-facing prompt definition*. It deliberately does NOT
cover:

- **System prompt** — `harness/orchestrator.py:SYSTEM_PROMPT` is hashed
  separately as `calls.system_prompt_sha256` per row. Bumping it is a
  methodology change but does not invalidate prompt-set identity.
- **S2_docs retrieval snippet** — the QC-docs excerpt prepended under S2/A1
  is generated at run time by `harness/retrieval.py` (Sonnet picks files,
  raw content is concatenated). It is cached per prompt and logged in full
  on the sidecar artifact (`results/artifacts/{call_id}.json:retrieval_snippet`)
  plus its SHA-256 (`retrieval_snippet_sha256`). The retrieval snippet is
  treated as a *harness-generated input*, not as part of the prompt-set
  identity — different snippets across re-runs of S2/A1 are expected and
  audited per call, not frozen globally.

This split is deliberate: the prompt-set hash answers "did the benchmark
run on the same prompts?"; per-call artifacts answer "what exactly did the
model see this time?". The paper must describe S2_docs context as
harness-generated and logged per call, not as part of the canonical prompt.

---

## 2. Gemini exclusion from `S3_web` and `A1_agentic_full`

**Decision.** Gemini-3.1-pro is excluded from `S3_web` and `A1_agentic_full`
for the v1.0 run. The cells are persisted with
`status='excluded', excluded_reason='tooling_parity'` so the grid stays
auditable, but are dropped from pass-rate denominators, total attempted
calls, and cost totals.

**Why.** The agentic loop is wired against Anthropic and OpenAI tool-calling
APIs; the Gemini SDK's tool-use surface does not provide the parity we need
to make the comparison fair on either web search behavior or the structured
feedback round-trip. Forcing Gemini through a degraded surrogate would
introduce a confound that we cannot cleanly attribute later. We disclose this
as a tooling limitation rather than score it as a failure.

**How to apply.** The exclusion list lives in
`harness/constants.py:EXCLUDED_CELLS`. The orchestrator gates these cells
before any provider call. Adding Gemini parity later requires removing the
entry, re-running the affected cells, and bumping the benchmark version.

---

## 3. Judge threshold rationale

**Decision.** `JUDGE_PASS_THRESHOLD = 0.7`, fixed a priori.

**Why.** 0.7 corresponds to the rubric anchor "mostly correct, core logic
intact" in `harness/judge.py:JUDGE_SYSTEM_PROMPT`. It is a *semantic*
cutoff derived from the rubric definition, not a knob fitted to maximize a
target metric. The HITL validation pipeline (`scripts/validate_judge.py`,
`scripts/export_hitl_sample.py`) evaluates judge credibility against human
labels at the rubric definition; it does NOT optimize the threshold.

**How to apply.** Treat 0.7 as locked. Any future change requires bumping
`JUDGE_VERSION` in `harness/judge.py` AND running
`python scripts/rejudge.py --target-version <new>` over every affected call.
The threshold actually used to derive `judge_pass` on each row is persisted
to `calls.judge_threshold` so historical pass/fail decisions remain
auditable even after a versioned re-judge.

---

## 4. S3 web-search artifact logging — what we DO and DO NOT claim

**Decision.** For every non-excluded call we write a JSON sidecar at
`results/artifacts/{call_id}.json` capturing the provider-EXPOSED web
artifacts: tool calls, citations, URLs, response items where the provider
surfaces them. The artifact path and SHA-256 are persisted to
`calls.artifact_path` and `calls.artifact_sha256` for cross-checking.

**What this captures.** Whatever the provider's API surfaces about the
web-search interaction — tool invocations, URL citations, returned titles
and snippets, and the full raw response object.

**What this does NOT capture.** The provider's internal retrieval context.
Anthropic, OpenAI, and Google all run web search through provider-controlled
infrastructure and do not expose, in their public APIs, every byte the model
saw. The benchmark is honest about this limitation: a reviewer can inspect
the *provider-exposed* artifacts that were tied to a given `call_id`, but
the benchmark does not claim to have reconstructed the model's exact
internal context.

**Why this still suffices.** S3 measures whether augmenting the prompt with
general web search materially changes the model's output relative to S1.
The pass-rate delta is observable. Causal attribution to specific retrieved
content is bounded by what the provider exposes — a methodological limit we
state plainly rather than paper over.

**How to apply.** Always log the sidecar; never delete it. Cite the
artifact set in the paper as "provider-exposed web artifacts," never as
"exact context seen by the model."

---

## 5. HITL validation sampling rule

**Decision.** The judge-validation sample is drawn deterministically from
the frozen prompt set using a fixed random seed and stratified across
`(model_id, condition_id)`. When judged outputs already exist, the sampler
also covers score bins and failure modes to avoid blind spots. The export
tool (`scripts/export_hitl_sample.py`) writes prompt text, generated code,
a compact backtest summary, judge score, judge intent flag, and judge
failure mode; human labelers fill in the rubric score, `matches_prompt_intent`,
and primary failure mode in the same row.

**Why.** A reproducible sample lets the paper report judge–human agreement
without inviting a fitting-to-the-sample critique. Fixing the seed and
stratification cells removes ambiguity about *which* calls were validated.

**How to apply.** Never reuse the same sample to "tune" the judge. The
HITL pass produces an agreement statistic; if it's unacceptable, bump
`JUDGE_VERSION`, fix the judge, rejudge ALL affected calls, and draw a
NEW HITL sample from a different seed for the next pass.

---

## 6. A1 in v1.0 is a compile-loop, not full-stack per-turn LEAN

**Decision.** In `LEAN-Bench-v1.0`, the agentic feedback signal inside the
turn loop is AST compile only (`harness/evaluator.py:evaluate`). When the
model's submitted code parses cleanly, the loop exits — `feedback=None`
tells the orchestrator there's nothing actionable to send back. LEAN
backtest and the judge run ONCE on the final code, after the loop.

This is more limited than the original protocol memo, which described
per-turn Compile → Backtest → Trade feedback. The historical
condition_id `A1_agentic_full` is kept to preserve the locked DB schema,
but the display name has been updated to **"Agentic compile loop"** and
the `CONDITIONS[...].semantics` text now describes what actually runs.

**Why ship with this scope.**

- Per-turn LEAN execution is correctness-critical: each `lean backtest`
  invocation takes 30–90 seconds and ~$0.05–$0.20 of judge spend. Multiplied
  across up to 10 turns × the full grid, this is a 10× cost+latency hit.
  Adding it under time pressure would block the v1.0 freeze.
- The compile-loop is still a real signal: it measures whether models can
  self-correct from a Python syntax error, which is a non-trivial
  capability and a frequent failure mode in single-shot runs.
- The reported headline metric for A1 in v1.0 must explicitly say
  *"agentic compile loop"*, not *"agentic with full execution feedback"*.

**Paper wording (mandatory).** When discussing A1 in v1.0, use language
like: "A1 runs an agentic compile loop: the model receives Python
parse-error feedback after each turn for up to 10 turns; the LEAN backtest
and judge are evaluated on the final code." Do NOT describe A1 as
"full-stack agentic" or "self-correcting from backtest errors" — that
behavior is the v1.1 deliverable.

**v1.1 roadmap.** Replace `harness/evaluator.py`'s compile-only path with
a per-turn LEAN executor + judge that returns structured feedback (compile
error → backtest error → trade outcome → judge reasoning). Persist per-turn
backtest fields to the `turns` table (the columns already exist:
`compile_pass`, `backtest_pass`, `trade_pass`, `judge_pass`). Bumping to
v1.1 will require re-running every A1 cell.

**How to apply now.** Treat A1 as a compile-loop in all v1.0 analysis. If
a downstream comparison needs full-execution agentic results, it is a v1.1
deliverable; do not retrofit by interpolating from S2/S3 results.

---

## 7. A1 sub-set selection — outcome independence

**Decision.** When the paper discusses "the A1 subset" as a primary
analysis, that subset is defined from PROMPT METADATA only (e.g. strategy
complexity, evaluation_mode). It is never defined by `matches_prompt_intent`,
judge score, or any other field that depends on which model ran the prompt.

**Why.** Conditioning a primary subset on an outcome turns the result into
a tautology. The benchmark's strength is that the A1 grid is computed once
per (prompt, model, condition); defining subsets from prompt-only attributes
preserves that.

**How to apply.** Outcome-conditioned subsets are allowed only as secondary
analyses, clearly labeled. If a metadata-defined A1 subset is later
introduced, it is hashed and frozen the same way the full prompt set is —
see `harness/prompt_freeze.py`.

---

## Change history

| Date       | Change                                                  |
|------------|---------------------------------------------------------|
| 2026-05-13 | Initial decision log (v1.0 pre-run hardening).          |
