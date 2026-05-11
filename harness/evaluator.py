"""Four-stage pipeline evaluator: compile -> backtest -> trade -> judge.

Today only the COMPILE stage is implemented (Python AST parse). The other
three stages return None and are populated by a separate evaluation pass that
runs the QC LEAN backtester (Week 2-6 of the build).

The agentic loop (A1_agentic_full) reads `feedback_text` from this evaluator
and sends it back to the model to trigger a refinement turn.
"""

from __future__ import annotations

import ast
from typing import TypedDict


class EvalResult(TypedDict, total=True):
    compile_pass: bool | None
    backtest_pass: bool | None
    trade_pass: bool | None
    judge_pass: bool | None
    overall_pass: bool | None
    failure_l1: str | None
    failure_l2: str | None
    feedback: str | None      # message to send back to model in agentic loop, None if final


def evaluate(code: str | None) -> EvalResult:
    """Run the (currently truncated) four-stage pipeline on a generated code block.

    Returns:
      - compile_pass: True if `ast.parse(code)` succeeds
      - backtest_pass / trade_pass / judge_pass: None until QC integration exists
      - overall_pass: False on compile failure or empty code; otherwise None
        (cannot assert pass without the full pipeline)
      - feedback: text to send back to the model on a refinement turn, or None
        if the call is considered final (compile passed and we have nothing
        more to check yet)
    """
    if not code:
        return EvalResult(
            compile_pass=False,
            backtest_pass=None,
            trade_pass=None,
            judge_pass=None,
            overall_pass=False,
            failure_l1="compile_error",
            failure_l2="syntax_error",
            feedback=(
                "Your response did not contain a fenced ```python ... ``` code block. "
                "Please return your full LEAN algorithm inside a single python code fence."
            ),
        )

    try:
        ast.parse(code)
    except SyntaxError as exc:
        return EvalResult(
            compile_pass=False,
            backtest_pass=None,
            trade_pass=None,
            judge_pass=None,
            overall_pass=False,
            failure_l1="compile_error",
            failure_l2="syntax_error",
            feedback=(
                f"Your code raised a SyntaxError on line {exc.lineno}: {exc.msg}. "
                f"Please fix the syntax and return the corrected algorithm in a "
                f"single ```python ... ``` block."
            ),
        )

    # Compile passed. Real backtest/trade/judge stages are not yet implemented;
    # return None so the agentic loop knows to stop (no actionable feedback).
    return EvalResult(
        compile_pass=True,
        backtest_pass=None,
        trade_pass=None,
        judge_pass=None,
        overall_pass=None,
        failure_l1=None,
        failure_l2=None,
        feedback=None,
    )
