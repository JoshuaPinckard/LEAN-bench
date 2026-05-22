# LEAN-Bench

`LEAN-Bench-v2.0` — benchmark for LLM-generated QuantConnect LEAN code.
Vue 3 + Vite frontend, FastAPI Python backend, SQLite database. Local-only,
no auth. Methodology decisions live in
[docs/benchmark_decision_log.md](docs/benchmark_decision_log.md).

## What the benchmark does

For every benchmark-eligible prompt and every (model × condition × trial)
cell, the harness:

1. Sends the prompt to the model (with the condition's tool set, if any).
2. Runs the resulting code through a 5-stage pipeline:
   **compile → runtime → trade → schema → judge**.
3. Has a **dual judge** (claude-sonnet-4-6 + gpt-5.4, averaged) score
   semantic faithfulness against the original prompt.
4. Writes a sidecar `results/artifacts/{call_id}.json` capturing the full
   trajectory (raw response, tool calls, hashes).

Every row is stamped with `benchmark_version`, `prompt_set_sha256`,
`judge_version`, and `judge_threshold` for provenance.

## Conditions (2×2 factorial + 2 baselines)

| ID | Tools | Turns | N | Purpose |
|---|---|---|---|---|
| `C1_oneshot`        | none                            | 1   | 5 | Baseline — one-shot, no tools |
| `C2_docs`           | `qc_docs_retrieve`              | ≤24 | 3 | D: docs retrieval only |
| `C3_compiler`       | `lean_backtest`                 | ≤24 | 3 | F: compiler feedback only |
| `C4_docs_compiler`  | `qc_docs_retrieve` + `lean_backtest` | ≤24 | 3 | D × F: both tools |
| `C5_agent_notools`  | none (neutral continuation hop) | ≤24 | 3 | Isolates "more attempts" from "more information" |

`N` is the default replicate count per cell, overridable via
`LEANBENCH_N_BASELINE` / `LEANBENCH_N_AGENT`. Max turns is overridable via
`LEANBENCH_MAX_TURNS` or per-request in the UI.

## Models (frozen 2026-05-22)

| Friendly | API ID | Provider |
|---|---|---|
| claude-opus-4.7   | claude-opus-4-7              | anthropic |
| claude-opus-4.6   | claude-opus-4-6              | anthropic |
| claude-sonnet-4.6 | claude-sonnet-4-6            | anthropic |
| claude-haiku-4.5  | claude-haiku-4-5-20251001    | anthropic |
| gpt-5.5           | gpt-5.5-2026-04-23           | openai    |
| gpt-5.4           | gpt-5.4-2026-03-05           | openai    |
| gpt-5.4-mini      | gpt-5.4-mini-2026-03-17      | openai    |
| gpt-5.4-nano      | gpt-5.4-nano-2026-03-17      | openai    |
| gpt-4.1-mini      | gpt-4.1-mini                 | openai    |
| gemini-3.1-pro    | gemini-3.1-pro-preview       | google    |

Source of truth: [harness/models.py](harness/models.py). `EXCLUDED_CELLS` in
[harness/constants.py](harness/constants.py) is empty for v2.0 — every
(model × condition) combination is in scope.

## Prerequisites

- **Python 3.11+** with a venv at `.\venv\`
- **Node 18+** with `npm`
- **Docker Desktop** — running, for the C3/C4 `lean_backtest` tool (the
  LEAN CLI shells out to a pinned engine image)
- **API keys** for Anthropic, OpenAI, and Google in a `.env` file (see below)

## Setup

### 1. Python environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. API keys — create `.env` at the repo root

```ini
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...
GEMINI_API_KEY=AIza...

# Vite-style aliases (optional; backend bridges them automatically).
VITE_ANTHROPIC_API_KEY=sk-ant-...
VITE_OPENAI_API_KEY=sk-proj-...
VITE_GEMINI_API_KEY=AIza...
```

For Gemini, you must enable billing in
[AI Studio](https://aistudio.google.com/) — the free tier is locked to 0
requests for `gemini-3.1-pro` and will 429 immediately.

### 3. Frontend dependencies

```powershell
npm install
```

### 4. Verify the lineup before any run

```powershell
$env:PYTHONPATH = (Get-Location).Path
.\venv\Scripts\python.exe scripts/smoke_models.py
```

Every model should report `PASS`. If one fails with `model_not_found`,
re-check [harness/models.py](harness/models.py) against the provider's live
model list.

## Running locally

You need **two** processes: the FastAPI backend on `:8010` and the Vite dev
server on `:5173`.

### Terminal 1 — Backend

```powershell
.\start.ps1
```

This sets `LEAN_BIN` / `LEAN_WORKSPACE` and launches uvicorn with a
narrowly-scoped reloader (`--reload-dir backend --reload-dir harness`). The
narrow scope is **critical**: every backtest writes a `main.py` into
`lean_workspace/leanbench_<random>/`, and an unconstrained reloader would
restart the server mid-request, killing the in-flight `/api/generate`
connection (browser shows `net::ERR_FAILED` + a misleading CORS error).

API docs: `http://localhost:8010/docs`.

### Terminal 2 — Frontend

```powershell
npm run dev
```

Open `http://localhost:5173`. The Generate tab takes a prompt, lets you
pick any subset of models × conditions, and streams results back.

## Before any benchmark run: freeze the prompt set

```powershell
.\venv\Scripts\python.exe scripts/freeze_prompt_set.py
```

This writes `results/frozen/prompt_set_v1.json` (committed to git — the
reproducibility anchor) plus a sidecar `.meta.json` with hash and timestamp.
`run_grid` refuses to generate against any benchmark-eligible prompt when
the live DB diverges from the frozen file; `/api/generate` returns HTTP
409. Ad-hoc prompts (`source='adhoc'`) bypass the guard so you can iterate
without invalidating the canonical hash.

```powershell
# Verify the on-disk artifact still matches the DB.
.\venv\Scripts\python.exe scripts/freeze_prompt_set.py --check
```

## Project layout

```
backend/                FastAPI HTTP wrapper
  app.py                Endpoints, CORS for :5173
  schemas.py            Pydantic models

harness/                Pure-Python core (no HTTP, no UI)
  models.py             MODELS_FROZEN, CONDITIONS — the locked lineup
  constants.py          JUDGE_PASS_THRESHOLD, BENCHMARK_VERSION, FAILURE_MODES
  storage.py            SQLite layer; pass_rate_matrix, schema migrations
  prompt_freeze.py      Canonical prompt-set serialization + hash
  orchestrator.py       Cell lifecycle: exclusion → create → agent loop →
                        compile → backtest → schema → judge → artifact
  agent_tools.py        Tool dispatch: qc_docs_retrieve, lean_backtest
  lean_executor.py      Runs `lean backtest` via Docker, parses results
  judge.py              Dual-judge (sonnet-4.6 + gpt-5.4); locked rubric
  pricing.py            USD cost per call
  evaluator.py          AST compile, schema-adherence checks
  artifacts.py          Sidecar JSON writer
  conditions/builder.py condition_id → per-provider tool config
  providers/
    base.py             ProviderResponse contract
    anthropic_client.py
    openai_client.py
    gemini_client.py

src/                    Vue 3 frontend
  api.js                Single source of truth for backend HTTP
  components/{GenerateTab,PromptsTab,DistributionTab,StatsTab,
              PromptModal,CallDetailsModal,ResultCard}.vue

scripts/
  freeze_prompt_set.py    Freeze + write canonical artifact (run before main runs)
  smoke_models.py         Verify every model in MODELS_FROZEN responds
  rejudge.py              Re-run the judge on existing calls
  validate_judge.py       Compute judge-vs-human metrics on a labeled JSONL
  export_hitl_sample.py   Stratified, seeded HITL sample exporter
  wipe_calls.py           DB cleanup utility

lean_backtest_tool/     Standalone package — the lean_backtest tool impl
lean_rag/               Standalone package — frozen QC docs retriever
lean_workspace/         LEAN project root (gitignored except lean.json + data/)

results/
  leanbench.db          SQLite DB (gitignored)
  frozen/               Frozen prompt-set artifact (COMMITTED)
  artifacts/            Per-call sidecar JSONs (gitignored)

docs/
  benchmark_decision_log.md  Methodology rationale (paper-facing)

tests/                  pytest suite
```

## Database schema

`calls` is the central table. Status is one of `started | completed | error
| excluded`. Every row carries `benchmark_version`, `prompt_set_sha256`,
`judge_version`, `judge_threshold`, `artifact_path`, `artifact_sha256`.

`turns` carries one row per agent-loop iteration with per-turn
`tool_events_json` (RAG queries + compiler runs), `response_code_extracted`,
`response_tokens_in/out`, `wall_clock_seconds`, and `is_final_turn`.

The store auto-migrates additively when `Store()` is constructed — running
an older DB through the harness upgrades it in place.

## Running tests

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -v
```

Coverage: canonical serialization stability, hash round-trip, exclusion
gating, denominator math, artifact hash determinism. The judge / provider
clients are not unit-tested (they hit external APIs); use
`scripts/smoke_models.py` for a live-API health check.

## HITL validation workflow

```powershell
# 1. Export a reproducible, stratified sample (seeded; only frozen-prompt rows)
.\venv\Scripts\python.exe scripts/export_hitl_sample.py --per-cell 3 --seed 20260513

# 2. Humans fill in human_score / matches_prompt_intent_human /
#    human_failure_mode in the resulting CSV/JSONL.

# 3. Validate.
.\venv\Scripts\python.exe scripts/validate_judge.py validation/hitl_sample.jsonl
```

HITL evaluates **judge credibility**. It does NOT optimize the pass
threshold — that's locked at 0.7 by the rubric. Any threshold change
requires bumping `JUDGE_VERSION` and re-judging all affected calls.

## Troubleshooting

- **Browser shows "Failed to fetch" / CORS error on `/api/generate`.**
  The backend connection died mid-request. Almost always caused by
  uvicorn's reloader watching a file that the harness writes during a run
  (typically `lean_workspace/leanbench_<random>/main.py`). Confirm
  `start.ps1` uses `--reload-dir backend --reload-dir harness` (not bare
  `--reload`), then restart the backend cleanly.

- **`ModuleNotFoundError: No module named 'tiktoken'`** during a C3/C4 run.
  `pip install -r requirements.txt` again — `tiktoken` is required by
  `lean_backtest_tool`.

- **`model_not_found` from OpenAI.** A dated suffix in
  [harness/models.py](harness/models.py) is wrong. Run
  `scripts/smoke_models.py` and cross-check the pinned ID against
  `client.models.list()`.

- **Gemini returns `RESOURCE_EXHAUSTED` (429) on every call.** Free-tier
  quota for `gemini-3.1-pro` is 0. Enable billing in
  [AI Studio](https://aistudio.google.com/).

- **Anthropic returns `rate_limit_error` (429).** Your tier has a 30k
  input-TPM ceiling on sonnet-4.6. The SDK auto-retries with backoff
  (`max_retries=6` in [harness/providers/anthropic_client.py](harness/providers/anthropic_client.py));
  reduce the parallel cell fan-out or raise your tier.

- **`lean: command not found` during a backtest.** `start.ps1` sets
  `LEAN_BIN=.\venv\Scripts\lean.exe`. If Docker Desktop isn't running, the
  backtest will surface `docker_error` and the orchestrator will abort the
  loop — start Docker before kicking off a run.

- **Stale `status='started'` rows in the DB.** Calls that died mid-flight
  (server restart, Ctrl+C, etc.) leave their row in `started`. Safe to
  clean up:
  ```sql
  UPDATE calls SET status='error', error='killed mid-run' WHERE status='started';
  ```
