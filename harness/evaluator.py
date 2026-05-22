"""5-stage pipeline evaluator for LEAN-Bench v2.0 (proposal §Evaluation).

Stage order:
    1. compile  — Python AST parse of the candidate (+ LEAN compile, when
                  the lean_backtest tool ran).
    2. runtime  — backtest executed the date range without crashing.
    3. trade    — at least one order was placed by the algorithm.
    4. schema   — mechanical check: the code's declared securities/dates/
                  resolution match the prompt's schema fields.
    5. judge    — dual-judge semantic faithfulness (harness/judge.py).

Stages 2/3 are populated from the LEAN backtest result (harness/lean_executor
or, in the agent loop, from the lean_backtest_tool round-trip). Stage 5 is the
dual-judge. Stage 4 is implemented here as a regex/AST scan of the generated
code. Stage 1 runs both here (AST) and inside the agent loop's tool feedback.

A continuous performance metric sidecar (Sharpe, total return, max drawdown,
trade count) is *reported* per the proposal but does NOT enter pass/fail
unless the prompt's evaluation_mode is metric_threshold_required.
"""

from __future__ import annotations

import ast
import re
from typing import TypedDict


class EvalResult(TypedDict, total=True):
    compile_pass: bool | None
    backtest_pass: bool | None        # alias for runtime_pass (legacy column name)
    trade_pass: bool | None
    schema_pass: bool | None
    judge_pass: bool | None
    overall_pass: bool | None
    failure_l1: str | None
    failure_l2: str | None
    feedback: str | None              # short-circuit feedback when AST fails
    schema_violations: list[str]


def evaluate_compile(code: str | None) -> EvalResult:
    """Stage 1 only. AST-parse the candidate. Other stages return None.

    Used to short-circuit the agent loop when the model emits unparseable
    Python — sending feedback immediately is cheaper than firing up Docker.
    """
    if not code:
        return EvalResult(
            compile_pass=False,
            backtest_pass=None,
            trade_pass=None,
            schema_pass=None,
            judge_pass=None,
            overall_pass=False,
            failure_l1="compile_error",
            failure_l2="syntax_error",
            feedback=(
                "Your response did not contain a fenced ```python ... ``` "
                "code block. Please return your full LEAN algorithm inside a "
                "single python code fence."
            ),
            schema_violations=[],
        )

    try:
        ast.parse(code)
    except SyntaxError as exc:
        return EvalResult(
            compile_pass=False,
            backtest_pass=None,
            trade_pass=None,
            schema_pass=None,
            judge_pass=None,
            overall_pass=False,
            failure_l1="compile_error",
            failure_l2="syntax_error",
            feedback=(
                f"Your code raised a SyntaxError on line {exc.lineno}: "
                f"{exc.msg}. Please fix the syntax and return the corrected "
                f"algorithm in a single ```python ... ``` block."
            ),
            schema_violations=[],
        )

    return EvalResult(
        compile_pass=True,
        backtest_pass=None,
        trade_pass=None,
        schema_pass=None,
        judge_pass=None,
        overall_pass=None,
        failure_l1=None,
        failure_l2=None,
        feedback=None,
        schema_violations=[],
    )


# --- Stage 4: schema-adherence ------------------------------------------
#
# Proposal §Evaluation Methods step 4: "mechanically verify if the algorithm
# follows the prompt schema fields: {securities[type]}, {start date}, {end
# date}." We also check resolution because the prompt schema declares it.
#
# Implementation note: the LEAN Python API uses snake_case (set_start_date)
# in the modern style and PascalCase (SetStartDate) in the legacy style.
# Both are accepted by the engine and we accept both here.

_ADD_SECURITY_TO_TYPE = {
    "add_equity":   "equity",
    "addequity":    "equity",
    "add_forex":    "forex",
    "addforex":     "forex",
    "add_crypto":   "crypto",
    "addcrypto":    "crypto",
    "add_future":   "future",
    "addfuture":    "future",
    "add_option":   "option",
    "addoption":    "option",
    "add_cfd":      "cfd",
    "addcfd":       "cfd",
}

# Maps prompt's `securities_type` value to the set of LEAN security-types it
# permits. Prompt schema's coarse "equity" allows AddEquity; "option" allows
# AddOption; "multi_asset" intentionally permits any subscription.
_PROMPT_TYPE_PERMITS = {
    "equity":      {"equity"},
    "forex":       {"forex"},
    "crypto":      {"crypto"},
    "future":      {"future"},
    "option":      {"option", "equity"},  # option strategies routinely subscribe equities
    "cfd":         {"cfd"},
    "mixed":       set(_ADD_SECURITY_TO_TYPE.values()),
    "multi_asset": set(_ADD_SECURITY_TO_TYPE.values()),
}

_DATE_TUPLE = re.compile(
    r"(?:Set|set_)Start\s*Date\s*\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)",
    re.IGNORECASE,
)
_END_DATE_TUPLE = re.compile(
    r"(?:Set|set_)End\s*Date\s*\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)",
    re.IGNORECASE,
)
_RESOLUTION_TOKEN = re.compile(
    r"Resolution\.(?P<name>Tick|Second|Minute|Hour|Daily)",
    re.IGNORECASE,
)

_RESOLUTION_PROMPT_TO_LEAN = {
    "tick":            {"tick"},
    "second":          {"second"},
    "minute":          {"minute"},
    "hour":            {"hour"},
    "hourly":          {"hour"},
    "daily":           {"daily"},
    "high_frequency":  {"tick", "second", "minute"},
    "intraday":        {"minute", "hour"},
}


