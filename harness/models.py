"""Frozen constants for LEAN-Bench v2.0 — proposal-faithful 2x2 factorial.

Four conditions implement a 2x2 factorial over two tools (docs retrieval D,
compiler feedback F) plus one baseline:

    C1_oneshot         one-shot, no tools                   (baseline)
    C2_docs            agent, D only                        (D=on, F=off)
    C3_compiler        agent, F only                        (D=off, F=on)
    C4_docs_compiler   agent, D + F                         (D=on,  F=on)

Frontier-model lineup is the existing v1.0 list of six (Anthropic +OpenAI +
Google). The proposal's 3-model example list (sonnet-4.5 / chatGPT-5.2 /
gemini-2.5-pro) is taken as illustrative; we keep the locked v1.0 6-model
sweep so prior provenance carries over.

Imported by every other module so there is exactly one source of truth for the
model list, condition definitions, failure taxonomy, and source distribution.
"""

from __future__ import annotations

import os

FROZEN_DATE = "2026-05-22"

# --- Models ---------------------------------------------------------------

# friendly name -> (provider, pinned API string, model_family)
MODELS_FROZEN: dict[str, dict[str, str]] = {
    "claude-opus-4.7":   {"provider": "anthropic", "model_id": "claude-opus-4-7",        "model_family": "claude"},
    "claude-opus-4.6":   {"provider": "anthropic", "model_id": "claude-opus-4-6",        "model_family": "claude"},
    "claude-sonnet-4.6": {"provider": "anthropic", "model_id": "claude-sonnet-4-6",      "model_family": "claude"},
    "claude-haiku-4.5":  {"provider": "anthropic", "model_id": "claude-haiku-4-5-20251001", "model_family": "claude"},
    "gpt-5.5":           {"provider": "openai",    "model_id": "gpt-5.5-2026-04-23",     "model_family": "gpt"},
    "gpt-5.4":           {"provider": "openai",    "model_id": "gpt-5.4-2026-03-05",     "model_family": "gpt"},
    "gpt-5.4-mini":      {"provider": "openai",    "model_id": "gpt-5.4-mini-2026-03-17", "model_family": "gpt"},
    "gpt-5.4-nano":      {"provider": "openai",    "model_id": "gpt-5.4-nano-2026-03-17", "model_family": "gpt"},
    "gpt-4.1-mini":      {"provider": "openai",    "model_id": "gpt-4.1-mini",           "model_family": "gpt"},
    "gemini-3.1-pro":    {"provider": "google",    "model_id": "gemini-3.1-pro-preview", "model_family": "gemini"},
}

# --- Run-count + turn defaults ------------------------------------------
#
# Proposal §Statistical Variance: N=5 for the single-shot baseline (C1),
# N=3 for every agent pipeline (C2-C4). T=24 turns for every agent
# condition. These are the publication defaults; env overrides exist so
# smoke tests can run cheaply without touching code.
DEFAULT_MAX_TURNS_AGENT: int = int(os.environ.get("LEANBENCH_MAX_TURNS", "24"))
N_BASELINE_DEFAULT:      int = int(os.environ.get("LEANBENCH_N_BASELINE", "5"))
N_AGENT_DEFAULT:         int = int(os.environ.get("LEANBENCH_N_AGENT", "3"))


# --- Conditions -----------------------------------------------------------
#
# 2x2 factorial (D × F) + one baseline. Each tuple of (tool_docs_retrieval,
# tool_compiler_feedback) isolates a single factor. C1 is the no-tool
# reference point: it isolates "more attempts" via N replication.
CONDITIONS: dict[str, dict] = {
    "C1_oneshot": {
        "display_name": "One-shot, no tools",
        "tools": [],
        "max_turns": 1,
        "default_attempts": N_BASELINE_DEFAULT,
        "tool_docs_retrieval": False,
        "tool_compiler_feedback": False,
        # Legacy column kept for storage back-compat (was web search).
        "tool_web_search": False,
        "tool_agentic_loop": False,
        "semantics": (
            "Proposal Category 1. Single provider call, no tool augmentation. "
            f"N={N_BASELINE_DEFAULT} replicate samples for variance accounting."
        ),
    },
    "C2_docs": {
        "display_name": "Agent + docs retrieval",
        "tools": ["qc_docs_retrieve"],
        "max_turns": DEFAULT_MAX_TURNS_AGENT,
        "default_attempts": N_AGENT_DEFAULT,
        "tool_docs_retrieval": True,
        "tool_compiler_feedback": False,
        "tool_web_search": False,
        "tool_agentic_loop": True,
        "semantics": (
            "Proposal Category 2. Agent with frozen lean_rag retrieval. Tool "
            "input is a string query; output is 5 chunks per the proposal "
            "spec. Max T=24 turns of iteration."
        ),
    },
    "C3_compiler": {
        "display_name": "Agent + LEAN compiler feedback",
        "tools": ["lean_backtest"],
        "max_turns": DEFAULT_MAX_TURNS_AGENT,
        "default_attempts": N_AGENT_DEFAULT,
        "tool_docs_retrieval": False,
        "tool_compiler_feedback": True,
        "tool_web_search": False,
        "tool_agentic_loop": True,
        "semantics": (
            "Proposal Category 3. Agent with lean_backtest_tool feedback. "
            "Tool runs Docker-pinned LEAN and returns a filtered log "
            "(ERROR::, Log::, ORDERS_PLACED:N, etc.). Max T=24 turns."
        ),
    },
    "C4_docs_compiler": {
        "display_name": "Agent + docs retrieval + LEAN compiler feedback",
        "tools": ["qc_docs_retrieve", "lean_backtest"],
        "max_turns": DEFAULT_MAX_TURNS_AGENT,
        "default_attempts": N_AGENT_DEFAULT,
        "tool_docs_retrieval": True,
        "tool_compiler_feedback": True,
        "tool_web_search": False,
        "tool_agentic_loop": True,
        "semantics": (
            "Proposal Category 4. Agent with BOTH lean_rag retrieval AND "
            "lean_backtest_tool feedback. Max T=24 turns."
        ),
    },
}

