"""Run a single (prompt × model × condition × trial) cell end-to-end for
LEAN-Bench v2.0 (proposal-faithful build).

5 conditions, all driven by this orchestrator:

    C1_oneshot          1 provider call, no tools                         (N=5)
    C2_docs             agent loop, qc_docs_retrieve only,    T<=24       (N=3)
    C3_compiler         agent loop, lean_backtest only,       T<=24       (N=3)
    C4_docs_compiler    agent loop, BOTH tools,               T<=24       (N=3)
    C5_agent_notools    agent loop, no tools, neutral hop,    T<=24       (N=3)

Per-call lifecycle (mirrors v1 but extended for v2):

  1. (Optional) DESIGN-TIME EXCLUSION pre-flight.
  2. INSERT calls row (status='started') with full identity / prompt-set
     hash / judge threshold so even an errored row is auditable.
  3. AGENT LOOP — provider call -> tool dispatch -> tool_result -> repeat.
     Per-turn rows are written to `turns`. Loop terminates on:
       - max_turns reached, or
       - model returns no tool calls AND has emitted a fenced code block
         (final assistant message), or
       - lean_backtest tool returned exit_status='docker_error' (hard error;
         we do NOT silently degrade — proposal §Procedure requires the
         compiler feedback signal to be real LEAN), or
       - AST compile failure on a code-only response in C1 (single-turn
         conditions short-circuit).
  4. PIPELINE on final code:
       Stage 1  compile    (AST)
       Stage 2  runtime    (LEAN backtest via harness/lean_executor)
       Stage 3  trade      (num_trades > 0)
       Stage 4  schema     (mechanical, harness/evaluator.evaluate_schema)
       Stage 5  judge      (dual-judge, harness/judge.judge_call)
  5. SIDECAR artifact (results/artifacts/{call_id}.json).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from harness.agent_tools import dispatch
from harness.artifacts import build_artifact, write_artifact
from harness.conditions.builder import build_tools, is_agentic, max_turns_for, tool_names_for
from harness.constants import (
    BENCHMARK_VERSION, JUDGE_PASS_THRESHOLD, excluded_reason_for,
)
from harness.evaluator import (
    derive_overall_pass,
    evaluate_compile,
    evaluate_schema,
)
from harness.judge import JUDGE_VERSION, JudgeError, judge_call
from harness.lean_executor import run_backtest
from harness.models import (
    CONDITIONS, DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_TEMPERATURE, DEFAULT_TOP_P,
    MODELS_FROZEN, default_attempts_for,
)
from harness.pricing import PricingNotSetError, cost_usd
from harness.prompt_freeze import canonicalize, is_eligible, load_frozen, sha256_of
from harness.providers import anthropic_client, gemini_client, openai_client
from harness.providers.base import ProviderResponse
from harness.storage import Store


FROZEN_PROMPT_SET_PATH = Path("results/frozen/prompt_set_v1.json")


PROVIDER_CALL = {
    "anthropic": anthropic_client.call,
    "openai":    openai_client.call,
    "google":    gemini_client.call,
}

PROVIDER_TOOL_RESULT_BUILDER = {
    "anthropic": anthropic_client.build_tool_result_message,
    "openai":    openai_client.build_tool_result_message,
    "google":    gemini_client.build_tool_result_message,
}


SYSTEM_PROMPT = (
    "You are an expert algorithmic-trading engineer. Generate a complete "
    "QuantConnect LEAN algorithm in Python that fulfills the user's request. "
    "The class should subclass QCAlgorithm and implement Initialize and OnData.\n\n"
    "If a `Required schema` block is included in the user message, your "
    "SetStartDate / SetEndDate calls, security subscriptions (AddEquity / "
    "AddCrypto / etc.), and Resolution arguments MUST match those values "
    "exactly — do not invent your own date window, tickers, or resolution.\n\n"
    "When you have finished iterating, return your FINAL algorithm as a "
    "single fenced ```python ... ``` block in a plain assistant message with "
    "no tool calls — that message is what the harness scores.\n\n"
    "Tool guidance (when tools are available):\n"
    "- qc_docs_retrieve(query): use to look up LEAN APIs you are unsure about. "
    "Issue concise queries describing what you need to do.\n"
    "- lean_backtest(code, language='python'): use to run your candidate "
    "algorithm against the pinned LEAN engine and read the filtered log. "
    "Iterate until the log shows LEAN_RUN_FINISHED and ORDERS_PLACED > 0 (or "
    "until you are confident the algorithm is correct)."
)
SYSTEM_PROMPT_SHA256 = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()


# Neutral continuation message used by C5 (agent without tools). Keeping the
# wording flat / unbiased — we are isolating the value of in-context iteration
# without leaking any feedback signal.
C5_CONTINUATION_PROMPT = (
    "Please review your previous algorithm and submit an improved version. "
    "If you believe the algorithm is already correct, simply return the same "
    "code as your final answer."
)


def _safe_cost(model_pinned: str, in_tok: int, out_tok: int, cached: int) -> float | None:
    try:
        return cost_usd(model_pinned, in_tok, out_tok, cached)
    except PricingNotSetError:
        return None
    except Exception:
        return None


# --- helpers -------------------------------------------------------------

def _last_code_from_tool_calls(response: ProviderResponse) -> str | None:
    """If the model's tool calls included a lean_backtest invocation, return
    the `code` arg from the most recent one. This becomes a fallback for the
    'final code' when the model never emits a plain text code fence."""
    last: str | None = None
    for tc in response["tool_calls"]:
        if tc["name"] == "lean_backtest":
            code = tc["input"].get("code")
            if isinstance(code, str) and code.strip():
                last = code
    return last


def _agentic_continuation_message(provider: str) -> dict:
    """Per-provider canonical 'continue with no feedback' user message.

    For C5 only. We never inject this into the tool-using conditions
    because they have natural follow-ups (tool_result)."""
    if provider == "google":
        from google.genai import types as genai_types
        part = genai_types.Part(text=C5_CONTINUATION_PROMPT)
        return {"role": "user", "_gemini_parts": [part]}
    if provider == "openai":
        return {"role": "user", "content": C5_CONTINUATION_PROMPT}
    return {"role": "user", "content": C5_CONTINUATION_PROMPT}


def _render_schema_block(prompt_record: dict | None) -> str | None:
    """Render a `Required schema` block from the prompt's metadata.

    Returns None when the prompt has no useful schema fields (e.g. ad-hoc
    prompts inserted via /api/generate, which only carry text). The block is
    appended to the initial user message so the model has explicit, unambiguous
    targets for SetStartDate/SetEndDate, securities, and resolution — fields
    that the post-hoc schema evaluator checks against.
    """
    if not prompt_record:
        return None
    start_date = (prompt_record.get("start_date") or "").strip()
    end_date = (prompt_record.get("end_date") or "").strip()
    securities = (prompt_record.get("securities_type") or "").strip()
    resolution = (prompt_record.get("resolution") or "").strip()
    tickers = prompt_record.get("tickers")
    if isinstance(tickers, str):
        try:
            tickers = json.loads(tickers)
        except (TypeError, json.JSONDecodeError):
            tickers = [tickers] if tickers else []
    tickers = tickers or []

    if not (start_date or end_date or securities or resolution or tickers):
        return None

    lines = ["Required schema (your code must match these exactly):"]
    if start_date:
        lines.append(f"- Start date: {start_date}")
    if end_date:
        lines.append(f"- End date:   {end_date}")
    if securities or tickers:
        sec = securities or "equity"
        tick_str = f" ({', '.join(tickers)})" if tickers else ""
        lines.append(f"- Securities: {sec}{tick_str}")
    if resolution:
        lines.append(f"- Resolution: {resolution}")
    return "\n".join(lines)


def _summarise_tool_event(tool_call: dict, tool_output: dict) -> dict:
    """Compact, UI-friendly summary of a single tool dispatch.

    Truncation policy:
      - qc_docs_retrieve: query is short; output is up to ~12KB so we cap a
        preview at 800 chars (the modal lets the user expand).
      - lean_backtest: code can be huge — we record the SHA + length only and
        keep a 1.6KB tail of the log (where ERROR::, ORDERS_PLACED, and
        LEAN_RUN_FINISHED live).
    """
    name = tool_call["name"]
    inp = tool_call.get("input") or {}
    out_text = tool_output.get("output") or ""
    meta = tool_output.get("metadata") or {}

    event: dict[str, Any] = {
        "name":       name,
        "is_error":   bool(tool_output.get("is_error", False)),
        "output_len": len(out_text),
    }

    if name == "qc_docs_retrieve":
        event["query"] = (inp.get("query") or "")[:500]
        event["output_preview"] = out_text[:800]
    elif name == "lean_backtest":
        code = inp.get("code") or ""
        event["language"] = inp.get("language") or "python"
        event["code_chars"] = len(code)
        event["code_sha8"] = hashlib.sha256(code.encode("utf-8")).hexdigest()[:8] if code else None
        # Last 1.6KB carries the actionable trailer (ORDERS_PLACED:N,
        # LEAN_RUN_FINISHED / TIMEOUT_EXCEEDED / INFRASTRUCTURE_ERROR).
        event["log_tail"] = out_text[-1600:]
        event["exit_status"] = meta.get("exit_status")
    else:
        event["input_preview"]  = json.dumps(inp, separators=(",", ":"))[:500]
        event["output_preview"] = out_text[:800]

    return event


async def _run_agent_loop(
    provider: str,
    model_pinned: str,
    messages: list[dict],
    tools: list[dict] | None,
    max_turns: int,
    store: Store,
    call_id: str,
    record_turns: bool,
    *,
    c5_neutral_hop: bool = False,
) -> dict[str, Any]:
    """Drive the multi-turn loop. Returns a dict carrying the final code,
    aggregated tokens, last response, error text (if any), and turn count.

    Behaviors:
      - C1: callers pass max_turns=1; no continuation hop; loop returns after
        the first response.
      - C2/C3/C4: callers pass tools=[...]; this function dispatches each
        tool_use to harness.agent_tools.dispatch and round-trips the result.
      - C5: callers pass tools=None AND c5_neutral_hop=True; after each
        response we append C5_CONTINUATION_PROMPT and keep iterating.

    Hard error contract: if a lean_backtest dispatch returns is_error=True
    with exit_status='docker_error', we abort the loop with an error string.
    The orchestrator treats this as a call-level failure.
    """
    provider_call = PROVIDER_CALL[provider]
    build_tool_result = PROVIDER_TOOL_RESULT_BUILDER[provider]

    total_input = total_output = total_cached = 0
    total_wall = 0.0
    last_response: ProviderResponse | None = None
    final_code: str | None = None
    final_code_turn_index: int | None = None
    error_text: str | None = None
    turns_used = 0

    for turn_index in range(max_turns):
        try:
            resp = await provider_call(
                model_pinned=model_pinned,
                messages=messages,
                system_prompt=SYSTEM_PROMPT,
                tools=tools,
                max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
                temperature=DEFAULT_TEMPERATURE,
            )
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            break

        turns_used += 1
        total_input += resp["input_tokens"]
        total_output += resp["output_tokens"]
        total_cached += resp["cached_tokens"]
        total_wall += resp["latency_ms"] / 1000
        last_response = resp

        # Code on this turn — prefer the model's assistant code fence,
        # fall back to the most recent lean_backtest tool input.
        prev_code = final_code
        if resp["generated_code"]:
            final_code = resp["generated_code"]
        else:
            maybe_tool_code = _last_code_from_tool_calls(resp)
            if maybe_tool_code is not None:
                final_code = maybe_tool_code
        if final_code is not None and final_code != prev_code:
            final_code_turn_index = turn_index

        # Per-turn AST evaluation (cheap; used for telemetry + C1 short-circuit).
        compile_eval = evaluate_compile(final_code)

        # Tool events for this turn get filled in below after dispatch — store
        # the per-turn write at the END of the turn so the events are present.
        per_turn_tool_events: list[dict] = []

        # If the model emitted tool_use blocks, dispatch them and round-trip
        # the results into the next turn. Otherwise we treat the response as
        # 'final' (assistant message, possibly with code).
        if resp["tool_calls"]:
            # Append the model's assistant turn verbatim (provider-shaped).
            messages.append(resp["raw_assistant_turn"])

            # Dispatch each tool_use in parallel; gather their outputs.
            dispatch_tasks = [
                dispatch(tc["name"], tc["input"]) for tc in resp["tool_calls"]
            ]
            outputs = await asyncio.gather(*dispatch_tasks, return_exceptions=False)

            # Capture compact summaries of each tool event for the UI.
            for tc, out in zip(resp["tool_calls"], outputs):
                per_turn_tool_events.append(_summarise_tool_event(tc, out))

            # Hard-error gate: any docker_error from lean_backtest aborts.
            for tc, out in zip(resp["tool_calls"], outputs):
                if tc["name"] == "lean_backtest" and out.get("metadata", {}).get("exit_status") == "docker_error":
                    error_text = (
                        f"lean_backtest reported docker_error on turn {turn_index}: "
                        f"{out['output'][:300]}"
                    )
                    break
            if error_text:
                _write_turn(
                    store, call_id, turn_index, messages, resp, final_code,
                    compile_eval, per_turn_tool_events, record_turns,
                    model_pinned,
                )
                break

            # Build the tool_result(s) and append as the next user message.
            tool_result_items = [
                build_tool_result(tc, out) for tc, out in zip(resp["tool_calls"], outputs)
            ]
            if provider == "anthropic":
                # Anthropic expects a single user turn with a content list of
                # tool_result blocks.
                messages.append({"role": "user", "content": tool_result_items})
            elif provider == "openai":
                # OpenAI Responses API takes function_call_output items as
                # standalone input entries — splice them in directly.
                messages.extend(tool_result_items)
            else:  # google
                # Each Gemini function_response goes in its own user Content.
                messages.extend(tool_result_items)
            # Persist this turn (with its tool events) before continuing.
            _write_turn(
                store, call_id, turn_index, messages, resp, final_code,
                compile_eval, per_turn_tool_events, record_turns, model_pinned,
            )
            # Continue the loop — model gets to use the tool output next turn.
            continue

        # No tool calls this turn. If we have any code, we're done — assistant
        # has emitted what we should evaluate.
        if c5_neutral_hop and turn_index < max_turns - 1:
            # C5: keep iterating with a neutral continuation prompt. Append
            # the assistant turn so the model sees its own history.
            messages.append({"role": "assistant", "content": resp["response_text"]})
            messages.append(_agentic_continuation_message(provider))
            _write_turn(
                store, call_id, turn_index, messages, resp, final_code,
                compile_eval, per_turn_tool_events, record_turns, model_pinned,
                feedback_text=C5_CONTINUATION_PROMPT,
            )
            continue

        # C1, or tool-condition where model ended without a tool call.
        # If we have code, exit. Otherwise let the loop iterate once more
        # (gives the model a chance to recover) until max_turns.
        _write_turn(
            store, call_id, turn_index, messages, resp, final_code,
            compile_eval, per_turn_tool_events, record_turns, model_pinned,
        )
        if final_code is not None:
            break
        # No code yet and no tools — only meaningful for C5 / fallback.
        if c5_neutral_hop:
            continue
        break

    # Mark the turn that produced the final code so the UI can jump to it.
    if record_turns and final_code_turn_index is not None:
        try:
            store.mark_final_turn(call_id, final_code_turn_index)
        except Exception as exc:  # noqa: BLE001
            print(f"[orchestrator] failed to mark final turn: {exc}")

    return {
        "final_code":   final_code,
        "final_code_turn_index": final_code_turn_index,
        "last_response": last_response,
        "turns_used":   turns_used,
        "total_input":  total_input,
        "total_output": total_output,
        "total_cached": total_cached,
        "total_wall":   total_wall,
        "error_text":   error_text,
    }


def _write_turn(
    store: Store,
    call_id: str,
    turn_index: int,
    messages: list[dict],
    resp: ProviderResponse,
    final_code: str | None,
    compile_eval: dict,
    tool_events: list[dict],
    record_turns: bool,
    model_pinned: str,
    *,
    feedback_text: str | None = None,
) -> None:
    """Single point of truth for writing a turns row from the loop."""
    if not record_turns:
        return
    turn_cost = _safe_cost(
        model_pinned, resp["input_tokens"], resp["output_tokens"], resp["cached_tokens"],
    )
    try:
        store.record_turn(
            call_id=call_id,
            turn_index=turn_index,
            prompt_messages_json=json.dumps(
                _safe_serialise_messages(messages), separators=(",", ":")
            ),
            response_text=resp["response_text"],
            response_code_extracted=final_code,
            response_tokens_in=resp["input_tokens"],
            response_tokens_out=resp["output_tokens"],
            ran_pipeline=True,
            compile_pass=compile_eval["compile_pass"],
            backtest_pass=None,
            trade_pass=None,
            judge_pass=None,
            feedback_text=feedback_text,
            cost_usd=turn_cost,
            wall_clock_seconds=resp["latency_ms"] / 1000,
            tool_events_json=tool_events or None,
            is_final_turn=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[orchestrator] failed to record turn {turn_index}: {exc}")


def _safe_serialise_messages(messages: list[dict]) -> list[dict]:
    """Strip the per-provider raw-object fields out of message dicts before
    JSON-encoding for the turns table. The raw provider structures (e.g.,
    Anthropic content blocks, Gemini Parts) aren't JSON-serialisable directly
    in every case; this best-effort flattens them to summary dicts."""
    out: list[dict] = []
    for m in messages:
        if isinstance(m, dict) and "_gemini_parts" in m:
            out.append({
                "role": m.get("role"),
                "content_summary": f"<{len(m['_gemini_parts'])} gemini parts>",
            })
            continue
        try:
            json.dumps(m)
            out.append(m)
        except (TypeError, ValueError):
            out.append({"role": m.get("role"), "content_summary": "<unserializable>"})
    return out


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

    See module docstring for the full pipeline. Always writes one `calls` row
    (even on provider error or excluded cell) and the appropriate `turns`
    rows. Returns a result dict matching the CallResult Pydantic schema.

    `max_turns_override`: when not None, overrides the condition default for
    agentic conditions (C2-C5). C1_oneshot is immune — it always runs 1 turn,
    because increasing it would change the meaning of the one-shot baseline.
    """
    cond = CONDITIONS[condition_id]
    model_info = MODELS_FROZEN[model_friendly]
    provider = model_info["provider"]
    model_pinned = model_info["model_id"]
    model_family = model_info["model_family"]

    call_id = str(uuid.uuid4())
    tools = build_tools(condition_id, provider) or None
    max_turns = max_turns_for(condition_id)
    if max_turns_override is not None and cond.get("tool_agentic_loop"):
        max_turns = max_turns_override

    # ==== Pre-flight: design-time cell exclusion ====
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
            system_prompt_sha=SYSTEM_PROMPT_SHA256,
            status="excluded",
            excluded_reason=excl_reason,
            benchmark_version=BENCHMARK_VERSION,
            prompt_set_sha256=prompt_set_sha256,
        )
        return _excluded_result(call_id, model_friendly, condition_id, trial_index, excl_reason)

    # ==== STAGE 1: create_call ====
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
        system_prompt_sha=SYSTEM_PROMPT_SHA256,
        # v2 retrieval is in-loop, so no preprocessor snippet.
        retrieval_snippet=None,
        status="started",
        benchmark_version=BENCHMARK_VERSION,
        prompt_set_sha256=prompt_set_sha256,
        judge_threshold=JUDGE_PASS_THRESHOLD,
    )

    # ==== STAGE 2: AGENT LOOP ====
    overall_start = time.monotonic()

    # Fetch the prompt record once and reuse it for both the user-message
    # schema block (here) and the post-loop schema/judge stages (below).
    # Ad-hoc prompts won't carry schema fields — _render_schema_block returns
    # None in that case and we send the raw text.
    prompt_record = store.get_prompt(prompt_id)
    schema_block = _render_schema_block(prompt_record)
    user_content = (
        f"{prompt_text}\n\n{schema_block}" if schema_block else prompt_text
    )
    messages: list[dict] = [{"role": "user", "content": user_content}]

    loop_outcome = await _run_agent_loop(
        provider=provider,
        model_pinned=model_pinned,
        messages=messages,
        tools=tools,
        max_turns=max_turns,
        store=store,
        call_id=call_id,
        record_turns=is_agentic(condition_id),
        c5_neutral_hop=(condition_id == "C5_agent_notools"),
    )

    final_code = loop_outcome["final_code"]
    error_text = loop_outcome["error_text"]
    last_response = loop_outcome["last_response"]
    turns_used = loop_outcome["turns_used"]
    total_input = loop_outcome["total_input"]
    total_output = loop_outcome["total_output"]
    total_cached = loop_outcome["total_cached"]
    total_wall_loop = loop_outcome["total_wall"]

    total_cost = _safe_cost(model_pinned, total_input, total_output, total_cached)
    final_code_sha = hashlib.sha256((final_code or "").encode()).hexdigest()
    overall_wall = time.monotonic() - overall_start

    # First fold loop outputs onto the row.
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
    )

    # ==== STAGE 3a: compile (AST) on the final code ====
    compile_eval = evaluate_compile(final_code)
    store.update_call(call_id, compile_pass=compile_eval["compile_pass"])

    # ==== STAGE 3b/3c: runtime + trade (LEAN backtest) ====
    backtest_result: dict[str, Any] = {}
    if final_code and not error_text:
        try:
            backtest_result = await run_backtest(final_code, store, call_id)
        except Exception as exc:  # noqa: BLE001
            err_text = f"{type(exc).__name__}: {exc}"
            print(f"[backtest] unexpected: {err_text}")
            try:
                backtest_result = store.update_call_with_backtest(
                    call_id,
                    compile_success=None,
                    runtime_success=None,
                    runtime_error=f"backtest crashed: {err_text}",
                )
            except Exception as persist_exc:  # noqa: BLE001
                print(f"[backtest] failed to persist crash: {persist_exc}")

    # ==== STAGE 4: schema-adherence ====
    # `prompt_record` was fetched once above for the user-message schema block;
    # reuse it here. Ad-hoc prompts won't be in the DB; fall back to the raw
    # prompt text so evaluate_schema/judge_call still have something to chew on.
    if prompt_record is None:
        prompt_record = {
            "reformulated_text": prompt_text,
            "original_text":     prompt_text,
        }
    schema_eval = evaluate_schema(final_code, prompt_record)
    store.update_call_with_schema(
        call_id,
        schema_pass=schema_eval["schema_pass"],
        schema_violations=schema_eval["schema_violations"],
    )

    # ==== STAGE 5: dual-judge ====
    judge_outcome: dict[str, Any] = {}
    judge_error_text: str | None = None
    if final_code and not error_text:
        try:
            judge_result = await judge_call(
                prompt_record=prompt_record,
                generated_code=final_code,
                backtest_result=backtest_result,
                judge_version=JUDGE_VERSION,
            )
            judge_outcome = store.update_call_with_judge(
                call_id,
                judge_score=judge_result["judge_score"],
                judge_reasoning=judge_result["judge_reasoning"],
                judge_version=judge_result["judge_version"],
                failure_mode=judge_result["failure_mode"],
                failure_notes=judge_result["failure_notes"],
                matches_prompt_intent=judge_result["matches_prompt_intent"],
                judge_score_a=judge_result["judge_score_a"],
                judge_score_b=judge_result["judge_score_b"],
                judge_reasoning_a=judge_result["judge_reasoning_a"],
                judge_reasoning_b=judge_result["judge_reasoning_b"],
                judge_version_a=judge_result["judge_version_a"],
                judge_version_b=judge_result["judge_version_b"],
                judge_model_a=judge_result["judge_model_a"],
                judge_model_b=judge_result["judge_model_b"],
                judge_error_a=judge_result["judge_error_a"],
                judge_error_b=judge_result["judge_error_b"],
            )
            store.update_call(call_id, judge_error=None)
        except JudgeError as exc:
            judge_error_text = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001
            judge_error_text = f"{type(exc).__name__}: {exc}"
        if judge_error_text:
            try:
                store.update_call(call_id, judge_error=judge_error_text)
            except Exception as persist_exc:  # noqa: BLE001
                print(f"[judge] failed to persist error: {persist_exc}")

    # ==== overall_pass: combine the five stages ====
    judge_pass = judge_outcome.get("judge_pass")
    overall_pass = derive_overall_pass(
        compile_pass=compile_eval["compile_pass"],
        runtime_pass=backtest_result.get("runtime_success"),
        trade_pass=backtest_result.get("trade_pass"),
        schema_pass=schema_eval["schema_pass"],
        judge_pass=judge_pass,
        evaluation_mode=prompt_record.get("evaluation_mode"),
    )
    store.update_call(call_id, overall_pass=overall_pass)

    # ==== STAGE 6: sidecar artifact ====
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
            enriched_prompt=prompt_text,           # v2: no preprocessor enrichment
            retrieval_snippet=None,
            response_text=last_response["response_text"] if last_response else None,
            generated_code=final_code,
            raw_response=last_response["raw_response"] if last_response else None,
            finish_reason=last_response["finish_reason"] if last_response else None,
            tools_called=last_response["tools_called"] if last_response else None,
            turns_used=turns_used,
            error=error_text,
        )
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
        "call_id":             call_id,
        "model":               model_friendly,
        "condition":           condition_id,
        "attempt":             trial_index,
        "status":              final_status,
        "generated_code":      final_code,
        "response_text":       last_response["response_text"] if last_response else None,
        "compile_pass":        compile_eval["compile_pass"],
        "backtest_pass":       backtest_result.get("backtest_pass"),
        "trade_pass":          backtest_result.get("trade_pass"),
        "schema_pass":         schema_eval["schema_pass"],
        "judge_pass":          judge_pass,
        "overall_pass":        overall_pass,
        "judge_score_a":       judge_outcome.get("judge_score_a"),
        "judge_score_b":       judge_outcome.get("judge_score_b"),
        "cost_usd":            total_cost,
        "latency_ms":          int(overall_wall * 1000),
        "input_tokens":        total_input,
        "output_tokens":       total_output,
        "turns_used":          turns_used,
        "error":               error_text,
        "judge_error":         judge_error_text,
    }


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
        "error":               None,
        "judge_error":         None,
    }


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
    """Fan out (model × condition × attempt) cells in parallel via asyncio.gather.

    Per the proposal, attempts default per-condition: N=5 for the C1
    baseline, N=3 for the agent conditions. Callers may still pass an explicit
    integer `attempts` to override (uniform across conditions).

    `max_turns`: when not None, overrides per-call turn limit for agentic
    conditions (C2-C5). C1_oneshot stays pinned to 1 turn regardless.
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
