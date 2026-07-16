"""Locked, shared enumerations for LEAN-Bench v2.0 (proposal-faithful build).

Anything in this module is **frozen** at v2 of the experiment. Any change to
values here requires re-judging all prior runs — bump `JUDGE_VERSION` in
harness/judge.py whenever this file changes.

v2.0 vs v1.0 deltas:
- 4-condition factorial (C1..C4) — one baseline plus a 2x2 D × F factorial.
- Dual-judge semantic check (claude-sonnet-4-6 + gpt-5.4, averaged).
- 5-stage pipeline: compile -> runtime -> trade -> schema -> judge, with
  continuous practitioner metrics reported as a sidecar.
- EXCLUDED_CELLS is empty: the proposal-faithful tool wiring uses lean_rag
  + lean_backtest_tool as native function-call tools, which all three
  providers support.
"""

from __future__ import annotations

from pathlib import Path

# Path to the frozen prompt-set artifact stamped into every benchmark run.
# Lives here (rather than in harness/orchestrator.py) so /api/stats and other
# lightweight endpoints can import it without dragging in provider SDKs.
FROZEN_PROMPT_SET_PATH: Path = Path("results/frozen/prompt_set_v1.json")

# Locked failure-mode taxonomy. JSON-stored on `calls.failure_mode` as a list
# (first element is treated as the primary failure mode for analysis).
FAILURE_MODES: tuple[str, ...] = (
    "compilation_error",
    "runtime_error",
    "hallucinated_api",
    "no_trades_placed",
    "schema_violation",
    "wrong_indicator",
    "wrong_universe",
    "logic_error",
    "threshold_miss",
    "incomplete_implementation",
    "timeout",
    "malformed_output",
    "none",
)

FAILURE_MODE_DESCRIPTIONS: dict[str, str] = {
    "compilation_error":         "Code does not compile or has syntax errors.",
    "runtime_error":             "Code compiles but crashes during backtest.",
    "hallucinated_api":          "Code references LEAN methods or classes that don't exist.",
    "no_trades_placed":          "Code runs cleanly but never trades.",
    "schema_violation":          "Mechanical schema check failed (wrong asset class / start / end / resolution).",
    "wrong_indicator":           "Uses an incorrect indicator or miscalculates one.",
    "wrong_universe":            "Trades the wrong assets or fails to select the intended universe.",
    "logic_error":               "Trades occur but strategy logic doesn't match the prompt's intent.",
    "threshold_miss":            "All requirements met but performance threshold not achieved (metric_threshold_required only).",
    "incomplete_implementation": "Code stops short of fully implementing the prompt.",
    "timeout":                   "Generation or backtest exceeded the time budget.",
    "malformed_output":          "Model response could not be parsed into a code block.",
    "none":                      "No failure; model succeeded.",
}


INTERPRETATION_STRICTNESS_VALUES: tuple[str, ...] = (
    "unambiguous",
    "mild_variation",
    "broad_interpretation",
)


# Minimum aggregate judge_score (mean of the two judges) that counts as a
# pass. The shared rubric in harness/judge.py anchors 0.7 as "mostly correct,
# core logic intact". Dual-judge means BOTH judges run; the call's
# judge_pass is True iff (judge_a + judge_b) / 2 >= JUDGE_PASS_THRESHOLD.
#
# Treated as an a priori rubric-semantic cutoff, NOT a tunable knob.
# Validation (scripts/validate_judge.py) evaluates judge credibility against
# humans; it does not re-fit this threshold. Any future change requires
# bumping JUDGE_VERSION and a full rejudge across affected calls.
JUDGE_PASS_THRESHOLD: float = 0.7


# --- Benchmark identity --------------------------------------------------

# Stamped onto every call. v2.0 is the proposal-faithful build: 5 conditions,
# dual judge, 5-stage pipeline, native function-call tool wiring.
BENCHMARK_VERSION: str = "LEAN-Bench-v2.0"


# --- LEAN execution pin --------------------------------------------------

# Pinned LEAN CLI package version. Mirrors the `lean==...` line in
# requirements.txt and is stamped into results .meta.json so every result row
# is traceable to the CLI that produced it.
LEAN_CLI_VERSION: str = "1.0.225"

# Pinned LEAN engine Docker image, by manifest digest. This is the actual
# executor: same code under a different image yields different Sharpe /
# trades / drawdown.
#
# Must match the commit in `lean_backtest_tool` spec D1
# (d2daf42d34a0c97225794e9b1afaef820434db69). To change: pull the new image,
# capture its `quantconnect/lean@sha256:...` repo digest, update this
# constant AND run `lean config set engine-image <new-digest>`.
LEAN_ENGINE_IMAGE: str = (
    "quantconnect/lean@sha256:"
    "dc84a683464681b2e6c9579bc7655e16d4802380367c77004e40a6a504088bd7"
)


# --- Call status enum ----------------------------------------------------
#
# Persisted on calls.status. Lifecycle:
#   started   — row created, provider call not yet returned
#   completed — provider returned (with or without judge pass)
#   error     — provider/orchestrator threw; calls.error has the text
#   excluded  — design-time excluded (kept for schema back-compat; v2 has
#               no design-time exclusions)
CALL_STATUSES: tuple[str, ...] = ("started", "completed", "error", "excluded")


# --- Design-time cell exclusions ----------------------------------------
#
# v2.0: empty. The proposal-faithful tool wiring uses native function calling
# on all three providers (Anthropic tool_use, OpenAI function tools via the
# Responses API, Gemini function declarations), so the v1.0 Gemini
# tooling-parity exclusion no longer applies.
EXCLUDED_CELLS: dict[tuple[str, str], str] = {}


def excluded_reason_for(model_id: str, condition_id: str) -> str | None:
    """Return the exclusion reason for this cell, or None if not excluded."""
    return EXCLUDED_CELLS.get((model_id, condition_id))
