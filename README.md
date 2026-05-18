# LEAN-Bench

`LEAN-Bench-v1.0` — benchmark for LLM-generated QuantConnect LEAN code.
Vue 3 + Vite frontend, FastAPI Python backend, SQLite database. Local-only,
no auth. This is the **locked** v1.0 codebase; methodology decisions live in
[docs/benchmark_decision_log.md](docs/benchmark_decision_log.md).

## What the benchmark does

For every benchmark-eligible prompt and every (model, condition) cell, the
harness generates code, runs a LEAN backtest, asks a judge model to score
implementation correctness, and stamps a full provenance trio on the row:

- `benchmark_version` — `LEAN-Bench-v1.0`
- `prompt_set_sha256` — SHA-256 of the frozen prompt-set artifact
- `judge_version` + `judge_threshold` — judge identity + the pass cutoff
  actually applied to that row

A sidecar JSON artifact is written for every non-excluded call at
`results/artifacts/{call_id}.json` capturing the provider-exposed
trajectory (raw response, tool calls, web citations, hashes).

## The four conditions

| ID | Tools | Turns | Purpose |
|---|---|---|---|
| `S1_base`         | none                       | 1   | Baseline — parametric only |
| `S2_docs`         | QC docs retrieval (Sonnet preprocessor) | 1 | Domain knowledge augmentation |
| `S3_web`          | provider-native web search | 1   | General knowledge augmentation |
| `A1_agentic_full` | docs + web + compile-loop  | ≤10 | Agentic compile loop (v1.0 scope — see note below) |

> **A1 scope note for v1.0.** The per-turn feedback signal inside the A1
> loop is Python AST compile only. When the model's submitted code parses,
> the loop exits and the LEAN backtest + judge run once on the final code.
> Full per-turn Compile → Backtest → Trade feedback is deferred to v1.1.
> Display name is **"Agentic compile loop"**; the `A1_agentic_full` ID is
> retained for DB schema continuity. Decision log §6 has the full rationale
> and the v1.1 roadmap.

## Models (frozen 2026-05-09)

| Friendly | API ID | Family |
|---|---|---|
| claude-opus-4.7   | claude-opus-4-7        | claude |
| claude-opus-4.6   | claude-opus-4-6        | claude |
| claude-sonnet-4.6 | claude-sonnet-4-6      | claude |
| gpt-5.5           | gpt-5.5-2026-04-23     | gpt    |
| gpt-5.4           | gpt-5.4-2026-03-05     | gpt    |
| gemini-3.1-pro    | gemini-3.1-pro-preview | gemini |

### Excluded cells

`gemini-3.1-pro × S3_web` and `gemini-3.1-pro × A1_agentic_full` are
**excluded by design** for tooling parity (we lack a Gemini-compatible MCP
docs retrieval / agentic feedback wiring). The cells are persisted with
`status='excluded', excluded_reason='tooling_parity'` so the grid stays
auditable but are dropped from pass-rate denominators, attempted-call
counts, and cost totals. See decision log §2.

## Running locally

You need **two** processes: the Python backend on :8000 and the Vite dev
server on :5173.

### 1. Backend (Python)

```bash
python -m venv venv
venv\Scripts\activate          # PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt

# .env: ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
# (VITE_*_API_KEY names are auto-bridged at backend startup)

uvicorn backend.app:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`.

### 2. Frontend (Vue / Vite)

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

## Before any benchmark run: freeze the prompt set

```bash
python scripts/freeze_prompt_set.py
```

This writes `results/frozen/prompt_set_v1.json` (committed to git — it is
the reproducibility anchor) and a sidecar `.meta.json` with the hash and
freeze timestamp. The orchestrator refuses to generate against any
benchmark-eligible prompt when the live DB diverges from the frozen file;
the `/api/generate` endpoint returns HTTP 409 with the mismatched hashes.

```bash
# Verify the on-disk artifact still matches the DB.
python scripts/freeze_prompt_set.py --check
```

Ad-hoc prompts (`source='adhoc'`) bypass the freeze guard — useful for
development without invalidating the canonical hash. They are excluded
from the canonical form by construction.

## Project layout

