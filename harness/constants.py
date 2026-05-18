"""Locked, shared enumerations for LEAN-Bench.

Anything in this module is **frozen** at v1 of the experiment. Any change to
values here requires re-judging all prior runs — bump `JUDGE_VERSION` in
harness/judge.py whenever this file changes.
"""

from __future__ import annotations

# Locked failure-mode taxonomy. JSON-stored on `calls.failure_mode` as a list
# (first element is treated as the primary failure mode for analysis).
FAILURE_MODES: tuple[str, ...] = (
    "compilation_error",
    "runtime_error",
    "hallucinated_api",
    "no_trades_placed",
    "wrong_indicator",
    "wrong_universe",
    "logic_error",
    "threshold_miss",
    "incomplete_implementation",
    "timeout",
    "malformed_output",
    "none",
)

# Operational descriptions used in the judge system prompt and (optionally)
# surfaced in tooltips. Keep tight — these are reviewer-facing.
FAILURE_MODE_DESCRIPTIONS: dict[str, str] = {
    "compilation_error":         "Code does not compile or has syntax errors.",
    "runtime_error":             "Code compiles but crashes during backtest.",
    "hallucinated_api":          "Code references LEAN methods or classes that don't exist.",
    "no_trades_placed":          "Code runs cleanly but never trades.",
    "wrong_indicator":           "Uses an incorrect indicator or miscalculates one.",
    "wrong_universe":            "Trades the wrong assets or fails to select the intended universe.",
    "logic_error":               "Trades occur but strategy logic doesn't match the prompt's intent.",
    "threshold_miss":            "All requirements met but performance threshold not achieved (metric_threshold_required only).",
    "incomplete_implementation": "Code stops short of fully implementing the prompt.",
    "timeout":                   "Generation or backtest exceeded the time budget.",
    "malformed_output":          "Model response could not be parsed into a code block.",
    "none":                      "No failure; model succeeded.",
}


# Interpretation strictness values (prompts.interpretation_strictness).
INTERPRETATION_STRICTNESS_VALUES: tuple[str, ...] = (
    "unambiguous",
    "mild_variation",
    "broad_interpretation",
)

# Minimum judge_score that counts as a pass. The judge rubric in harness/judge.py
# anchors 0.7 as "mostly correct, core logic intact"; calls at/above this become
# judge_pass=True. Pass/fail thresholds feed pass_rate_matrix and the UI's
# headline metric, so changes here are a methodology change — bump JUDGE_VERSION
# in harness/judge.py and re-judge.
#
# Treated as an a priori rubric-semantic cutoff, NOT a tunable knob. Validation
# (scripts/validate_judge.py) evaluates judge credibility against humans; it
# does not re-fit this threshold. Any future change requires bumping
# JUDGE_VERSION and a full rejudge across affected calls.
JUDGE_PASS_THRESHOLD: float = 0.7


# --- Benchmark identity --------------------------------------------------

# Stamped onto every call. Bumping this is a benchmark methodology change.
BENCHMARK_VERSION: str = "LEAN-Bench-v1.0"


# --- LEAN execution pin --------------------------------------------------

# Pinned LEAN CLI package version. Mirrors the `lean==...` line in
# requirements.txt and is stamped into results .meta.json so every result row
# is traceable to the CLI that produced it.
LEAN_CLI_VERSION: str = "1.0.225"

# Pinned LEAN engine Docker image, by manifest digest (immutable — a tag like
# `latest` can move, a digest cannot). This is the actual executor: same code
# under a different image yields different Sharpe / trades / drawdown, which
# would disqualify a published benchmark.
#
# To change: pull the new image, capture its `quantconnect/lean@sha256:...`
# repo digest, update this constant AND run
# `lean config set engine-image <new-digest>` so local backtests match.
LEAN_ENGINE_IMAGE: str = (
    "quantconnect/lean@sha256:"
    "dc84a683464681b2e6c9579bc7655e16d4802380367c77004e40a6a504088bd7"
)


# --- Call status enum ----------------------------------------------------

# Persisted on calls.status. Lifecycle:
#   started   — row created, provider call not yet returned
#   completed — provider returned (with or without judge pass)
#   error     — provider/orchestrator threw; calls.error has the text
#   excluded  — design-time excluded (e.g. tooling-parity); never hits provider
CALL_STATUSES: tuple[str, ...] = ("started", "completed", "error", "excluded")


# --- Design-time cell exclusions ----------------------------------------

# (model_id, condition_id) pairs that are excluded from the main benchmark
# by design. Today's only exclusion is Gemini under tool-using conditions:
# we lack Gemini-compatible MCP docs retrieval and the agentic feedback loop
# is wired against Anthropic/OpenAI tool calling. Reported transparently as
# `status='excluded', excluded_reason='tooling_parity'` rather than hidden.
#
# Rows for excluded cells are still created (auditable grid) but never make
# a provider/judge call and are dropped from pass-rate denominators.
EXCLUDED_CELLS: dict[tuple[str, str], str] = {
    ("gemini-3.1-pro", "S3_web"):          "tooling_parity",
    ("gemini-3.1-pro", "A1_agentic_full"): "tooling_parity",
}


def excluded_reason_for(model_id: str, condition_id: str) -> str | None:
    """Return the exclusion reason for this cell, or None if not excluded."""
    return EXCLUDED_CELLS.get((model_id, condition_id))
