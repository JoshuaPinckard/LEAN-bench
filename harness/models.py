"""Frozen constants for LEAN-Bench. Set once on Day 1 and never mutated.

Imported by every other module so there is exactly one source of truth for the
model list, condition definitions, failure taxonomy, and source distribution.
"""

from __future__ import annotations

FROZEN_DATE = "2026-05-09"

# --- Models ---------------------------------------------------------------

# friendly name -> (provider, pinned API string, model_family)
MODELS_FROZEN: dict[str, dict[str, str]] = {
    "claude-opus-4.7":   {"provider": "anthropic", "model_id": "claude-opus-4-7",        "model_family": "claude"},
    "claude-opus-4.6":   {"provider": "anthropic", "model_id": "claude-opus-4-6",        "model_family": "claude"},
    "claude-sonnet-4.6": {"provider": "anthropic", "model_id": "claude-sonnet-4-6",      "model_family": "claude"},
    "gpt-5.5":           {"provider": "openai",    "model_id": "gpt-5.5-2026-04-23",     "model_family": "gpt"},
    "gpt-5.4":           {"provider": "openai",    "model_id": "gpt-5.4-2026-03-05",     "model_family": "gpt"},
    "gemini-3.1-pro":    {"provider": "google",    "model_id": "gemini-3.1-pro-preview", "model_family": "gemini"},
}

# --- Conditions -----------------------------------------------------------

# 3 isolated single-turn conditions for clean attribution + 1 cumulative
# agentic condition for headline numbers. Ablations are derived comparisons
# between conditions, not separate runs.
# Methodology note on tool budgets:
#   - max_turns is hard-capped at the orchestrator level (10 for A1, 1 elsewhere).
#   - qc_docs_max_uses is hard-capped at the MCP server we own (5 per turn);
#     applies uniformly to any provider that speaks MCP. Gemini gets context
#     injection instead — a disclosed methodology limitation.
#   - web search is intentionally NOT capped. Each provider's native tool
#     decides how many searches to run; we log observed counts from
#     ProviderResponse.tools_called and report the distribution honestly. A
#     uniform numeric cap is unenforceable across providers (Anthropic has
#     max_uses, OpenAI/Gemini do not), so capping would be asymmetric and
#     less defensible than reporting actual behavior. Framing for the paper:
#     "real-world deployment uses provider-native tool behavior; capping
#     artificially would not reflect production use."
CONDITIONS: dict[str, dict] = {
    "S1_base": {
        "display_name": "Single-turn baseline",
        "tools": [],
        "max_turns": 1,
        "tool_docs_retrieval": False,
        "tool_web_search": False,
        "tool_agentic_loop": False,
        "qc_docs_max_uses": 0,
        "semantics": "Prompt + LEAN API description (~2K-token system prompt). No web. No retrieval. No iteration. Pure parametric knowledge.",
    },
    "S2_docs": {
        "display_name": "Single-turn + QC docs retrieval",
        "tools": ["qc_docs"],
        "max_turns": 1,
        "tool_docs_retrieval": True,
        "tool_web_search": False,
        "tool_agentic_loop": False,
        "qc_docs_max_uses": 5,
        "semantics": "S1 + retrieval over QuantConnect documentation corpus. Up to 5 QC docs retrievals per turn before the single final code block.",
    },
    "S3_web": {
        "display_name": "Single-turn + web search",
        "tools": ["web_search"],
        "max_turns": 1,
        "tool_docs_retrieval": False,
        "tool_web_search": True,
        "tool_agentic_loop": False,
        "qc_docs_max_uses": 0,
        "semantics": "S1 + provider-native web search; observed search counts logged per call. No QC docs retrieval.",
    },
    "A1_agentic_full": {
        "display_name": "Agentic full stack",
        "tools": ["qc_docs", "web_search", "agentic_loop"],
        "max_turns": 10,
        "tool_docs_retrieval": True,
        "tool_web_search": True,
        "tool_agentic_loop": True,
        "qc_docs_max_uses": 5,
        "semantics": "S2 + S3 tools + agentic loop: after each code submission, LEAN harness runs Compile -> Backtest -> Trade checks and returns structured feedback. Model may iterate up to 10 turns. QC docs retrievals capped at 5 per turn; web searches uncapped (observed counts reported). Headline leaderboard condition.",
    },
}

# --- Sampling ------------------------------------------------------------

MAIN_GRID_TRIALS = 1                    # N=1 for the 24K main grid
VARIANCE_SUBSET_TRIALS = 4              # pass^4 (tau-bench style)
VARIANCE_SUBSET_PROMPT_COUNT = 100      # stratified by difficulty
VARIANCE_SUBSET_CONDITIONS = ("S1_base", "A1_agentic_full")

# --- Failure taxonomy (12 leaves, 4 top-level pre-registered) -----------

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
    "semantic_misalignment": {  # trades but wrong strategy per judge
        "wrong_indicator":         "Asked RSI, used MACD",
        "wrong_direction":         "Long instead of short",
        "wrong_universe_or_asset": "Ran on AAPL when prompt said BTC",
    },
}

PIPELINE_STAGES = ("compile", "backtest", "trade", "judge")

# --- Prompt curation targets --------------------------------------------

TARGET_PROMPT_COUNT = 1000

# source -> (count, percent)
SOURCE_DISTRIBUTION_TARGETS: dict[str, tuple[int, int]] = {
    "qc_forum":      (250, 25),
    "qc_docs":       (100, 10),
    "reddit":        (200, 20),
    "stackexchange": (150, 15),
    "github":        (150, 15),  # README descriptions only, NOT code
    "tradingview":   (50,  5),
    "original":      (100, 10),  # authored by Pinckard/Raissi group, post-2026
}

DIFFICULTY_DISTRIBUTION: dict[str, int] = {
    "easy":   40,
    "medium": 35,
    "hard":   25,
}

# Hard cutoff for is_post_cutoff flag (contamination control).
POST_CUTOFF_DATE = "2025-12-01"

# --- Defaults ------------------------------------------------------------

DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOP_P = 1.0
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_STARTING_CASH = 100_000
