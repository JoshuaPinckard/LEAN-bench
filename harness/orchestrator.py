"""Run a single (prompt × model × condition) cell end-to-end.

For S1/S2/S3 (max_turns=1): one provider call, one evaluator pass, one row in
`calls`, zero rows in `turns`.

For A1_agentic_full (max_turns=10): up to 10 turns. Each iteration is:
  1. send full message history to provider
  2. extract code from response, run evaluator
  3. write a row to `turns` capturing this iteration's input, output, eval, and
     the feedback that was sent back to the model (or None if final)
  4. stop if overall_pass is True, or if the evaluator returned no feedback
     (nothing to refine), or if max_turns reached
At the end, one row is written to `calls` with aggregated tokens/cost and
`turns_used` set to the number of iterations that actually executed.

Per-turn rows let downstream analysis derive the T1...T10 cumulative success
curve that is the headline figure of LEAN-Bench.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any

from harness.conditions.builder import build_tools, is_agentic, max_turns_for
from harness.evaluator import evaluate
from harness.models import (
    CONDITIONS, DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_TEMPERATURE, DEFAULT_TOP_P,
    MODELS_FROZEN,
)
from harness.pricing import PricingNotSetError, cost_usd
from harness.providers import anthropic_client, gemini_client, openai_client
from harness.judge import JUDGE_VERSION, JudgeError, judge_call
from harness.lean_executor import run_backtest
from harness.retrieval import get_retrieval_snippet
from harness.storage import Store


PROVIDER_CALL = {
    "anthropic": anthropic_client.call,
    "openai":    openai_client.call,
    "google":    gemini_client.call,
}

# Conditions where the retrieval preprocessor injects a shared LEAN docs snippet
# into the prompt before any model call. Goal: every model in these conditions
# sees identical baseline API info, eliminating retrieval-bias between providers.
# S1_base remains untouched (pure parametric baseline).
CONDITIONS_WITH_RETRIEVAL: frozenset[str] = frozenset(
    {"S2_docs", "A1_agentic_full"}
)

# TODO: replace with the real ~2K-token LEAN API description per the design memo.
SYSTEM_PROMPT = (
    "You are an expert algorithmic-trading engineer. Generate a complete "
    "QuantConnect LEAN algorithm in Python that fulfills the user's request. "
    "Return ONLY a single fenced ```python ... ``` block — no prose before "
    "or after. The class should subclass QCAlgorithm and implement Initialize "
    "and OnData."
)
SYSTEM_PROMPT_SHA256 = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()


def _safe_cost(model_pinned: str, in_tok: int, out_tok: int, cached: int) -> float | None:
    """Return cost in USD, or None if pricing isn't set yet (so the dev UI
    can still display the call)."""
    try:
        return cost_usd(model_pinned, in_tok, out_tok, cached)
    except PricingNotSetError:
        return None
    except Exception:
        return None


async def run_cell(
    store: Store,
    prompt_id: str,
    prompt_text: str,
    model_friendly: str,
    condition_id: str,
    trial_index: int,
) -> dict[str, Any]:
    """Run one (prompt × model × condition × trial_index) cell. Always writes
    one `calls` row (even on provider error) and the appropriate `turns`
    rows. Returns a result dict matching the CallResult Pydantic schema.

    trial_index must be pre-allocated by the caller (run_grid) so concurrent
    cells with the same (prompt, model, condition) don't collide on the
    UNIQUE(prompt_id, model_id, condition_id, trial_index) index.
    """
    cond = CONDITIONS[condition_id]
    model_info = MODELS_FROZEN[model_friendly]
    provider = model_info["provider"]
    model_pinned = model_info["model_id"]
    model_family = model_info["model_family"]

    call_id = str(uuid.uuid4())
    tools = build_tools(condition_id, provider) or None
    provider_call = PROVIDER_CALL[provider]
    max_turns = max_turns_for(condition_id)

    base_kwargs = dict(
        model_pinned=model_pinned,
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
    )

    # Retrieval preprocessor: enrich the prompt with a shared LEAN docs snippet
    # for tool-using conditions. Cached per-prompt so all six models see the
    # identical snippet. Empty snippet => no augmentation.
    retrieval_snippet: str | None = None
    enriched_prompt = prompt_text
    if condition_id in CONDITIONS_WITH_RETRIEVAL:
        try:
            retrieval_snippet = await get_retrieval_snippet(prompt_text, store)
        except Exception as exc:
            retrieval_snippet = None
            # Retrieval failures must not kill the call.
            print(f"[retrieval] failed for call {call_id}: {type(exc).__name__}: {exc}")
        if retrieval_snippet:
            enriched_prompt = (
                f"{prompt_text}\n\n"
                f"--- RELEVANT QUANTCONNECT LEAN DOCUMENTATION ---\n\n"
                f"{retrieval_snippet}"
            )

    # ==== STAGE 1: create_call ====
    # Insert the row up front so the staged update_call_with_backtest /
    # update_call_with_judge helpers have a row to UPDATE against.
    store.create_call(
        call_id=call_id,
        prompt_id=prompt_id,
        model_family=model_family,
        model_id=model_friendly,
        model_version=model_pinned,
        condition=condition_id,                # mirrored to legacy condition_id
        pass_number=trial_index,               # mirrored to legacy trial_index
        tool_docs_retrieval=cond["tool_docs_retrieval"],
        tool_web_search=cond["tool_web_search"],
        tool_agentic_loop=cond["tool_agentic_loop"],
        max_turns_allowed=max_turns,
        temperature=DEFAULT_TEMPERATURE,
        top_p=DEFAULT_TOP_P,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        system_prompt_sha=SYSTEM_PROMPT_SHA256,
        retrieval_snippet=retrieval_snippet,
    )

    messages: list[dict] = [{"role": "user", "content": enriched_prompt}]
    total_input = 0
    total_output = 0
    total_cached = 0
    total_wall = 0.0
    last_response = None
    last_eval = None
    final_code = None
    turns_used = 0
    error_text: str | None = None

    overall_start = time.monotonic()

    for turn_index in range(max_turns):
        try:
            resp = await provider_call(messages=messages, **base_kwargs)
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            break

        turns_used += 1
        total_input += resp["input_tokens"]
        total_output += resp["output_tokens"]
        total_cached += resp["cached_tokens"]
        total_wall += resp["latency_ms"] / 1000

        ev = evaluate(resp["generated_code"])
        last_response = resp
        last_eval = ev
        final_code = resp["generated_code"]

        # Only write per-turn rows for the agentic condition (per schema design
        # memo: turns table is for A1_agentic_full only).
        if is_agentic(condition_id):
            turn_cost = _safe_cost(
                model_pinned, resp["input_tokens"], resp["output_tokens"], resp["cached_tokens"],
            )
            store.record_turn(
                call_id=call_id,
                turn_index=turn_index,
                prompt_messages_json=json.dumps(messages, separators=(",", ":")),
                response_text=resp["response_text"],
                response_code_extracted=resp["generated_code"],
                response_tokens_in=resp["input_tokens"],
                response_tokens_out=resp["output_tokens"],
                ran_pipeline=True,
                compile_pass=ev["compile_pass"],
                backtest_pass=ev["backtest_pass"],
                trade_pass=ev["trade_pass"],
                judge_pass=ev["judge_pass"],
                feedback_text=ev["feedback"],
                cost_usd=turn_cost,
                wall_clock_seconds=resp["latency_ms"] / 1000,
            )

        # Decide whether to refine or stop.
        if ev["overall_pass"]:
            break
        if ev["feedback"] is None:
            # No actionable feedback (compile passed and we have no further
            # checks today). Stop; the call is final.
            break
        if turn_index == max_turns - 1:
            break

        # Append assistant turn + user feedback for the next iteration.
        messages.append({"role": "assistant", "content": resp["response_text"]})
        messages.append({"role": "user",      "content": ev["feedback"]})

    total_cost = _safe_cost(model_pinned, total_input, total_output, total_cached)
    final_code_sha = hashlib.sha256((final_code or "").encode()).hexdigest()
    overall_wall = time.monotonic() - overall_start

    eval_for_call = last_eval or {
        "compile_pass": None, "backtest_pass": None, "trade_pass": None,
        "judge_pass": None, "overall_pass": None, "failure_l1": None, "failure_l2": None,
    }

    # ==== STAGE 2: update with generation outputs ====
    # Fold model loop results plus legacy pipeline fields onto the row.
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
        # Legacy pipeline outcomes (kept for back-compat queries)
        compile_pass=eval_for_call["compile_pass"],
        backtest_pass=eval_for_call["backtest_pass"],
        trade_pass=eval_for_call["trade_pass"],
        judge_pass=eval_for_call["judge_pass"],
        overall_pass=eval_for_call["overall_pass"],
        first_failed_stage=None,
        failure_category_l1=eval_for_call["failure_l1"],
        failure_category_l2=eval_for_call["failure_l2"],
        trajectory_path=None,
        error=error_text,
    )

    # ==== STAGE 3: backtest ====
    # lean_executor materializes a temp project, runs `lean backtest`, parses
    # the results JSON, and writes the metrics via update_call_with_backtest.
    # Returns the result dict so the judge can score against real numbers.
    backtest_result: dict[str, Any] = {}
    if final_code and not error_text:
        try:
            backtest_result = await run_backtest(final_code, store, call_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[backtest] unexpected: {type(exc).__name__}: {exc}")

    # ==== STAGE 4: judge ====
    # Score implementation correctness against the prompt's stated intent,
    # using the real backtest result from stage 3. The judge is robust to
    # cases where the backtest was skipped (LEAN CLI absent / timed out).
    judge_outcome: dict[str, Any] = {}
    if final_code and not error_text:
        try:
            prompt_record = store.get_prompt(prompt_id) or {
                "reformulated_text": prompt_text,
                "original_text": prompt_text,
            }
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
            )
        except JudgeError as exc:
            print(f"[judge] {type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[judge] unexpected: {type(exc).__name__}: {exc}")

    return {
        "call_id": call_id,
        "model": model_friendly,
        "condition": condition_id,
        "attempt": trial_index,
        "status": "error" if error_text else "completed",
        "generated_code": final_code,
        "response_text": last_response["response_text"] if last_response else None,
        "compile_pass": eval_for_call["compile_pass"],
        "backtest_pass": backtest_result.get("backtest_pass", eval_for_call["backtest_pass"]),
        "trade_pass": backtest_result.get("trade_pass", eval_for_call["trade_pass"]),
        "judge_pass": judge_outcome.get("judge_pass", eval_for_call["judge_pass"]),
        "overall_pass": judge_outcome.get("overall_pass", eval_for_call["overall_pass"]),
        "failure_category_l1": eval_for_call["failure_l1"],
        "failure_category_l2": eval_for_call["failure_l2"],
        "cost_usd": total_cost,
        "latency_ms": int(overall_wall * 1000),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "turns_used": turns_used,
        "error": error_text,
    }


async def run_grid(
    store: Store,
    prompt_id: str,
    prompt_text: str,
    models: list[str],
    conditions: list[str],
    attempts: int = 1,
) -> list[dict[str, Any]]:
    """Fan out (model × condition × attempt) cells in parallel via asyncio.gather.

    Pre-allocates trial_index for each task BEFORE launching, so concurrent
    cells with the same (prompt, model, condition) don't collide on the
    unique index when an awaited API call yields the event loop between
    next_trial_index() and record_call().
    """
    tasks = []
    for m in models:
        for c in conditions:
            base = store.next_trial_index(prompt_id, m, c)
            for i in range(attempts):
                tasks.append(run_cell(
                    store, prompt_id, prompt_text, m, c,
                    trial_index=base + i,
                ))
    return await asyncio.gather(*tasks)
