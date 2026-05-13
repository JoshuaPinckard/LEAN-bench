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
