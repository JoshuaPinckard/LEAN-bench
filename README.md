# LEAN-Bench

Private research workbench for benchmarking LLMs on QuantConnect LEAN code generation.
Vue 3 + Vite frontend, FastAPI Python backend, SQLite database. Local-only, no auth.

## Running locally

You need **two** processes: the Python backend on :8000 and the Vite dev server on :5173.

### 1. Backend (Python)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Make sure .env contains ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
# (Vite-style VITE_*_API_KEY names are auto-bridged at backend startup.)

uvicorn backend.app:app --reload --port 8000
```

Backend serves the API at `http://localhost:8000` and auto-generated docs at `http://localhost:8000/docs`.

### 2. Frontend (Vue / Vite)

In a second terminal:

```bash
npm install
npm run dev
```

Open `http://localhost:5173`. The app boots by fetching `/api/models` and `/api/conditions`; if the backend isn't running you'll see a "Backend not reachable" page with the start command.

## Project layout

```
backend/
  app.py            FastAPI app — 10 endpoints, CORS for :5173
  schemas.py        Pydantic request/response models

harness/            Pure Python core (no HTTP, no UI)
  models.py         FROZEN constants: MODELS_FROZEN, CONDITIONS, FAILURE_TAXONOMY
  storage.py        SQLite layer (3 tables: prompts, calls, turns)
  pricing.py        Cost computation (rates intentionally unset; see file)
  evaluator.py      4-stage pipeline (only `compile` implemented today)
  orchestrator.py   Runs one cell; A1_agentic_full loops up to 10 turns,
                    writing one row to `turns` per iteration
  conditions/
    builder.py      condition_id -> per-provider tool config
  providers/
    base.py         ProviderResponse contract + code-fence extractor
    anthropic_client.py
    openai_client.py
    gemini_client.py

src/                Vue 3 frontend
  api.js            Single source of truth for backend HTTP
  App.vue           Tab shell (Generate / Prompts / Stats)
  components/
    GenerateTab.vue
    PromptsTab.vue
    StatsTab.vue
    PromptModal.vue
    CallDetailsModal.vue
    ResultCard.vue
  style.css

scripts/            CLI entry points (smoke_test, batch runners)
results/            SQLite DB lives here (gitignored)
```

## The four conditions

| ID | Tools | Turns | Purpose |
|---|---|---|---|
| `S1_base`         | none                       | 1   | Baseline — parametric only |
| `S2_docs`         | QC docs RAG                | 1   | Domain knowledge augmentation |
| `S3_web`          | web search                 | 1   | General knowledge augmentation |
| `A1_agentic_full` | docs + web + feedback loop | ≤10 | Self-correction; logs each turn for the T1...T10 success curve |

The agentic condition writes one row per turn into the `turns` table so the cumulative-success-by-turn figure can be derived after a batch run completes.

## What's not yet built

- **Real evaluation pipeline** (backtest / trade / judge). Today's evaluator only runs `ast.parse()` for the compile stage; the other three stages return `None` and require the QC LEAN integration that's a separate workstream.
- **QC docs RAG** (S2_docs is recognized but emits no tool today).
- **Web search wiring** (S3_web emits the provider-native tool spec via `conditions/builder.py` but the Anthropic web_search server tool requires the right SDK version and the OpenAI/Gemini paths drop the tool spec).
- **Pricing rates** (`harness/pricing.py` PRICING dict is intentionally seeded with `None`; `cost_usd()` will refuse to compute until verified rates are filled in).
