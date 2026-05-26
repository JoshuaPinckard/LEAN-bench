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
from harness.constants import BENCHMARK_VERSION, JUDGE_PASS_THRESHOLD
from harness.models import CONDITIONS, FROZEN_DATE, MODELS_FROZEN
from harness.orchestrator import (
    FROZEN_PROMPT_SET_PATH, FrozenPromptSetMismatch, SYSTEM_PROMPTS, run_grid,
)
from harness.prompt_freeze import load_frozen
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
        for col in ("tickers", "indicators", "curator_modified_fields"):
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
    for col in ("tickers", "indicators", "curator_modified_fields"):
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
        # derive legacy bool: any non-"unambiguous" value implies underspecification
        implementation_underspecified=prompt_in.interpretation_strictness != "unambiguous",
        underspecification_notes=prompt_in.underspecification_notes,
        excluded_from_benchmark=prompt_in.excluded_from_benchmark,
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


# ---- Distribution dashboard -------------------------------------------

@app.get("/api/stats/distribution")
def stats_distribution() -> dict:
    """Live count breakdowns across all curated prompts (excluding adhoc and
    excluded_from_benchmark rows). Used by the Distribution dashboard tab."""
    return get_store().compute_distribution_stats()


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
    if req.attempts is not None and req.attempts < 1:
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

    try:
        results = await run_grid(
            store=store,
            prompt_id=prompt_id,
            prompt_text=req.prompt_text,
            models=req.models,
            conditions=req.conditions,
            attempts=req.attempts,
            max_turns=req.max_turns,
        )
    except FrozenPromptSetMismatch as exc:
        # 409 Conflict: the DB state and the frozen artifact disagree.
        # No provider call fired; this is the freeze guard doing its job.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        # v2: structured per-turn tool events (RAG + compiler). Decoded once
        # here so the frontend never has to JSON.parse a string column.
        raw_events = t.get("tool_events_json")
        if raw_events:
            try:
                t["tool_events"] = json.loads(raw_events)
            except (TypeError, json.JSONDecodeError):
                t["tool_events"] = []
        else:
            t["tool_events"] = []
    c["turns"] = turns

    # v2.1 monitoring aggregate: 'transcript' carries everything the Transcript
    # tab needs without traversing all 24 rounds in the browser.
    #
    # Event taxonomy (per harness/orchestrator.py:_summarise_turn_events):
    #   rag_retrieve     — emitted for {R}-handshake RAG calls (C2/C4 only)
    #   code_attempt     — emitted for every model code submission
    #   lean_backtest    — emitted for every code attempt regardless of cond
    #                      (carries `feedback_shown_to_model` flag to
    #                      distinguish C3/C4 from C1/C2 gate-only runs)
    #   schema_check     — emitted when the schema gate ran (i.e., trade
    #                      passed). Carries the violation list.
    #   judge            — emitted when the judge ran (i.e., schema passed).
    #                      Carries per-judge scores + reasoning.
    #   invalid_response — emitted when the parser couldn't classify the
    #                      model's response as either RAG or code.
    #
    # Legacy event name `qc_docs_retrieve` (v2.0) is still recognised for
    # rows written before the rename.
    rag_events:     list[dict] = []
    code_events:    list[dict] = []
    compile_events: list[dict] = []
    schema_events:  list[dict] = []
    judge_events:   list[dict] = []
    invalid_events: list[dict] = []
    final_turn: dict | None = None
    for t in turns:
        for ev in t["tool_events"]:
            ev_with_idx = {"turn_index": t["turn_index"], **ev}
            name = ev["name"]
            if name in ("rag_retrieve", "qc_docs_retrieve"):
                rag_events.append(ev_with_idx)
            elif name == "code_attempt":
                code_events.append(ev_with_idx)
            elif name == "lean_backtest":
                compile_events.append(ev_with_idx)
            elif name == "schema_check":
                schema_events.append(ev_with_idx)
            elif name == "judge":
                judge_events.append(ev_with_idx)
            elif name == "invalid_response":
                invalid_events.append(ev_with_idx)
        if t.get("is_final_turn"):
            final_turn = t
    if final_turn is None and turns:
        # Fallback: pick the last turn we recorded.
        final_turn = turns[-1]

    # Per-turn user message: every turn carries its own assembled prompt
    # (labeled context history + original prompt). Surface it directly on
    # the turn dict so the UI can render the evolution turn-by-turn.
    for t in turns:
        msgs = t.get("prompt_messages") or []
        if msgs and isinstance(msgs, list):
            first = msgs[0]
            if isinstance(first, dict) and isinstance(first.get("content"), str):
                t["user_message"] = first["content"]
            else:
                t["user_message"] = None
        else:
            t["user_message"] = None

    # Decode the JSON schema_violations column for the UI.
    sv_raw = c.get("schema_violations")
    if isinstance(sv_raw, str) and sv_raw:
        try:
            c["schema_violations_parsed"] = json.loads(sv_raw)
        except (TypeError, json.JSONDecodeError):
            c["schema_violations_parsed"] = None
    else:
        c["schema_violations_parsed"] = sv_raw if isinstance(sv_raw, list) else None

    # v2.1: the initial user message is just the raw prompt text — the
    # orchestrator no longer appends a schema block (curator-pinned dates /
    # securities / resolution stay HIDDEN from the model by design). For
    # agentic conditions we can also pull it from turns[0] verbatim, which
    # includes any context-history block that was rendered (empty on turn 0).
    initial_user_message: str | None = None
    if turns:
        first_msgs = turns[0].get("prompt_messages") or []
        if first_msgs:
            first = first_msgs[0]
            content = first.get("content") if isinstance(first, dict) else None
            if isinstance(content, str):
                initial_user_message = content
    if initial_user_message is None:
        prompt_row = store.get_prompt(c["prompt_id"])
        if prompt_row:
            initial_user_message = (
                prompt_row.get("reformulated_text")
                or prompt_row.get("original_text")
                or ""
            )

    # v2.1 has per-condition system prompts. Look up by the call's condition;
    # fall back to C1 if a legacy row carries a missing/unknown condition_id.
    cond_id = c.get("condition_id") or c.get("condition") or "C1_oneshot"
    system_prompt_text = SYSTEM_PROMPTS.get(cond_id) or SYSTEM_PROMPTS["C1_oneshot"]

    c["transcript"] = {
        "total_turns":          len(turns),
        "final_turn_index":     final_turn["turn_index"] if final_turn else None,
        "final_turn":           final_turn,
        # Per-event-type collections for the Transcript tab's grouped views.
        "rag_events":           rag_events,
        "code_events":          code_events,
        "compile_events":       compile_events,
        "schema_events":        schema_events,
        "judge_events":         judge_events,
        "invalid_events":       invalid_events,
        # Counters (also stored as columns on the call row, but echoed here
        # so the modal doesn't need two queries).
        "rag_count":            len(rag_events),
        "code_count":           len(code_events),
        "compile_count":        len(compile_events),
        "schema_count":         len(schema_events),
        "judge_count":          len(judge_events),
        "invalid_count":        len(invalid_events),
        # First-pass turn index per pipeline gate (None = never passed).
        # 0-indexed in storage; the UI renders +1 for human-friendly display.
        "first_pass": {
            "compile": c.get("first_pass_compile"),
            "runtime": c.get("first_pass_runtime"),
            "trade":   c.get("first_pass_trade"),
            "schema":  c.get("first_pass_schema"),
            "judge":   c.get("first_pass_judge"),
        },
        # Prompts the model saw verbatim. The sha is on the call row as
        # system_prompt_sha so the artifact can be cross-checked.
        "system_prompt":        system_prompt_text,
        "initial_user_message": initial_user_message,
    }
    return c