def _normalise_date(s: str | None) -> tuple[int, int, int] | None:
    if not s:
        return None
    parts = re.split(r"[-/]", str(s).strip())
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
    except ValueError:
        return None
    return (y, m, d)


def evaluate_schema(code: str | None, prompt_record: dict) -> EvalResult:
    """Stage 4. Mechanical conformance to the prompt's declared schema.

    Returns an EvalResult where only schema_pass and schema_violations are
    populated (other stages = None). Pass = no violation detected.

    Rule of thumb: only fail when the prompt actually declared the field. If
    the curator didn't pin a value (e.g., resolution=None), we don't penalise.
    """
    violations: list[str] = []
    if not code:
        return EvalResult(
            compile_pass=None, backtest_pass=None, trade_pass=None,
            schema_pass=False, judge_pass=None, overall_pass=None,
            failure_l1="schema_violation", failure_l2="wrong_securities_type",
            feedback=None, schema_violations=["no_code_emitted"],
        )

    # 1) Securities type. Scan for Add<Asset> calls and pull out the asset class.
    declared_type = (prompt_record.get("securities_type") or "").strip().lower() or None
    detailed_type = (prompt_record.get("securities_type_detailed") or "").strip().lower() or None
    found_types: set[str] = set()
    for fn, kind in _ADD_SECURITY_TO_TYPE.items():
        if re.search(rf"\b{fn}\s*\(", code, re.IGNORECASE):
            found_types.add(kind)

    if declared_type and found_types:
        permitted = _PROMPT_TYPE_PERMITS.get(declared_type)
        # Detailed type narrows the allowed set when present.
        if detailed_type and detailed_type in _PROMPT_TYPE_PERMITS:
            permitted = _PROMPT_TYPE_PERMITS[detailed_type]
        if permitted is not None and not (found_types & permitted):
            violations.append(
                f"wrong_securities_type: prompt requires {declared_type!r} "
                f"({sorted(permitted)}), code subscribes {sorted(found_types)}"
            )

    # 2) Start / end dates.
    prompt_start = _normalise_date(prompt_record.get("start_date"))
    prompt_end = _normalise_date(prompt_record.get("end_date"))

    start_match = _DATE_TUPLE.search(code)
    end_match = _END_DATE_TUPLE.search(code)
    code_start = tuple(int(x) for x in start_match.groups()) if start_match else None
    code_end = tuple(int(x) for x in end_match.groups()) if end_match else None

    if prompt_start and code_start and code_start != prompt_start:
        violations.append(
            f"wrong_start_date: prompt {prompt_start!r} vs code {code_start!r}"
        )
    if prompt_end and code_end and code_end != prompt_end:
        violations.append(
            f"wrong_end_date: prompt {prompt_end!r} vs code {code_end!r}"
        )

    # 3) Resolution. Prompt's resolution might be high_frequency / intraday /
    # daily, or a literal tick/second/.... If the code never references a
    # Resolution token at all, we don't penalise (LEAN defaults to Minute).
    declared_res = (prompt_record.get("resolution") or "").strip().lower() or None
    code_resolutions = {m.group("name").lower() for m in _RESOLUTION_TOKEN.finditer(code)}
    if declared_res and code_resolutions:
        permitted_res = _RESOLUTION_PROMPT_TO_LEAN.get(declared_res)
        if permitted_res is not None and not (code_resolutions & permitted_res):
            violations.append(
                f"wrong_resolution: prompt {declared_res!r} permits "
                f"{sorted(permitted_res)}, code uses {sorted(code_resolutions)}"
            )

    schema_pass = not violations
    return EvalResult(
        compile_pass=None, backtest_pass=None, trade_pass=None,
        schema_pass=schema_pass,
        judge_pass=None,
        overall_pass=None,
        failure_l1=None if schema_pass else "schema_violation",
        failure_l2=None if schema_pass else (violations[0].split(":", 1)[0] if violations else None),
        feedback=None,
        schema_violations=violations,
    )


def derive_overall_pass(
    *,
    compile_pass: bool | None,
    runtime_pass: bool | None,
    trade_pass: bool | None,
    schema_pass: bool | None,
    judge_pass: bool | None,
    evaluation_mode: str | None,
) -> bool | None:
    """Combine the 5 stages into a single overall_pass flag.

    Proposal §Evaluation: a call passes when ALL applicable stages pass.
    Trade activity gating depends on prompt.evaluation_mode:
      - trade_required:           trade_pass must be True
      - signal_required:          trade_pass advisory (trades may or may not fire)
      - code_only:                trade_pass ignored
      - metric_threshold_required: caller layers a metric check on top

    Returns None if any required stage is still unknown (so the UI can show
    'pending' instead of 'failed').
    """
    if compile_pass is False:
        return False
    if runtime_pass is False:
        return False
    if schema_pass is False:
        return False
    if judge_pass is False:
        return False

    mode = (evaluation_mode or "trade_required").lower()
    if mode == "trade_required":
        if trade_pass is False:
            return False
        if trade_pass is None:
            return None

    if any(v is None for v in (compile_pass, runtime_pass, schema_pass, judge_pass)):
        return None
    return True


# Back-compat shim. The v1 orchestrator imported `evaluate` as the compile-only
# AST gate; keeping the alias means scripts/rejudge.py and tests that still
# reference it don't break.
evaluate = evaluate_compile