# Ordered tuple used by anything that needs a canonical iteration order.
CONDITION_ORDER: tuple[str, ...] = (
    "C1_oneshot",
    "C2_docs",
    "C3_compiler",
    "C4_docs_compiler",
)


# --- Sampling ------------------------------------------------------------
#
# N=5 baseline replicates, N=3 agent replicates. Variance-subset config kept
# from v1.0 for back-compat with existing analysis scripts; conditions
# updated to v2.0 IDs.
MAIN_GRID_TRIALS = 1
VARIANCE_SUBSET_TRIALS = N_AGENT_DEFAULT
VARIANCE_SUBSET_PROMPT_COUNT = 100
VARIANCE_SUBSET_CONDITIONS = ("C1_oneshot", "C4_docs_compiler")


# --- Failure taxonomy (mirrors v1.0; the proposal's pipeline still groups
# failures into compile / runtime / trade / semantic) ---------------------

FAILURE_TAXONOMY: dict[str, dict[str, str]] = {
    "compile_error": {
        "qc_api_hallucination": "Calling a nonexistent QC method/class",
        "syntax_error":         "Python syntax error",
        "import_error":         "Wrong module or missing dependency",
    },
    "backtest_runtime_error": {
        "data_resolution_mismatch": "Asked for minute data, used daily",
        "lookahead_bias":           "Referenced future data",
        "universe_or_symbol_error": "Invalid ticker, empty universe",
    },
    "trade_logic_error": {  # compiles + backtests but produces zero trades
        "missing_warmup":      "Indicator never warm",
        "condition_never_true": "Entry condition impossible",
        "missing_order_call":  "Signal generated, no SetHoldings/MarketOrder",
    },
    "schema_violation": {  # mechanically detected on the generated code
        "wrong_securities_type": "Code subscribes to the wrong asset class",
        "wrong_start_or_end_date": "SetStartDate/SetEndDate don't match prompt",
        "wrong_resolution": "Resolution argument doesn't match prompt schema",
    },
    "semantic_misalignment": {  # passes the mechanical checks but the judge says wrong
        "wrong_indicator":         "Asked RSI, used MACD",
        "wrong_direction":         "Long instead of short",
        "wrong_universe_or_asset": "Ran on AAPL when prompt said BTC",
    },
}

# Proposal §Evaluation Methods: 5 ordered pass/fail stages plus a
# continuous-metrics sidecar (no pass/fail).
PIPELINE_STAGES: tuple[str, ...] = (
    "compile",          # AST parse + LEAN compile (when backtest runs)
    "runtime",          # backtest executes the date range without crashing
    "trade",            # >=1 order placed
    "schema",           # mechanical adherence to prompt schema fields
    "judge",            # dual-judge semantic faithfulness
)


# --- Prompt curation targets --------------------------------------------
#
# Proposal §Prompt Curation: ~500-1000 hand-written prompts classified along
# (asset_class, signal_type). We keep the existing v1.0 source-distribution
# targets so the curated set carries over.

TARGET_PROMPT_COUNT = 1000

SOURCE_DISTRIBUTION_TARGETS: dict[str, tuple[int, int]] = {
    "qc_forum":      (250, 25),
    "qc_docs":       (100, 10),
    "reddit":        (200, 20),
    "stackexchange": (150, 15),
    "github":        (150, 15),
    "tradingview":   (50,  5),
    "original":      (100, 10),
}

DIFFICULTY_DISTRIBUTION: dict[str, int] = {
    "easy":   40,
    "medium": 35,
    "hard":   25,
}

POST_CUTOFF_DATE = "2025-12-01"

# --- Defaults ------------------------------------------------------------

DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOP_P = 1.0
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_STARTING_CASH = 100_000


def default_attempts_for(condition_id: str) -> int:
    """Proposal-anchored replicate count for this condition.

    C1 baseline = N=5; agent conditions = N=3. Overridden by env at module
    load (LEANBENCH_N_BASELINE / LEANBENCH_N_AGENT).
    """
    cond = CONDITIONS.get(condition_id)
    if cond is None:
        raise KeyError(f"Unknown condition_id={condition_id!r}")
    return int(cond["default_attempts"])