# ---- Stats ------------------------------------------------------------

@app.get("/api/stats", response_model=StatsResponse)
def stats() -> StatsResponse:
    store = get_store()
    matrix = store.pass_rate_matrix()
    # Surface the frozen prompt-set hash if the artifact exists. Don't fail
    # the stats endpoint if it doesn't (dev runs are valid without a freeze).
    prompt_set_sha = None
    if FROZEN_PROMPT_SET_PATH.exists():
        try:
            _, prompt_set_sha = load_frozen(FROZEN_PROMPT_SET_PATH)
        except Exception:
            prompt_set_sha = None
    return StatsResponse(
        total_spend_usd=store.total_cost_usd(),
        total_calls=store.call_count(),
        excluded_calls=store.excluded_count(),
        total_prompts=len(store.list_prompts()),
        frozen_date=FROZEN_DATE,
        benchmark_version=BENCHMARK_VERSION,
        judge_threshold=JUDGE_PASS_THRESHOLD,
        prompt_set_sha256=prompt_set_sha,
        spend_by_model=store.cost_by_model(),
        spend_by_condition=store.cost_by_condition(),
        pass_rate_matrix=[
            CellStat(
                model=row["model_id"],
                condition=row["condition_id"],
                n=row["n"],
                excluded=row["excluded"],
                pass_rate=row["pass_rate"],
                status=row["status"],
            )
            for row in matrix
        ],
    )


@app.get("/")
def root() -> dict:
    return {"app": "LEAN-Bench backend", "frozen_date": FROZEN_DATE, "docs": "/docs"}