```
backend/
  app.py            FastAPI app — 10 endpoints, CORS for :5173
  schemas.py        Pydantic request/response models

harness/            Pure Python core (no HTTP, no UI)
  models.py         FROZEN constants: MODELS_FROZEN, CONDITIONS, FAILURE_TAXONOMY
  constants.py      JUDGE_PASS_THRESHOLD, BENCHMARK_VERSION, EXCLUDED_CELLS,
                    FAILURE_MODES, CALL_STATUSES
  storage.py        SQLite layer; status-aware pass_rate_matrix
  prompt_freeze.py  Canonical prompt-set serialization + hash
  artifacts.py      Sidecar JSON writer for per-call provenance
  pricing.py        Cost computation
  evaluator.py      4-stage pipeline AST compile check
  orchestrator.py   Cell lifecycle: exclusion gate -> create -> generate ->
                    backtest -> judge -> artifact; freeze guard in run_grid
  lean_executor.py  Runs `lean backtest` and parses results JSON
  judge.py          Anthropic Sonnet judge; locked rubric + version
  retrieval.py      QC docs preprocessor for S2/A1 (cached per prompt)
  conditions/
    builder.py      condition_id -> per-provider tool config
  providers/
    base.py         ProviderResponse contract + code-fence extractor
    anthropic_client.py / openai_client.py / gemini_client.py

src/                Vue 3 frontend
  api.js, App.vue, components/{GenerateTab,PromptsTab,DistributionTab,
                                StatsTab,PromptModal,CallDetailsModal,
                                ResultCard}.vue
  style.css

scripts/
  freeze_prompt_set.py   Freeze + write canonical artifact (run before main runs)
  rejudge.py             Re-run the judge on existing calls
  validate_judge.py      Compute judge-vs-human metrics on a labeled JSONL
  export_hitl_sample.py  Stratified, seeded HITL sample exporter

docs/
  benchmark_decision_log.md  Methodology rationale (paper-facing)

results/
  leanbench.db           SQLite DB (gitignored)
  frozen/                Frozen prompt-set artifact (COMMITTED to git)
    prompt_set_v1.json
    prompt_set_v1.json.meta.json
  artifacts/             Per-call sidecar JSONs (gitignored, written at run time)

tests/                   pytest unit tests covering §1, §2, §4 acceptance
```

## Database schema (v1.5)

`calls` is the central table. v1.5 (2026-05-13 pre-run hardening) adds:

- `status` (`started` | `completed` | `error` | `excluded`)
- `excluded_reason` — populated iff status = excluded
- `benchmark_version`, `prompt_set_sha256` — stamped at row creation
- `judge_threshold` — the cutoff applied to derive `judge_pass` for this row
- `artifact_path`, `artifact_sha256` — sidecar JSON location + content hash

Pre-existing v1.4 columns (`condition`, `pass_number`, `judge_score`,
`judge_version`, `judge_error`, `failure_mode`, full backtest fields, etc.)
are unchanged. The migration is additive and idempotent — running an old DB
through `Store()` upgrades it in place.

## HITL validation workflow

```bash
# 1. Export a reproducible, stratified sample (seeded; only frozen-prompt rows)
python scripts/export_hitl_sample.py --per-cell 3 --seed 20260513

# 2. Have humans fill in human_score / matches_prompt_intent_human /
#    human_failure_mode in the CSV (or JSONL).

# 3. Validate.
python scripts/validate_judge.py validation/hitl_sample.jsonl
#   reports Pearson, Spearman, MAE, intent agreement, failure-mode
#   agreement, and sample composition.
```

HITL evaluates judge credibility. It does NOT optimize the pass threshold —
that's locked at 0.7 by the rubric semantics. Any threshold change requires
bumping `JUDGE_VERSION` and re-judging all affected calls.

## Running tests

```bash
.\venv\Scripts\python.exe -m pytest tests/ -v
```

Coverage: canonical serialization stability, hash round-trip,
exclusion gating, denominator math, artifact hash determinism, web-citation
extraction. The judge / provider clients are not unit-tested (they call
external APIs); use `scripts/rejudge.py --limit 1 --dry-run` for a
post-schema-change smoke check.

## v1.1 roadmap (not part of v1.0)

- **Per-turn LEAN feedback inside A1.** Today the A1 loop returns
  AST-compile feedback only; the LEAN backtest + judge run once on the
  final code. v1.1 replaces this with a per-turn LEAN executor + judge that
  feeds structured Compile → Backtest → Trade results back to the model
  each turn. Will require re-running every A1 cell and bumping the
  benchmark version. See [docs/benchmark_decision_log.md](docs/benchmark_decision_log.md) §6.
- **QC docs RAG via MCP for non-Anthropic providers.** S2_docs today uses a
  Sonnet preprocessor that injects raw doc excerpts (see
  `harness/retrieval.py`); replacing this with a real MCP server is a
  scheduled v1.1 change.
- **Pricing rates.** `harness/pricing.py` PRICING dict is intentionally
  seeded with `None` until verified rates are filled in; cost columns show
  `None` until then.
