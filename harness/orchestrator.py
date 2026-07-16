"""Run a single (prompt × model × condition × trial) cell end-to-end for
LEAN-Bench v2.1 (harness-driven, no provider tool-use).

Four conditions, all driven by this orchestrator:

    C1_oneshot          one-shot, no tools                          N=5, T=1
    C2_docs             agent + RAG via {R} handshake               N=3, T<=24
    C3_compiler         agent + compiler feedback (lean_backtest)   N=3, T<=24
    C4_docs_compiler    agent + RAG + compiler feedback             N=3, T<=24

v2.1 deltas vs v2.0:
  - NO provider tool-use APIs. Every model call is plain text in / plain text
    out. RAG is invoked when the model's response starts with the literal
    `{R}` handshake marker; compiler feedback is the verbatim output of
    `lean_backtest_tool.run` appended to the next turn's context history.
  - NO schema-block leak: the curator-pinned start_date/end_date/securities/
    resolution are NEVER shown to the model. `evaluate_schema` still uses
    them as the hidden mechanical check.
  - Pipeline-driven retry: every code attempt is graded compile → runtime →
    trade → schema → judge, stopping at the first failed gate. Failure on
    any gate triggers a reprompt with the model's prior attempt(s) in
    labeled context history, until all five gates pass OR T is reached.
  - Per-condition system prompts: only C2/C4 mention the `{R}` RAG handshake;
    C3 does not mention compiler feedback at all (it just appears as text in
    the next turn's context history).
  - Schema and judge failures NEVER produce model-visible feedback, in any
    condition — they are hidden gates by design.

Per-cell lifecycle:

  1. DESIGN-TIME EXCLUSION pre-flight (kept for v2 schema back-compat — the
     EXCLUDED_CELLS table is empty in this build).
  2. INSERT calls row (status='started') with full identity / prompt-set
     hash / judge threshold so even an errored row is auditable.
  3. AGENT LOOP — see `_run_agent_loop`. Writes one `turns` row per turn.
  4. POST-LOOP: fold latest-attempt pipeline outcomes onto the calls row
     (compile_pass / backtest_pass / trade_pass / schema_pass / judge_pass /
     overall_pass, plus rag_call_count / code_attempt_count and the
     first-pass turn index for each gate).
  5. SIDECAR artifact (results/artifacts/{call_id}.json).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from harness.artifacts import build_artifact, write_artifact
from harness.conditions.builder import is_agentic, max_turns_for
from harness.constants import (
    BENCHMARK_VERSION, FROZEN_PROMPT_SET_PATH, JUDGE_PASS_THRESHOLD,
    excluded_reason_for,
)
from harness.evaluator import (
    derive_overall_pass,
    evaluate_compile,
    evaluate_schema,
)
from harness.judge import JUDGE_VERSION, JudgeError, judge_call
from harness.models import (
    CONDITIONS, DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_TEMPERATURE, DEFAULT_TOP_P,
    MODELS_FROZEN, default_attempts_for,
)
from harness.pricing import PricingNotSetError, cost_usd
from harness.prompt_freeze import canonicalize, is_eligible, load_frozen, sha256_of
from harness.providers import anthropic_client, gemini_client, openai_client
from harness.providers.base import ProviderResponse, extract_code
from harness.storage import Store


# FROZEN_PROMPT_SET_PATH is re-exported from harness.constants (moved there
# in v2.1 so lightweight endpoints can read it without pulling in provider
# SDKs). The import above keeps the name available at the orchestrator's
# public surface for back-compat.


PROVIDER_CALL = {
    "anthropic": anthropic_client.call,
    "openai":    openai_client.call,
    "google":    gemini_client.call,
}


# ---------------------------------------------------------------------------
# Per-condition system prompts. The model never sees curator-pinned schema
# fields (start/end/securities/resolution). C2/C4 advertise the {R} RAG
# handshake; C3/C4 do NOT mention the compiler-feedback channel — feedback is
# appended verbatim to the next turn's context-history block.
# ---------------------------------------------------------------------------

_SYSTEM_BASE = (
    "You are an expert algorithmic-trading engineer. Your task is to generate "
    "a complete QuantConnect LEAN algorithm in Python that fulfills the "
    "user's request. Your code must define a class that subclasses "
    "QCAlgorithm and implements Initialize and OnData.\n\n"
    "Return your final algorithm as a single fenced ```python ... ``` block "
    "with no other text outside the fence."
)

_SYSTEM_RAG_HANDSHAKE = (
    "\n\n"
    "You have access to a QuantConnect LEAN documentation retrieval (RAG) "
    "system. To query it, your ENTIRE response on this turn must be exactly:\n\n"
    "    {R} <your query>\n\n"
    "For example: {R} how to instantiate a Bollinger Bands indicator\n\n"
    "On the following turn the retrieved documentation will be appended to "
    "your context history. You may query RAG as many times as you need.\n\n"
    "Each turn you must EITHER query RAG with `{R} <query>` OR submit a final "
    "algorithm in a single ```python ... ``` block — never both in the same "
    "response."
)

SYSTEM_PROMPTS: dict[str, str] = {
    "C1_oneshot":       _SYSTEM_BASE,
    "C2_docs":          _SYSTEM_BASE + _SYSTEM_RAG_HANDSHAKE,
    "C3_compiler":      _SYSTEM_BASE,
    "C4_docs_compiler": _SYSTEM_BASE + _SYSTEM_RAG_HANDSHAKE,
}

SYSTEM_PROMPT_SHAS: dict[str, str] = {
    cond: hashlib.sha256(text.encode("utf-8")).hexdigest()
    for cond, text in SYSTEM_PROMPTS.items()
}


# ---------------------------------------------------------------------------
# RAG and compiler-feedback wiring. These are first-party harness facilities,
# NOT provider tools — the model never sees them as tool definitions.
# ---------------------------------------------------------------------------

_lean_rag_retrieve = None
_lean_backtest_run = None
_lean_backtest_run_config = None


def _retrieve_fn():
    global _lean_rag_retrieve
    if _lean_rag_retrieve is None:
        from lean_rag import retrieve  # type: ignore
        _lean_rag_retrieve = retrieve
    return _lean_rag_retrieve


def _backtest_fn():
    global _lean_backtest_run, _lean_backtest_run_config
    if _lean_backtest_run is None:
        from lean_backtest_tool import run, RunConfig  # type: ignore
        _lean_backtest_run = run
        _lean_backtest_run_config = RunConfig
    return _lean_backtest_run, _lean_backtest_run_config


_LEAN_WORKDIR    = os.environ.get("LEANBENCH_LEAN_WORKDIR",  str(Path.cwd() / "lean_workspace" / "agent_runs"))
_LEAN_DATA_DIR   = os.environ.get("LEANBENCH_LEAN_DATA_DIR", str(Path.cwd() / "data"))
_LEAN_DOCKER_IMG = os.environ.get(
    "LEANBENCH_LEAN_DOCKER_IMAGE",
    "quantconnect/lean@sha256:dc84a683464681b2e6c9579bc7655e16d4802380367c77004e40a6a504088bd7",
)

# Soft cap on the rendered RAG result block so context doesn't blow up at T=24.
_RAG_OUTPUT_CAP_CHARS = 12_000


def _render_rag_chunks(chunks: list[str] | None) -> str:
    if not chunks:
        return "(no documentation chunks matched the query)"
    rendered: list[str] = []
    for i, text in enumerate(chunks, 1):
        rendered.append(f"--- chunk {i} ---\n{str(text).strip()}")
    out = "\n\n".join(rendered)
    if len(out) > _RAG_OUTPUT_CAP_CHARS:
        out = out[:_RAG_OUTPUT_CAP_CHARS] + "\n[truncated]"
    return out


def _run_rag(query: str) -> str:
    """Synchronous RAG retrieval. Called from a thread executor."""
    chunks = _retrieve_fn()(query)
    return _render_rag_chunks(chunks)


def _run_compiler(code: str) -> dict[str, Any]:
    """Synchronous compiler-feedback invocation (lean_backtest_tool.run).

    Returns {"output": str, "exit_status": "completed"|"timeout"|...}.
    The `output` field IS the compiler-feedback string the model sees in
    C3/C4. We never modify it — what lean_backtest_tool returns is what the
    model gets.
    """
    run_fn, RunConfig = _backtest_fn()
    Path(_LEAN_WORKDIR).mkdir(parents=True, exist_ok=True)
    cfg = RunConfig(
        workdir=_LEAN_WORKDIR,
        lean_data_dir=_LEAN_DATA_DIR,
        docker_image=_LEAN_DOCKER_IMG,
    )
    result = run_fn(code, "python", cfg)
    return {"output": result.output, "exit_status": result.exit_status}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

_RAG_MARKER = "{R}"


def parse_response(text: str) -> tuple[str, str]:
    """Parse a model response into one of:

        ("rag_query", <query string>)   — response stripped starts with `{R}`
        ("code",      <python source>)  — response contains a ```python ... ```
                                          fence (and does NOT start with `{R}`)
        ("invalid",   <reason>)          — neither

    Strict {R} handshake per the spec: if the stripped response starts with
    `{R}`, the ENTIRE remainder (after `{R}` and any leading whitespace) is
    the query. No code-fence parsing happens inside a {R} response.

    The caller (the agent loop) decides whether a {R} attempt is legal for
    the current condition (only C2/C4 expose RAG); for C1/C3 a {R} response
    is recorded as invalid.
    """
    stripped = (text or "").lstrip()
    if stripped.startswith(_RAG_MARKER):
        after = stripped[len(_RAG_MARKER):].lstrip()
        if not after:
            return ("invalid", "empty RAG query after '{R}' marker")
        return ("rag_query", after.rstrip())
    code = extract_code(text or "")
    if code:
        return ("code", code)
    return ("invalid", "no '{R}' prefix and no fenced python block")


# ---------------------------------------------------------------------------
# Compiler-output parser. Reads the trailer that lean_backtest_tool appends:
#   "\nORDERS_PLACED: <n>\nLEAN_RUN_FINISHED"  -> runtime ok, n orders
#   "\nORDERS_PLACED: unknown\nLEAN_RUN_FINISHED" -> runtime ok, orders unknown
#   "\nTIMEOUT_EXCEEDED: ..."                  -> runtime timeout
#   "\nINFRASTRUCTURE_ERROR: ..."              -> tool/Docker failure
# The trailer is reliable because lean_backtest_tool synthesises it itself.
# ---------------------------------------------------------------------------

_RE_ORDERS = re.compile(r"^ORDERS_PLACED:\s*(\d+|unknown)\s*$", re.MULTILINE)


def _parse_compiler_output(output: str, exit_status: str) -> dict[str, Any]:
    """Derive runtime_success / num_trades / runtime_error from the compiler
    feedback string.

    Conventions:
      - runtime_success True iff trailer says LEAN_RUN_FINISHED AND no ERROR::
        lines reference an unhandled algorithm exception. We use a soft rule
        here: presence of LEAN_RUN_FINISHED with NO ERROR:: lines == True,
        LEAN_RUN_FINISHED with ERROR:: lines == False, any other trailer
        (timeout / infra) == False.
      - num_trades: integer from ORDERS_PLACED, or None on 'unknown' / absent.
    """
    text = output or ""
    has_run_finished = "LEAN_RUN_FINISHED" in text
    has_timeout = "TIMEOUT_EXCEEDED:" in text
    has_infra = "INFRASTRUCTURE_ERROR:" in text
    has_error = bool(re.search(r"\bERROR::", text))

    if exit_status == "timeout" or has_timeout:
        runtime_success = False
        runtime_error = "lean_backtest_tool timed out"
    elif exit_status in ("docker_error", "infra_error") or has_infra:
        runtime_success = False
        runtime_error = "lean_backtest_tool infrastructure error"
    elif has_run_finished and not has_error:
        runtime_success = True
        runtime_error = None
    elif has_run_finished and has_error:
        runtime_success = False
        # Capture the first ERROR:: line trimmed to ~500 chars for the row.
        m = re.search(r"^.*ERROR::.*$", text, re.MULTILINE)
        runtime_error = (m.group(0)[:500] if m else "ERROR:: in LEAN log")
    else:
        runtime_success = False
        runtime_error = "lean_backtest_tool did not report LEAN_RUN_FINISHED"

    num_trades: int | None = None
    m = _RE_ORDERS.search(text)
    if m:
        val = m.group(1)
        if val.isdigit():
            num_trades = int(val)

    return {
        "compile_success":  runtime_success,  # LEAN's own compile is rolled into runtime
        "runtime_success":  runtime_success,
        "runtime_error":    runtime_error,
        "num_trades":       num_trades,
        "lean_results_json": None,
        # Reported metrics not derivable from the filtered log — left None
        # per v2.1 spec (paper sidecar uses raw artifacts where needed).
        "total_return_pct":         None,
        "sharpe_ratio":             None,
        "max_drawdown_pct":         None,
        "win_rate":                 None,
        "starting_portfolio_value": None,
        "final_portfolio_value":    None,
        "benchmark_return_pct":     None,
    }


# ---------------------------------------------------------------------------
# User-message renderer.
#
# Every model call in v2.1 is shaped as ONE user turn:
#
#   [Context history of your previous attempts]
#   --- Attempt 1 ---
#   <model's prior response, verbatim>
#
#   RAG result:
#   <retrieved chunks>            (omitted when no RAG happened on that turn)
#
#   Compiler feedback:
#   <lean_backtest_tool output>   (omitted when no compiler feedback was sent)
#   --- Attempt 2 ---
#   ...
#   [End of context history]
#
#   [Original prompt]
#   <original natural-language prompt>
#
# When history is empty (turn 1), the context block is omitted entirely.
# Compiler-feedback and RAG-result sub-blocks appear ONLY when the orchestrator
# decided to attach them for that attempt (C3/C4 for compiler feedback;
# C2/C4 for RAG results). Schema/judge failures never attach anything — the
# attempt's `model_text` is the only artifact retained in that case.
# ---------------------------------------------------------------------------


def render_user_message(original_prompt: str, history: list[dict]) -> str:
    parts: list[str] = []
    if history:
        parts.append("[Context history of your previous attempts]")
        for i, attempt in enumerate(history, start=1):
            parts.append(f"--- Attempt {i} ---")
            parts.append(str(attempt.get("model_text") or ""))
            rag = attempt.get("rag_result")
            if rag is not None:
                parts.append("")
                parts.append("RAG result:")
                parts.append(str(rag))
            cfb = attempt.get("compiler_feedback")
            if cfb is not None:
                parts.append("")
                parts.append("Compiler feedback:")
                parts.append(str(cfb))
        parts.append("[End of context history]")
        parts.append("")
    parts.append("[Original prompt]")
    parts.append(original_prompt)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Per-turn event summary for storage.tool_events_json (used by the UI).
# ---------------------------------------------------------------------------


def _summarise_turn_events(attempt: dict, pipeline: dict | None) -> list[dict]:
    """Compact per-turn event list. One entry per facility the orchestrator
    actually exercised this turn. The Transcript tab of the call modal reads
    these to render per-turn cards.

    Field-name conventions match what the v2.1 UI consumes directly (no
    backend renaming pass needed). Specifically:

    - RAG events expose `query` and `output_len` at the top level.
    - lean_backtest events are emitted for EVERY code attempt — the gates
      need the LEAN trailer either way, so the diagnostic value is the same
      whether the model saw the output or not. The `feedback_shown_to_model`
      flag distinguishes the two cases (True only in C3/C4).
    - code_attempt carries the per-stage gate outcomes inline so the UI can
      render a stage matrix without re-joining anything.
    - invalid_response carries the parser's rejection reason so the UI can
      surface why the turn was thrown out (empty {R}, no python fence, etc.).
    """
    events: list[dict] = []
    kind = attempt.get("kind")

    if kind == "rag":
        result_text = str(attempt.get("rag_result") or "")
        events.append({
            "name":            "rag_retrieve",
            "query":           attempt.get("rag_query") or "",
            "output_preview":  result_text[:800],
            "output_len":      len(result_text),
            "is_error":        False,
        })

    if kind == "code":
        code = attempt.get("code") or ""
        stage_results = (pipeline or {}).get("stage_results") or {}
        events.append({
            "name":          "code_attempt",
            "code_chars":    len(code),
            "code_sha8":     hashlib.sha256(code.encode("utf-8")).hexdigest()[:8],
            "stage_results": stage_results,
            # Convenience: which stage was the first to fail this turn. Lets
            # the UI tag the card without re-deriving the order.
            "first_fail":    _first_fail_stage(stage_results),
        })
        # Compiler ran for EVERY code attempt — emit the event unconditionally.
        # The flag distinguishes C3/C4 (feedback fed back to the model) from
        # C1/C2 (gate-only). Without this, C1/C2 compiler runs are invisible
        # in the UI even though they happened.
        log_tail = str(attempt.get("compiler_log") or attempt.get("compiler_feedback") or "")
        if log_tail or pipeline:
            events.append({
                "name":                     "lean_backtest",
                "log_tail":                 log_tail[-1600:],
                "output_len":               len(log_tail),
                "exit_status":              (pipeline or {}).get("compiler_exit_status"),
                "is_error":                 (pipeline or {}).get("compiler_exit_status") in ("docker_error", "infra_error"),
                "feedback_shown_to_model":  attempt.get("compiler_feedback") is not None,
                "code_sha8":                hashlib.sha256(code.encode("utf-8")).hexdigest()[:8] if code else None,
            })

        # Schema check (hidden gate — never visible to the model, but the
        # auditor needs to see the violation list to diagnose schema fails).
        if stage_results.get("schema_pass") is not None:
            events.append({
                "name":        "schema_check",
                "schema_pass": stage_results.get("schema_pass"),
                "violations":  attempt.get("schema_violations") or [],
                "is_error":    stage_results.get("schema_pass") is False,
            })

        # Judge (hidden gate — same rationale; surface scores + reasoning).
        judge = attempt.get("judge_outcome")
        if judge is not None:
            events.append({
                "name":              "judge",
                "judge_pass":        stage_results.get("judge_pass"),
                "judge_score":       judge.get("judge_score"),
                "judge_score_a":     judge.get("judge_score_a"),
                "judge_score_b":     judge.get("judge_score_b"),
                "judge_reasoning_a": judge.get("judge_reasoning_a"),
                "judge_reasoning_b": judge.get("judge_reasoning_b"),
                "matches_prompt_intent": judge.get("matches_prompt_intent"),
                "failure_mode":      judge.get("failure_mode"),
                "judge_error":       judge.get("error"),
                "is_error":          bool(judge.get("error")) or stage_results.get("judge_pass") is False,
            })

    if kind == "invalid":
        events.append({
            "name":     "invalid_response",
            "reason":   attempt.get("reason"),
            "is_error": True,
        })

    return events


_STAGE_ORDER = ("compile_pass", "runtime_pass", "trade_pass", "schema_pass", "judge_pass")


def _first_fail_stage(stage_results: dict) -> str | None:
    """Return the canonical name of the first failing stage in pipeline
    order (compile → runtime → trade → schema → judge), or None when every
    stage that ran passed. A `None` outcome (stage didn't run) is treated as
    "did not reach" — earlier failures shadow it.
    """
    for s in _STAGE_ORDER:
        v = stage_results.get(s)
        if v is False:
            return s.replace("_pass", "")
    return None


def _summarise_judge_outcome(judge_outcome: dict | None) -> dict | None:
    """Pluck the fields the UI shows from a judge_call() result.

    The dual-judge dict carries A and B sub-judges plus the averaged score
    and a combined reasoning. The UI wants them all per-turn so a reviewer
    can audit "judge A said X but B said Y" without opening the artifact JSON.
    Returns None when the judge never ran (e.g., schema failed first).
    """
    if not judge_outcome:
        return None
    if "error" in judge_outcome:
        return {"error": judge_outcome["error"]}
    return {
        "judge_score":         judge_outcome.get("judge_score"),
        "judge_score_a":       judge_outcome.get("judge_score_a"),
        "judge_score_b":       judge_outcome.get("judge_score_b"),
        "judge_reasoning_a":   judge_outcome.get("judge_reasoning_a"),
        "judge_reasoning_b":   judge_outcome.get("judge_reasoning_b"),
        "matches_prompt_intent": judge_outcome.get("matches_prompt_intent"),
        "failure_mode":        judge_outcome.get("failure_mode"),
    }


# ---------------------------------------------------------------------------
# Pricing helper.
# ---------------------------------------------------------------------------


def _safe_cost(model_pinned: str, in_tok: int, out_tok: int, cached: int) -> float | None:
    try:
        return cost_usd(model_pinned, in_tok, out_tok, cached)
    except PricingNotSetError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Turn writer.
# ---------------------------------------------------------------------------


def _write_turn(
    store: Store,
    *,
    call_id: str,
    turn_index: int,
    user_msg: str,
    resp: ProviderResponse,
    attempt: dict,
    pipeline: dict | None,
    model_pinned: str,
) -> None:
    """Persist a single turn row to the DB."""
    try:
        turn_cost = _safe_cost(
            model_pinned, resp["input_tokens"], resp["output_tokens"], resp["cached_tokens"],
        )
        stage_results = (pipeline or {}).get("stage_results") or {}
        store.record_turn(
            call_id=call_id,
            turn_index=turn_index,
            prompt_messages_json=json.dumps(
                [{"role": "user", "content": user_msg}], separators=(",", ":")
            ),
            response_text=resp["response_text"],
            response_code_extracted=(attempt.get("code") if attempt.get("kind") == "code" else None),
            response_tokens_in=resp["input_tokens"],
            response_tokens_out=resp["output_tokens"],
            ran_pipeline=(attempt.get("kind") == "code"),
            compile_pass=stage_results.get("compile_pass"),
            backtest_pass=stage_results.get("runtime_pass"),
            trade_pass=stage_results.get("trade_pass"),
            judge_pass=stage_results.get("judge_pass"),
            feedback_text=(attempt.get("compiler_feedback") if attempt.get("kind") == "code" else None),
            cost_usd=turn_cost,
            wall_clock_seconds=resp["latency_ms"] / 1000,
            tool_events_json=_summarise_turn_events(attempt, pipeline) or None,
            is_final_turn=bool((pipeline or {}).get("all_pass")),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[orchestrator] failed to record turn {turn_index}: {exc}")


# ---------------------------------------------------------------------------
# The agent loop.
# ---------------------------------------------------------------------------


async def _run_agent_loop(
    *,
    provider: str,
    model_pinned: str,
    condition_id: str,
    system_prompt: str,
    original_prompt: str,
    prompt_record: dict,
    max_turns: int,
    store: Store,
    call_id: str,
    record_turns: bool,
) -> dict[str, Any]:
    """Drive the v2.1 pipeline-driven loop.

    Each turn:
      1. Build ONE user message from labeled history + original prompt.
      2. Call provider with tools=None.
      3. Parse response: rag_query | code | invalid.
      4. If rag_query AND condition allows RAG (C2/C4): retrieve, append.
      5. If code: run pipeline gates (compile/runtime/trade/schema/judge),
         stop on first fail. C3/C4 always append compiler feedback for code
         attempts; C1/C2 never do (they just see the prior model_text in
         history).
      6. If invalid: record and reprompt.

    Loop terminates when all 5 gates pass on a single code attempt OR
    max_turns is reached.

    Returns a dict carrying final code, the per-stage first-pass turn index,
    the latest backtest/schema/judge results (for folding onto the calls row),
    aggregated tokens/wall, and an error string when applicable.
    """
    rag_enabled              = condition_id in ("C2_docs", "C4_docs_compiler")
    compiler_feedback_to_model = condition_id in ("C3_compiler", "C4_docs_compiler")
    provider_call = PROVIDER_CALL[provider]

    history: list[dict] = []

    total_input = total_output = total_cached = 0
    total_wall = 0.0
    last_response: ProviderResponse | None = None
    error_text: str | None = None
    turns_used = 0
    rag_call_count = 0
    code_attempt_count = 0

    first_pass: dict[str, int | None] = {
        "compile": None, "runtime": None, "trade": None,
        "schema":  None, "judge":   None,
    }

    final_code: str | None = None
    final_code_turn_index: int | None = None
    latest_backtest: dict | None = None
    latest_schema_eval: dict | None = None
    latest_judge_outcome: dict | None = None
    overall_all_pass = False

    for turn_index in range(max_turns):
        # -- 1. user message ------------------------------------------------
        user_msg = render_user_message(original_prompt, history)
        messages = [{"role": "user", "content": user_msg}]

        # -- 2. provider call ----------------------------------------------
        try:
            resp = await provider_call(
                model_pinned=model_pinned,
                messages=messages,
                system_prompt=system_prompt,
                tools=None,
                max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
                temperature=DEFAULT_TEMPERATURE,
            )
        except Exception as exc:  # noqa: BLE001
            error_text = f"{type(exc).__name__}: {exc}"
            break

        turns_used += 1
        total_input  += resp["input_tokens"]
        total_output += resp["output_tokens"]
        total_cached += resp["cached_tokens"]
        total_wall   += resp["latency_ms"] / 1000
        last_response = resp

        # -- 3. parse response ----------------------------------------------
        kind, payload = parse_response(resp["response_text"])

        # ---- branch: RAG query ----
        if kind == "rag_query":
            if not rag_enabled:
                # Model emitted {R} in a condition that has no RAG (C1/C3).
                # Record as invalid attempt; no leak.
                attempt = {
                    "kind":       "invalid",
                    "model_text": resp["response_text"],
                    "reason":     "{R} marker used but RAG not enabled for this condition",
                }
                history.append(attempt)
                if record_turns:
                    _write_turn(store, call_id=call_id, turn_index=turn_index,
                                user_msg=user_msg, resp=resp, attempt=attempt,
                                pipeline=None, model_pinned=model_pinned)
                continue

            loop = asyncio.get_running_loop()
            try:
                rag_text = await loop.run_in_executor(None, _run_rag, payload)
            except Exception as exc:  # noqa: BLE001
                rag_text = f"(RAG retrieval failed: {type(exc).__name__}: {exc})"
            attempt = {
                "kind":        "rag",
                "model_text":  resp["response_text"],
                "rag_query":   payload,
                "rag_result":  rag_text,
            }
            history.append(attempt)
            rag_call_count += 1
            if record_turns:
                _write_turn(store, call_id=call_id, turn_index=turn_index,
                            user_msg=user_msg, resp=resp, attempt=attempt,
                            pipeline=None, model_pinned=model_pinned)
            continue

        # ---- branch: invalid ----
        if kind == "invalid":
            attempt = {
                "kind":       "invalid",
                "model_text": resp["response_text"],
                "reason":     payload,
            }
            history.append(attempt)
            if record_turns:
                _write_turn(store, call_id=call_id, turn_index=turn_index,
                            user_msg=user_msg, resp=resp, attempt=attempt,
                            pipeline=None, model_pinned=model_pinned)
            continue

        # ---- branch: code attempt ----
        code = payload
        code_attempt_count += 1
        final_code = code
        final_code_turn_index = turn_index

        stage_results: dict[str, bool | None] = {
            "compile_pass": None, "runtime_pass": None, "trade_pass": None,
            "schema_pass":  None, "judge_pass":   None,
        }
        compiler_feedback: str | None = None
        compiler_exit_status: str | None = None
        backtest_payload: dict | None = None
        schema_eval: dict | None = None
        judge_outcome: dict | None = None

        # Gate 1: compile (AST)
        compile_eval = evaluate_compile(code)
        stage_results["compile_pass"] = compile_eval["compile_pass"]
        if compile_eval["compile_pass"] and first_pass["compile"] is None:
            first_pass["compile"] = turn_index

        # ALWAYS run lean_backtest_tool when code is submitted — its output IS
        # the canonical compiler feedback string for C3/C4. We do not synthesise
        # a substitute even when AST already failed, because the spec mandates
        # that what lean_backtest_tool returns is what the model sees.
        loop = asyncio.get_running_loop()
        try:
            compiler_run = await loop.run_in_executor(None, _run_compiler, code)
        except Exception as exc:  # noqa: BLE001
            compiler_run = {
                "output": f"(lean_backtest_tool invocation failed: {type(exc).__name__}: {exc})",
                "exit_status": "infra_error",
            }
        compiler_exit_status = compiler_run.get("exit_status")
        if compiler_feedback_to_model:
            compiler_feedback = compiler_run["output"]
        backtest_payload = _parse_compiler_output(
            compiler_run["output"], compiler_exit_status or "",
        )

        # Gate 2: runtime — only if compile (AST) passed
        if stage_results["compile_pass"]:
            stage_results["runtime_pass"] = bool(backtest_payload["runtime_success"])
            if stage_results["runtime_pass"] and first_pass["runtime"] is None:
                first_pass["runtime"] = turn_index

            # Gate 3: trade — only if runtime passed
            if stage_results["runtime_pass"]:
                n = backtest_payload.get("num_trades")
                if n is None:
                    stage_results["trade_pass"] = None
                else:
                    stage_results["trade_pass"] = n >= 1
                if stage_results["trade_pass"] and first_pass["trade"] is None:
                    first_pass["trade"] = turn_index

        # Gate 4: schema (HIDDEN — model never sees the schema check)
        if stage_results["trade_pass"]:
            schema_eval = evaluate_schema(code, prompt_record)
            stage_results["schema_pass"] = schema_eval["schema_pass"]
            if stage_results["schema_pass"] and first_pass["schema"] is None:
                first_pass["schema"] = turn_index

        # Gate 5: judge (HIDDEN — model never sees the judge result)
        if stage_results["schema_pass"]:
            try:
                judge_result = await judge_call(
                    prompt_record=prompt_record,
                    generated_code=code,
                    backtest_result=backtest_payload,
                    judge_version=JUDGE_VERSION,
                )
                judge_score = judge_result.get("judge_score")
                judge_pass = bool(judge_score is not None and judge_score >= JUDGE_PASS_THRESHOLD)
                stage_results["judge_pass"] = judge_pass
                judge_outcome = judge_result
                if judge_pass and first_pass["judge"] is None:
                    first_pass["judge"] = turn_index
            except JudgeError as exc:
                stage_results["judge_pass"] = False
                judge_outcome = {"error": f"{type(exc).__name__}: {exc}"}
            except Exception as exc:  # noqa: BLE001
                stage_results["judge_pass"] = False
                judge_outcome = {"error": f"{type(exc).__name__}: {exc}"}

        # Persist latest pipeline outcomes for the post-loop calls-row update.
        latest_backtest = backtest_payload
        latest_schema_eval = schema_eval
        latest_judge_outcome = judge_outcome

        all_pass = all(
            stage_results[k] is True
            for k in ("compile_pass", "runtime_pass", "trade_pass", "schema_pass", "judge_pass")
        )
        overall_all_pass = all_pass

        # `attempt` is BOTH the history record (fed to the next user message
        # via render_user_message — model only sees `compiler_feedback` when
        # populated) AND the source for _summarise_turn_events (UI events —
        # `compiler_log` is the raw LEAN output regardless of condition, so
        # C1/C2 compiler runs aren't invisible in the diagnostic view).
        attempt = {
            "kind":               "code",
            "model_text":         resp["response_text"],
            "code":               code,
            "compiler_feedback":  compiler_feedback,          # model-visible (C3/C4 only)
            "compiler_log":       compiler_run["output"],     # diagnostic (every condition)
            "stage_results":      stage_results,
            "schema_violations":  (schema_eval or {}).get("schema_violations") if schema_eval else None,
            "judge_outcome":      _summarise_judge_outcome(judge_outcome),
        }
        history.append(attempt)
        if record_turns:
            _write_turn(
                store, call_id=call_id, turn_index=turn_index,
                user_msg=user_msg, resp=resp, attempt=attempt,
                pipeline={
                    "stage_results":        stage_results,
                    "compiler_exit_status": compiler_exit_status,
                    "all_pass":             all_pass,
                },
                model_pinned=model_pinned,
            )

        if all_pass:
            break

        # Failure at some gate — continue the loop until max_turns.

    if record_turns and final_code_turn_index is not None:
        try:
            store.mark_final_turn(call_id, final_code_turn_index)
        except Exception as exc:  # noqa: BLE001
            print(f"[orchestrator] failed to mark final turn: {exc}")

    return {
        "final_code":            final_code,
        "final_code_turn_index": final_code_turn_index,
        "last_response":         last_response,
        "turns_used":            turns_used,
        "rag_call_count":        rag_call_count,
        "code_attempt_count":    code_attempt_count,
        "first_pass":            first_pass,
        "history":               history,
        "latest_backtest":       latest_backtest,
        "latest_schema_eval":    latest_schema_eval,
        "latest_judge_outcome":  latest_judge_outcome,
        "overall_all_pass":      overall_all_pass,
        "total_input":           total_input,
        "total_output":          total_output,
        "total_cached":          total_cached,
        "total_wall":            total_wall,
        "error_text":            error_text,
    }


# ---------------------------------------------------------------------------
# Cell driver.
# ---------------------------------------------------------------------------


async def run_cell(
    store: Store,
    prompt_id: str,
    prompt_text: str,
    model_friendly: str,
    condition_id: str,
    trial_index: int,
    *,
    prompt_set_sha256: str | None = None,
    max_turns_override: int | None = None,
) -> dict[str, Any]:
    """Run one (prompt × model × condition × trial_index) cell.

    Always writes one `calls` row (even on provider error or excluded cell)
    and the appropriate `turns` rows. Returns a result dict matching the
    CallResult Pydantic schema (extended with v2.1 fields).
    """
    cond = CONDITIONS[condition_id]
    model_info = MODELS_FROZEN[model_friendly]
    provider = model_info["provider"]
    model_pinned = model_info["model_id"]
    model_family = model_info["model_family"]

    call_id = str(uuid.uuid4())
    max_turns = max_turns_for(condition_id)
    if max_turns_override is not None and cond.get("tool_agentic_loop"):
        max_turns = max_turns_override

    system_prompt     = SYSTEM_PROMPTS[condition_id]
    system_prompt_sha = SYSTEM_PROMPT_SHAS[condition_id]

    # ==== Pre-flight: design-time cell exclusion ==========================
    excl_reason = excluded_reason_for(model_friendly, condition_id)
    if excl_reason is not None:
        store.create_call(
            call_id=call_id,
            prompt_id=prompt_id,
            model_family=model_family,
            model_id=model_friendly,
            model_version=model_pinned,
            condition=condition_id,
            pass_number=trial_index,
            tool_docs_retrieval=cond["tool_docs_retrieval"],
            tool_web_search=cond["tool_web_search"],
            tool_agentic_loop=cond["tool_agentic_loop"],
            tool_compiler_feedback=cond["tool_compiler_feedback"],
            max_turns_allowed=max_turns,
            temperature=DEFAULT_TEMPERATURE,
            top_p=DEFAULT_TOP_P,
            max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            system_prompt_sha=system_prompt_sha,
            status="excluded",
            excluded_reason=excl_reason,
            benchmark_version=BENCHMARK_VERSION,
            prompt_set_sha256=prompt_set_sha256,
        )
        return _excluded_result(call_id, model_friendly, condition_id, trial_index, excl_reason)

    # ==== STAGE 1: create_call ============================================
    store.create_call(
        call_id=call_id,
        prompt_id=prompt_id,
        model_family=model_family,
        model_id=model_friendly,
        model_version=model_pinned,
        condition=condition_id,
        pass_number=trial_index,
        tool_docs_retrieval=cond["tool_docs_retrieval"],
        tool_web_search=cond["tool_web_search"],
        tool_agentic_loop=cond["tool_agentic_loop"],
        tool_compiler_feedback=cond["tool_compiler_feedback"],
        max_turns_allowed=max_turns,
        temperature=DEFAULT_TEMPERATURE,
        top_p=DEFAULT_TOP_P,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        system_prompt_sha=system_prompt_sha,
        # v2.1: no preprocessor snippet, no schema-leak, no native tool defs.
        retrieval_snippet=None,
        status="started",
        benchmark_version=BENCHMARK_VERSION,
        prompt_set_sha256=prompt_set_sha256,
        judge_threshold=JUDGE_PASS_THRESHOLD,
    )

    # ==== STAGE 2: AGENT LOOP =============================================
    overall_start = time.monotonic()

    prompt_record = store.get_prompt(prompt_id)
    if prompt_record is None:
        # Ad-hoc prompt not in DB. evaluate_schema returns clean / judge sees
        # the raw text. Schema fields are absent so the schema gate becomes a
        # no-op (no violations possible).
        prompt_record = {
            "reformulated_text": prompt_text,
            "original_text":     prompt_text,
        }

    loop_outcome = await _run_agent_loop(
        provider=provider,
        model_pinned=model_pinned,
        condition_id=condition_id,
        system_prompt=system_prompt,
        original_prompt=prompt_text,
        prompt_record=prompt_record,
        max_turns=max_turns,
        store=store,
        call_id=call_id,
        record_turns=is_agentic(condition_id) or condition_id == "C1_oneshot",
    )

    final_code           = loop_outcome["final_code"]
    error_text           = loop_outcome["error_text"]
    last_response        = loop_outcome["last_response"]
    turns_used           = loop_outcome["turns_used"]
    total_input          = loop_outcome["total_input"]
    total_output         = loop_outcome["total_output"]
    total_cached         = loop_outcome["total_cached"]
    rag_call_count       = loop_outcome["rag_call_count"]
    code_attempt_count   = loop_outcome["code_attempt_count"]
    first_pass           = loop_outcome["first_pass"]
    latest_backtest      = loop_outcome["latest_backtest"]
    latest_schema_eval   = loop_outcome["latest_schema_eval"]
    latest_judge_outcome = loop_outcome["latest_judge_outcome"]

    total_cost = _safe_cost(model_pinned, total_input, total_output, total_cached)
    final_code_sha = hashlib.sha256((final_code or "").encode()).hexdigest()
    overall_wall = time.monotonic() - overall_start

    # ==== Fold latest pipeline outcomes onto the calls row ================
    # `latest_*` are the most recent code-attempt results — if the loop
    # eventually passed, that's the passing attempt; otherwise it's the last
    # failing one. Either way, the calls row reflects the FINAL state.

    # Compile / runtime / trade
    compile_pass_for_row: bool | None = None
    if final_code is None:
        # Loop never produced code — call evaluate_compile on empty string to
        # get the canonical 'no code' EvalResult (compile_pass=False).
        compile_pass_for_row = evaluate_compile(None)["compile_pass"]
    else:
        compile_pass_for_row = evaluate_compile(final_code)["compile_pass"]

    store.update_call(
        call_id,
        turns_used=turns_used,
        generated_code=final_code,
        code_hash=final_code_sha,
        final_code_sha256=final_code_sha,
        raw_model_response=last_response["response_text"] if last_response else None,
        finish_reason=last_response["finish_reason"] if last_response else None,
        tokens_in=total_input,
        tokens_out=total_output,
        cost_usd=total_cost,
        latency_ms=last_response["latency_ms"] if last_response else None,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cost_usd=total_cost,
        wall_clock_seconds=overall_wall,
        error=error_text,
        compile_pass=compile_pass_for_row,
    )

    if latest_backtest is not None:
        store.update_call_with_backtest(
            call_id,
            compile_success=latest_backtest.get("compile_success"),
            runtime_success=latest_backtest.get("runtime_success"),
            runtime_error=latest_backtest.get("runtime_error"),
            lean_results_json=latest_backtest.get("lean_results_json"),
            total_return_pct=latest_backtest.get("total_return_pct"),
            sharpe_ratio=latest_backtest.get("sharpe_ratio"),
            max_drawdown_pct=latest_backtest.get("max_drawdown_pct"),
            num_trades=latest_backtest.get("num_trades"),
            win_rate=latest_backtest.get("win_rate"),
            starting_portfolio_value=latest_backtest.get("starting_portfolio_value"),
            final_portfolio_value=latest_backtest.get("final_portfolio_value"),
            benchmark_return_pct=latest_backtest.get("benchmark_return_pct"),
        )

    if latest_schema_eval is not None:
        store.update_call_with_schema(
            call_id,
            schema_pass=latest_schema_eval["schema_pass"],
            schema_violations=latest_schema_eval["schema_violations"],
        )

    judge_pass_for_overall: bool | None = None
    if latest_judge_outcome is not None and "error" not in latest_judge_outcome:
        try:
            judge_summary = store.update_call_with_judge(
                call_id,
                judge_score=latest_judge_outcome["judge_score"],
                judge_reasoning=latest_judge_outcome["judge_reasoning"],
                judge_version=latest_judge_outcome["judge_version"],
                failure_mode=latest_judge_outcome["failure_mode"],
                failure_notes=latest_judge_outcome["failure_notes"],
                matches_prompt_intent=latest_judge_outcome["matches_prompt_intent"],
                judge_score_a=latest_judge_outcome.get("judge_score_a"),
                judge_score_b=latest_judge_outcome.get("judge_score_b"),
                judge_reasoning_a=latest_judge_outcome.get("judge_reasoning_a"),
                judge_reasoning_b=latest_judge_outcome.get("judge_reasoning_b"),
                judge_version_a=latest_judge_outcome.get("judge_version_a"),
                judge_version_b=latest_judge_outcome.get("judge_version_b"),
                judge_model_a=latest_judge_outcome.get("judge_model_a"),
                judge_model_b=latest_judge_outcome.get("judge_model_b"),
                judge_error_a=latest_judge_outcome.get("judge_error_a"),
                judge_error_b=latest_judge_outcome.get("judge_error_b"),
            )
            judge_pass_for_overall = judge_summary.get("judge_pass")
            store.update_call(call_id, judge_error=None)
        except Exception as exc:  # noqa: BLE001
            store.update_call(call_id, judge_error=f"{type(exc).__name__}: {exc}")
    elif latest_judge_outcome is not None and "error" in latest_judge_outcome:
        store.update_call(call_id, judge_error=latest_judge_outcome["error"])

    # Per-condition counters + first-pass turn indexes
    store.update_call(
        call_id,
        # Counters are also derivable from the turns table, but storing
        # them here keeps reporting queries cheap.
        # (Storage migration adds these columns; see harness/storage.py.)
        rag_call_count=rag_call_count,
        code_attempt_count=code_attempt_count,
        first_pass_compile=first_pass.get("compile"),
        first_pass_runtime=first_pass.get("runtime"),
        first_pass_trade=first_pass.get("trade"),
        first_pass_schema=first_pass.get("schema"),
        first_pass_judge=first_pass.get("judge"),
    )

    # ==== overall_pass: combine the five stages ===========================
    schema_pass = latest_schema_eval["schema_pass"] if latest_schema_eval else None
    runtime_pass = latest_backtest["runtime_success"] if latest_backtest else None
    trade_pass: bool | None = None
    if latest_backtest and latest_backtest.get("num_trades") is not None:
        trade_pass = latest_backtest["num_trades"] >= 1
    overall_pass = derive_overall_pass(
        compile_pass=compile_pass_for_row,
        runtime_pass=runtime_pass,
        trade_pass=trade_pass,
        schema_pass=schema_pass,
        judge_pass=judge_pass_for_overall,
        evaluation_mode=prompt_record.get("evaluation_mode"),
    )
    store.update_call(call_id, overall_pass=overall_pass)

    # ==== STAGE 6: sidecar artifact =======================================
    final_status = "error" if error_text else "completed"
    artifact_path_str: str | None = None
    artifact_hash: str | None = None
    try:
        artifact = build_artifact(
            call_id=call_id,
            prompt_id=prompt_id,
            model_friendly=model_friendly,
            model_pinned=model_pinned,
            condition_id=condition_id,
            trial_index=trial_index,
            benchmark_version=BENCHMARK_VERSION,
            prompt_set_sha256=prompt_set_sha256,
            judge_version=JUDGE_VERSION,
            judge_threshold=JUDGE_PASS_THRESHOLD,
            original_prompt=prompt_text,
            enriched_prompt=prompt_text,   # v2.1: no preprocessor enrichment
            retrieval_snippet=None,
            response_text=last_response["response_text"] if last_response else None,
            generated_code=final_code,
            raw_response=last_response["raw_response"] if last_response else None,
            finish_reason=last_response["finish_reason"] if last_response else None,
            tools_called=None,             # v2.1: no native tool-use; harness owns retrieval/feedback
            turns_used=turns_used,
            error=error_text,
        )
        # v2.1 extensions: per-condition counters, per-stage first-pass turn,
        # and the labeled context-history transcript exactly as built for the
        # final turn. This is the auditable trace for the academic paper.
        artifact["v2_1"] = {
            "condition_id":        condition_id,
            "rag_call_count":      rag_call_count,
            "code_attempt_count":  code_attempt_count,
            "first_pass":          first_pass,
            "all_pass":            loop_outcome["overall_all_pass"],
            "history":             [_safe_attempt(a) for a in loop_outcome["history"]],
            "system_prompt_sha":   system_prompt_sha,
        }
        artifact_path, artifact_hash = write_artifact(artifact)
        artifact_path_str = str(artifact_path)
    except Exception as persist_exc:  # noqa: BLE001
        artifact_error = f"{type(persist_exc).__name__}: {persist_exc}"
        print(f"[artifact] failed for call {call_id}: {artifact_error}")
        if os.environ.get("LEANBENCH_REQUIRE_ARTIFACTS") == "1":
            final_status = "error"
            if not error_text:
                error_text = f"artifact_write_failed: {artifact_error}"

    try:
        store.update_call(
            call_id,
            status=final_status,
            artifact_path=artifact_path_str,
            artifact_sha256=artifact_hash,
            trajectory_path=artifact_path_str,
            error=error_text,
        )
    except Exception as persist_exc:  # noqa: BLE001
        print(f"[status] failed to persist final status for {call_id}: {persist_exc}")

    return {
        "call_id":           call_id,
        "model":             model_friendly,
        "condition":         condition_id,
        "attempt":           trial_index,
        "status":            final_status,
        "generated_code":    final_code,
        "response_text":     last_response["response_text"] if last_response else None,
        "compile_pass":      compile_pass_for_row,
        "backtest_pass":     runtime_pass,
        "trade_pass":        trade_pass,
        "schema_pass":       schema_pass,
        "judge_pass":        judge_pass_for_overall,
        "overall_pass":      overall_pass,
        "judge_score_a":     (latest_judge_outcome or {}).get("judge_score_a"),
        "judge_score_b":     (latest_judge_outcome or {}).get("judge_score_b"),
        "cost_usd":          total_cost,
        "latency_ms":        int(overall_wall * 1000),
        "input_tokens":      total_input,
        "output_tokens":     total_output,
        "turns_used":        turns_used,
        "rag_call_count":    rag_call_count,
        "code_attempt_count": code_attempt_count,
        "first_pass":        first_pass,
        "error":             error_text,
        "judge_error":       (latest_judge_outcome or {}).get("error"),
    }


def _safe_attempt(attempt: dict) -> dict:
    """Return a JSON-safe copy of one history attempt for the artifact.

    No truncation here — the academic artifact captures the full transcript.
    Callers that need a short preview should derive it from this raw record.
    """
    out: dict[str, Any] = {"kind": attempt.get("kind")}
    for k in ("model_text", "rag_query", "rag_result", "code",
              "compiler_feedback", "reason", "stage_results"):
        if k in attempt and attempt[k] is not None:
            out[k] = attempt[k]
    return out


def _excluded_result(call_id: str, model: str, condition: str, attempt: int, reason: str) -> dict[str, Any]:
    return {
        "call_id":             call_id,
        "model":               model,
        "condition":           condition,
        "attempt":             attempt,
        "status":              "excluded",
        "excluded_reason":     reason,
        "generated_code":      None,
        "response_text":       None,
        "compile_pass":        None,
        "backtest_pass":       None,
        "trade_pass":          None,
        "schema_pass":         None,
        "judge_pass":          None,
        "overall_pass":        None,
        "judge_score_a":       None,
        "judge_score_b":       None,
        "cost_usd":            None,
        "latency_ms":          0,
        "input_tokens":        0,
        "output_tokens":       0,
        "turns_used":          0,
        "rag_call_count":      0,
        "code_attempt_count":  0,
        "first_pass":          {
            "compile": None, "runtime": None, "trade": None,
            "schema":  None, "judge":   None,
        },
        "error":               None,
        "judge_error":         None,
    }


# ---------------------------------------------------------------------------
# Frozen prompt-set guard and top-level grid driver.
# ---------------------------------------------------------------------------


class FrozenPromptSetMismatch(RuntimeError):
    """Raised at run start when the live DB diverges from the frozen artifact."""


def resolve_prompt_set_sha256(store: Store, prompt_id: str) -> str | None:
    prompt = store.get_prompt(prompt_id)
    if prompt is None:
        return None
    if str(prompt.get("source") or "") == "adhoc":
        return None
    if not FROZEN_PROMPT_SET_PATH.exists():
        raise FrozenPromptSetMismatch(
            f"No frozen prompt-set artifact at {FROZEN_PROMPT_SET_PATH}. "
            f"Run `python scripts/freeze_prompt_set.py` before generating against "
            f"benchmark prompts."
        )
    eligible = [p for p in store.list_prompts() if is_eligible(p)]
    live_hash = sha256_of(canonicalize(eligible))
    _, frozen_hash = load_frozen(FROZEN_PROMPT_SET_PATH)
    if live_hash != frozen_hash:
        raise FrozenPromptSetMismatch(
            f"Live prompt-set hash diverges from frozen artifact.\n"
            f"  frozen ({FROZEN_PROMPT_SET_PATH}): {frozen_hash}\n"
            f"  live   ({len(eligible)} prompts):      {live_hash}\n"
            f"Either revert the DB change or re-freeze with "
            f"`python scripts/freeze_prompt_set.py`."
        )
    return frozen_hash


async def run_grid(
    store: Store,
    prompt_id: str,
    prompt_text: str,
    models: list[str],
    conditions: list[str],
    attempts: int | None = None,
    max_turns: int | None = None,
) -> list[dict[str, Any]]:
    """Fan out (model × condition × attempt) cells in parallel.

    Per the proposal: N=5 for C1 baseline, N=3 for agent conditions. Callers
    may pass an explicit integer `attempts` to override (uniform across).

    `max_turns`: when not None, overrides per-call turn limit for agentic
    conditions (C2-C4). C1_oneshot stays pinned to 1 turn regardless.
    """
    prompt_set_sha256 = resolve_prompt_set_sha256(store, prompt_id)

    prompt_row = store.get_prompt(prompt_id)
    if prompt_row and str(prompt_row.get("source") or "") != "adhoc":
        db_text = prompt_row.get("reformulated_text") or prompt_row.get("original_text") or ""
        if db_text:
            prompt_text = db_text

    tasks = []
    for m in models:
        for c in conditions:
            base = store.next_trial_index(prompt_id, m, c)
            cell_attempts = attempts if attempts is not None else default_attempts_for(c)
            for i in range(cell_attempts):
                tasks.append(run_cell(
                    store, prompt_id, prompt_text, m, c,
                    trial_index=base + i,
                    prompt_set_sha256=prompt_set_sha256,
                    max_turns_override=max_turns,
                ))
    return await asyncio.gather(*tasks)
