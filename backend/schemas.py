"""Pydantic request/response models for the FastAPI layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    difficulty: str = "medium"           # easy | medium | hard
    strategy_type: str | None = None
    qc_securities_type: str | None = None
    qc_universe_type: str | None = None
    qc_data_resolution: str | None = None
    qc_brokerage_model: str | None = None
    tickers: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    cash: int = 100_000
    expected_indicators: list[str] = Field(default_factory=list)
    expected_order_types: list[str] = Field(default_factory=list)
    trades_expected: bool = True
    curator_notes: str | None = None
    # provenance / control
    source: str = "original"
    source_creation_date: str | None = None
    source_license: str | None = None
    is_post_cutoff: bool = False
    leak_audit_status: str = "clean"


class PromptOut(PromptIn):
    prompt_id: str
    version: str
    original_text: str
    reformulated_text: str
    created_at: str


class PromptList(BaseModel):
    prompts: list[dict[str, Any]]
    total: int


# ---- Generate ---------------------------------------------------------

class GenerateRequest(BaseModel):
    prompt_id: str | None = None       # null means ad-hoc (auto-saved as adhoc-XXXX)
    prompt_text: str
    models: list[str]                   # friendly names from MODELS_FROZEN
    conditions: list[str]               # condition IDs from CONDITIONS
    attempts: int = 1                   # 4 for pass^4 mode


class CallResult(BaseModel):
    call_id: str
    model: str
    condition: str
    attempt: int
    status: str                         # completed | error | skipped
    generated_code: str | None
    response_text: str | None
    compile_pass: bool | None
    backtest_pass: bool | None
    trade_pass: bool | None
    judge_pass: bool | None
    overall_pass: bool | None
    failure_category_l1: str | None
    failure_category_l2: str | None
    cost_usd: float | None
    latency_ms: int
    input_tokens: int
    output_tokens: int
    turns_used: int
    error: str | None


class GenerateResponse(BaseModel):
    results: list[CallResult]


# ---- Stats ------------------------------------------------------------

class CellStat(BaseModel):
    model: str
    condition: str
    n: int
    pass_rate: float | None             # judge_pass rate; None if no calls


class StatsResponse(BaseModel):
    total_spend_usd: float
    total_calls: int
    total_prompts: int
    frozen_date: str
    spend_by_model: dict[str, float]
    spend_by_condition: dict[str, float]
    pass_rate_matrix: list[CellStat]
