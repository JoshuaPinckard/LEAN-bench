"""FastAPI HTTP wrapper around the harness/ Python core.

Run with:
    uvicorn backend.app:app --reload --port 8000

Reads .env at startup and bridges Vite-style keys (VITE_ANTHROPIC_API_KEY,
VITE_OPENAI_API_KEY, VITE_GEMINI_API_KEY) to the standard SDK env vars
(ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY) so the same .env file
works for both the Vue dev server and the Python backend during the
transition. Once the Vue UI is fully backend-routed, the VITE_ keys can
(and should) be removed.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Make `harness` importable when running via `uvicorn backend.app:app` from
# the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env")

# Bridge Vite -> SDK env names BEFORE importing any provider client.
for vite, std in (
    ("VITE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    ("VITE_OPENAI_API_KEY",    "OPENAI_API_KEY"),
    ("VITE_GEMINI_API_KEY",    "GEMINI_API_KEY"),
):
    if not os.environ.get(std) and os.environ.get(vite):
        os.environ[std] = os.environ[vite]

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.schemas import (
    CallResult, CellStat, ConditionInfo, ConditionsResponse,
    GenerateRequest, GenerateResponse, ModelInfo, ModelsResponse,
    PromptIn, SchemaAutofillRequest, SchemaAutofillResponse, StatsResponse,
)
from harness.models import CONDITIONS, FROZEN_DATE, MODELS_FROZEN
from harness.orchestrator import run_grid
from harness.schema_fill import SchemaAutofillError, fill_schema
from harness.storage import Store


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_store()  # warm up the connection / migrations
    yield
    if _store is not None:
        _store.close()


app = FastAPI(title="LEAN-Bench Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Models / Conditions metadata --------------------------------------

@app.get("/api/models", response_model=ModelsResponse)
def list_models() -> ModelsResponse:
    return ModelsResponse(
        frozen_date=FROZEN_DATE,
        models=[
            ModelInfo(
                friendly_name=name,
                model_id=info["model_id"],
                provider=info["provider"],
                model_family=info["model_family"],
            )
            for name, info in MODELS_FROZEN.items()
        ],
    )


@app.get("/api/conditions", response_model=ConditionsResponse)
def list_conditions() -> ConditionsResponse:
    return ConditionsResponse(
        conditions=[
            ConditionInfo(
                id=cid,
                display_name=cdef["display_name"],
                tools=cdef["tools"],
                max_turns=cdef["max_turns"],
                semantics=cdef["semantics"],
            )
            for cid, cdef in CONDITIONS.items()
        ],
    )


# ---- Prompts CRUD ------------------------------------------------------

@app.get("/api/prompts")
def list_prompts(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str | None = None,
) -> dict:
    store = get_store()
    rows, total = store.search_prompts(search=search, limit=limit, offset=offset)
    # Decode JSON list columns for the frontend.
    for r in rows:
        for col in ("tickers", "indicators", "failure_mode", "curator_modified_fields"):
            if r.get(col):
                try:
                    r[col] = json.loads(r[col])
                except (TypeError, json.JSONDecodeError):
                    r[col] = []
            else:
                r[col] = []
    return {"prompts": rows, "total": total}


@app.get("/api/prompts/{prompt_id}")
def get_prompt(prompt_id: str) -> dict:
    store = get_store()
    p = store.get_prompt(prompt_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
    for col in ("tickers", "indicators", "failure_mode", "curator_modified_fields"):
        if p.get(col):
            try:
                p[col] = json.loads(p[col])
            except (TypeError, json.JSONDecodeError):
                p[col] = []
        else:
            p[col] = []
    return p


def _prompt_fields(prompt_in: PromptIn) -> dict:
    """Map a PromptIn to the column kwargs add_prompt expects."""
    return dict(
        version="1.0.0",
        original_text=prompt_in.text,
        original_url=prompt_in.source_url,
        reformulated_text=prompt_in.text,
        source=prompt_in.source,
        strategy_type=prompt_in.strategy_type,
        strategy_complexity=prompt_in.strategy_complexity,
        api_complexity=prompt_in.api_complexity,
        securities_type=prompt_in.securities_type,
        securities_type_detailed=prompt_in.securities_type_detailed,
        resolution=prompt_in.resolution,
        implementation_type=prompt_in.implementation_type,
        indicators=prompt_in.indicators,
        universe_type=prompt_in.universe_type,
        universe_index=prompt_in.universe_index,
        universe_index_other=prompt_in.universe_index_other,
        tickers=prompt_in.tickers,
        start_date=prompt_in.start_date,
        end_date=prompt_in.end_date,
        evaluation_mode=prompt_in.evaluation_mode,
        interpretation_strictness=prompt_in.interpretation_strictness,
        # derive legacy bool from the new int field
        implementation_underspecified=prompt_in.interpretation_strictness > 0,
        underspecification_notes=prompt_in.underspecification_notes,
        failure_mode=prompt_in.failure_mode,
        failure_notes=prompt_in.failure_notes,
        source_date=str(prompt_in.source_date) if prompt_in.source_date else None,
        is_post_cutoff=False,    # legacy NOT NULL column; UI no longer surfaces this
        ai_prepopulated=prompt_in.ai_prepopulated,
        curator_modified_fields=prompt_in.curator_modified_fields,
        leak_audit_status=prompt_in.leak_audit_status,
        leak_audit_notes=prompt_in.curator_notes,
    )


@app.post("/api/prompts")
def create_prompt(prompt_in: PromptIn) -> dict:
    store = get_store()
    prompt_id = store.next_prompt_id()
    store.add_prompt(prompt_id=prompt_id, **_prompt_fields(prompt_in))
    return get_prompt(prompt_id)


@app.patch("/api/prompts/{prompt_id}")
def update_prompt(prompt_id: str, prompt_in: PromptIn) -> dict:
    store = get_store()
    if store.get_prompt(prompt_id) is None:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
    store.add_prompt(prompt_id=prompt_id, **_prompt_fields(prompt_in))  # idempotent upsert
    return get_prompt(prompt_id)


@app.delete("/api/prompts/{prompt_id}")
def delete_prompt(prompt_id: str) -> dict:
    store = get_store()
    if store.get_prompt(prompt_id) is None:
        raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
    n_calls = store.delete_prompt(prompt_id)
    return {"deleted": prompt_id, "deleted_calls": n_calls}


# ---- Schema autofill --------------------------------------------------

@app.post("/api/schema/autofill", response_model=SchemaAutofillResponse)
async def schema_autofill(req: SchemaAutofillRequest) -> SchemaAutofillResponse:
    text = req.prompt_text.strip()
    if len(text) < 20:
        raise HTTPException(
            status_code=400,
            detail="prompt_text must be at least 20 characters to autofill.",
        )
    try:
        data = await fill_schema(text)
    except SchemaAutofillError as exc:
        # Log server-side, return 500 with the parse error per the spec.
        print(f"[schema_autofill] {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail=f"Autofill failed: {exc}") from exc
    return SchemaAutofillResponse(**data)


# ---- Generate ----------------------------------------------------------

@app.post("/api/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    if not req.prompt_text.strip():
        raise HTTPException(status_code=400, detail="prompt_text is required")
    if not req.models:
        raise HTTPException(status_code=400, detail="at least one model required")
    if not req.conditions:
        raise HTTPException(status_code=400, detail="at least one condition required")
    if req.attempts < 1:
        raise HTTPException(status_code=400, detail="attempts must be >= 1")

    unknown_models = [m for m in req.models if m not in MODELS_FROZEN]
    if unknown_models:
        raise HTTPException(status_code=400, detail=f"unknown models: {unknown_models}")
    unknown_conds = [c for c in req.conditions if c not in CONDITIONS]
    if unknown_conds:
        raise HTTPException(status_code=400, detail=f"unknown conditions: {unknown_conds}")

    store = get_store()

    if req.prompt_id is None:
        adhoc_id = f"adhoc-{uuid.uuid4().hex[:8]}"
        store.add_prompt(
            prompt_id=adhoc_id,
            version="adhoc",
            original_text=req.prompt_text,
            reformulated_text=req.prompt_text,
            source="adhoc",
            difficulty="medium",
            trades_expected=True,
            is_post_cutoff=False,
            leak_audit_status="adhoc",
        )
        prompt_id = adhoc_id
    else:
        if store.get_prompt(req.prompt_id) is None:
            raise HTTPException(
                status_code=404, detail=f"prompt_id={req.prompt_id} not found"
            )
        prompt_id = req.prompt_id

    results = await run_grid(
        store=store,
        prompt_id=prompt_id,
        prompt_text=req.prompt_text,
        models=req.models,
        conditions=req.conditions,
        attempts=req.attempts,
    )
    return GenerateResponse(results=[CallResult(**r) for r in results])


# ---- Calls ------------------------------------------------------------

@app.get("/api/calls/{call_id}")
def get_call(call_id: str) -> dict:
    store = get_store()
    c = store.get_call(call_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    turns = store.turns_for_call(call_id)
    # Decode JSON columns for inspection in the UI.
    for col in ("retrieval_queries", "retrieval_doc_ids",
                "web_search_queries", "web_search_result_urls"):
        for t in turns:
            if t.get(col):
                try:
                    t[col] = json.loads(t[col])
                except (TypeError, json.JSONDecodeError):
                    pass
    for t in turns:
        if t.get("prompt_messages_json"):
            try:
                t["prompt_messages"] = json.loads(t["prompt_messages_json"])
            except (TypeError, json.JSONDecodeError):
                t["prompt_messages"] = None
    c["turns"] = turns
    return c


# ---- Stats ------------------------------------------------------------

@app.get("/api/stats", response_model=StatsResponse)
def stats() -> StatsResponse:
    store = get_store()
    matrix = store.pass_rate_matrix()
    return StatsResponse(
        total_spend_usd=store.total_cost_usd(),
        total_calls=store.call_count(),
        total_prompts=len(store.list_prompts()),
        frozen_date=FROZEN_DATE,
        spend_by_model=store.cost_by_model(),
        spend_by_condition=store.cost_by_condition(),
        pass_rate_matrix=[
            CellStat(
                model=row["model_id"],
                condition=row["condition_id"],
                n=row["n"],
                pass_rate=row["pass_rate"],
            )
            for row in matrix
        ],
    )


@app.get("/")
def root() -> dict:
    return {"app": "LEAN-Bench backend", "frozen_date": FROZEN_DATE, "docs": "/docs"}
