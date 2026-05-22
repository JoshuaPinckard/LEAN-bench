"""Pydantic request/response models for the FastAPI layer."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---- Models / Conditions metadata -------------------------------------

class ModelInfo(BaseModel):
    friendly_name: str
    model_id: str
    provider: str
    model_family: str


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    frozen_date: str


class ConditionInfo(BaseModel):
    id: str
    display_name: str
    tools: list[str]
    max_turns: int
    semantics: str


class ConditionsResponse(BaseModel):
    conditions: list[ConditionInfo]


# ---- Prompts ----------------------------------------------------------

class PromptIn(BaseModel):
    """Fields a curator submits via the Prompts tab."""
    text: str
    strategy_type: str = "directional"    # directional|mean_reversion|derivatives|portfolio|execution|relative_value|other
    strategy_complexity: int = 2          # 1=easy|2=medium|3=hard
    api_complexity: int = 2               # 1=basic|2=intermediate|3=advanced
    # LEAN configuration
    securities_type: str = "equity"       # equity|option|multi_asset
    securities_type_detailed: str | None = None
    resolution: str = "daily"             # high_frequency|intraday|daily
    implementation_type: Literal[
        "lean_native", "custom_implementation", "external_data_required", "mixed"
    ] = "lean_native"
    indicators: list[str] = Field(default_factory=list)
    # universe
    universe_type: Literal[
        "single_asset", "multi_asset_specific", "index_components",
        "screened_universe", "custom_universe_logic"
    ] = "single_asset"
    universe_index: str | None = None       # SP500|NASDAQ100|RUSSELL2000|DOW30|SP400_MIDCAP|RUSSELL1000|other
    universe_index_other: str | None = None # freetext when universe_index="other"
    tickers: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    # evaluation
    evaluation_mode: Literal[
        "trade_required", "signal_required", "code_only", "metric_threshold_required"
    ] = "trade_required"
    interpretation_strictness: Literal[
        "unambiguous", "mild_variation", "broad_interpretation"
    ] = "unambiguous"
    underspecification_notes: str | None = None
    curator_notes: str | None = None
    excluded_from_benchmark: bool = False
    # provenance
    source: str = "original"
    source_url: str | None = None
    source_date: date | None = None
    leak_audit_status: str = "clean"
    # AI-assisted curation telemetry
    ai_prepopulated: bool = False
    curator_modified_fields: list[str] = Field(default_factory=list)


class SchemaAutofillRequest(BaseModel):
    prompt_text: str


class SchemaAutofillResponse(BaseModel):
    """All fields the AI populates on autofill. Frontend uses this as the
    snapshot to diff against on save (curator_modified_fields)."""
    strategy_type: str
    strategy_complexity: int
    api_complexity: int
    securities_type: str
    securities_type_detailed: str | None = None
    resolution: str
    implementation_type: str
    indicators: list[str] = Field(default_factory=list)
    universe_type: str
    universe_index: str | None = None
    tickers: list[str] = Field(default_factory=list)
    start_date: str
    end_date: str
    evaluation_mode: str
    interpretation_strictness: str   # unambiguous|mild_variation|broad_interpretation
    curator_notes: str

    @field_validator("strategy_complexity", "api_complexity")
    @classmethod
    def check_1_to_3(cls, v: int) -> int:
        if v not in (1, 2, 3):
            raise ValueError("must be 1, 2, or 3")
        return v


class PromptOut(PromptIn):
    prompt_id: str
    version: str
    original_text: str
    reformulated_text: str
    created_at: str


class PromptList(BaseModel):
    prompts: list[dict[str, Any]]
    total: int


# ---- Runs ---------------------------------------------------------------

class Run(BaseModel):
    """One evaluated run of generated code against the LEAN backtest engine."""
    run_id: str
    prompt_id: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    lean_engine_version: str | None = None
    lean_data_snapshot_hash: str | None = None
    generated_code: str | None = None
    compile_ok: bool | None = None
    backtest_ok: bool | None = None
    trades_count: int | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    cagr: float | None = None
    judge_score: float | None = None
    judge_reasoning: str | None = None
    judge_replication_index: int | None = None
    failure_mode: str | None = None        # populated post-evaluation
    market_regime: str | None = None       # populated post-enrichment
    human_validated: bool = False
    created_at: str | None = None


# ---- Generate ---------------------------------------------------------

class GenerateRequest(BaseModel):
    prompt_id: str | None = None       # null means ad-hoc (auto-saved as adhoc-XXXX)
    prompt_text: str
    models: list[str]                   # friendly names from MODELS_FROZEN
    conditions: list[str]               # condition IDs from CONDITIONS (C1..C5)
    # None means "use the proposal-anchored per-condition default" (N=5 for C1,
    # N=3 for agent conditions). Pass an int to override uniformly.
    attempts: int | None = None
    # None means "use the proposal-anchored per-condition default" (24 for
    # agent conditions, 1 for C1_oneshot). Pass an int to override the turn
    # limit for agentic conditions only — C1 stays pinned to 1 turn.
    max_turns: int | None = None

    @field_validator("max_turns")
    @classmethod
    def check_max_turns(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not (1 <= v <= 100):
            raise ValueError("max_turns must be between 1 and 100")
        return v


class CallResult(BaseModel):
    call_id: str
    model: str
    condition: str
    attempt: int
    status: str                         # started | completed | error | excluded
    excluded_reason: str | None = None  # populated iff status='excluded'
    generated_code: str | None
    response_text: str | None
    compile_pass: bool | None
    backtest_pass: bool | None
    trade_pass: bool | None
    schema_pass: bool | None = None     # v2 stage-4 mechanical schema check
    judge_pass: bool | None
    overall_pass: bool | None
    judge_score_a: float | None = None  # v2 dual-judge individual scores
    judge_score_b: float | None = None
    failure_category_l1: str | None = None
    failure_category_l2: str | None = None
    cost_usd: float | None
    latency_ms: int
    input_tokens: int
    output_tokens: int
    turns_used: int
    error: str | None
    judge_error: str | None = None


class GenerateResponse(BaseModel):
    results: list[CallResult]


# ---- Stats ------------------------------------------------------------

class CellStat(BaseModel):
    model: str
    condition: str
    n: int                              # NON-excluded rows (the denominator)
    excluded: int = 0                   # design-time excluded rows for this cell
    pass_rate: float | None             # judge_pass rate over n; None if no judged calls
    status: str | None = None           # 'excluded' iff every row in cell is excluded


class StatsResponse(BaseModel):
    total_spend_usd: float
    total_calls: int                    # attempted (non-excluded)
    excluded_calls: int = 0             # design-time excluded
    total_prompts: int
    frozen_date: str
    benchmark_version: str
    judge_threshold: float
    prompt_set_sha256: str | None = None
    spend_by_model: dict[str, float]
    spend_by_condition: dict[str, float]
    pass_rate_matrix: list[CellStat]
