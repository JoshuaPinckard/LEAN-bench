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
import os
import time
import uuid
from pathlib import Path
from typing import Any

from harness.artifacts import build_artifact, write_artifact
from harness.conditions.builder import build_tools, is_agentic, max_turns_for
from harness.constants import (
    BENCHMARK_VERSION, JUDGE_PASS_THRESHOLD, excluded_reason_for,
)
from harness.evaluator import evaluate
from harness.models import (
    CONDITIONS, DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_TEMPERATURE, DEFAULT_TOP_P,
    MODELS_FROZEN,
)
from harness.pricing import PricingNotSetError, cost_usd
from harness.prompt_freeze import canonicalize, is_eligible, load_frozen, sha256_of
from harness.providers import anthropic_client, gemini_client, openai_client
from harness.judge import JUDGE_VERSION, JudgeError, judge_call
from harness.lean_executor import run_backtest
from harness.retrieval import get_retrieval_snippet
from harness.storage import Store


FROZEN_PROMPT_SET_PATH = Path("results/frozen/prompt_set_v1.json")


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
    *,
    prompt_set_sha256: str | None = None,
) -> dict[str, Any]:
    """Run one (prompt × model × condition × trial_index) cell. Always writes
    one `calls` row (even on provider error or excluded cell) and the
    appropriate `turns` rows. Returns a result dict matching the CallResult
    Pydantic schema.

    Excluded cells (e.g. Gemini × S3/A1) short-circuit BEFORE any provider
    call: a row is created with status='excluded', excluded_reason='...' and
    no provider/judge/artifact work runs. They appear in the grid for
    transparency but are dropped from pass-rate denominators.

    trial_index must be pre-allocated by the caller (run_grid) so concurrent
    cells with the same (prompt, model, condition) don't collide on the
    UNIQUE(prompt_id, model_id, condition_id, trial_index) index.

    prompt_set_sha256 is stamped on every row. The caller (run_grid) computes
    it once per batch from the frozen artifact and passes it through.
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

    # ==== Pre-flight: design-time cell exclusion ====
    # Some (model, condition) cells are excluded by design — e.g. Gemini under
    # S3_web/A1_agentic_full lacks the tooling parity we have for Anthropic/
    # OpenAI. Persist a status='excluded' row so the grid stays auditable, but
    # never fire a provider call, never judge, never write an artifact.
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
        return {
            "call_id":             call_id,
            "model":               model_friendly,
            "condition":           condition_id,
            "attempt":             trial_index,
            "status":              "excluded",
            "excluded_reason":     excl_reason,
            "generated_code":      None,
            "response_text":       None,
            "compile_pass":        None,
            "backtest_pass":       None,
            "trade_pass":          None,
            "judge_pass":          None,
            "overall_pass":        None,
            "failure_category_l1": None,
            "failure_category_l2": None,
            "cost_usd":            None,
            "latency_ms":          0,
            "input_tokens":        0,
            "output_tokens":       0,
            "turns_used":          0,
            "error":               None,
            "judge_error":         None,
        }

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
        # Pre-run hardening v1.5: identity stamping happens at row creation
        # so even a row that later errors carries the benchmark context.
        status="started",
        benchmark_version=BENCHMARK_VERSION,
        prompt_set_sha256=prompt_set_sha256,
        judge_threshold=JUDGE_PASS_THRESHOLD,
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
            # An unhandled exception inside run_backtest leaves the calls row
            # with NULL backtest fields and no signal to the UI. Persist a
            # synthetic skipped result so the row reflects what happened.
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

    # ==== STAGE 4: judge ====
    # Score implementation correctness against the prompt's stated intent,
    # using the real backtest result from stage 3. The judge is robust to
    # cases where the backtest was skipped (LEAN CLI absent / timed out).
    #
    # On failure (rate limit, malformed response, network), persist the error
    # text to calls.judge_error so the UI can surface "judge failed" instead of
    # silently leaving judge_pass NULL (which looks identical to "pending").
    judge_outcome: dict[str, Any] = {}
    judge_error: str | None = None
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
            # Clear any prior judge_error on success (so a successful rejudge
            # overwrites a previously failed attempt cleanly).
            store.update_call(call_id, judge_error=None)
        except JudgeError as exc:
            judge_error = f"{type(exc).__name__}: {exc}"
            print(f"[judge] {judge_error}")
        except Exception as exc:  # noqa: BLE001
            judge_error = f"{type(exc).__name__}: {exc}"
            print(f"[judge] unexpected: {judge_error}")
        if judge_error:
            try:
                store.update_call(call_id, judge_error=judge_error)
            except Exception as persist_exc:  # noqa: BLE001
                print(f"[judge] failed to persist error: {persist_exc}")

    # ==== STAGE 5: sidecar artifact ====
    # Write a per-call JSON artifact with everything a reviewer needs to
    # audit this row offline (provider response, retrieval snippet, web
    # citations, prompt hashes, judge/benchmark provenance). Hash and path
    # are persisted on the row so DB <-> file system can be cross-checked.
    #
    # Strict mode: when LEANBENCH_REQUIRE_ARTIFACTS=1 is set (paper / publish
    # runs), an artifact write failure flips the call to status='error' so
    # we never publish a completed row that's missing its audit sidecar.
    # In dev mode (default) the failure is logged and the call still
    # completes — useful so a transient disk issue doesn't waste a generation.
    final_status = "error" if error_text else "completed"
    artifact_path_str: str | None = None
    artifact_hash: str | None = None
    artifact_error: str | None = None
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
            enriched_prompt=enriched_prompt,
            retrieval_snippet=retrieval_snippet,
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
            # Treat missing artifact as a call failure in strict mode.
            final_status = "error"
            if not error_text:
                error_text = f"artifact_write_failed: {artifact_error}"

    # Final status / artifact provenance stamp.
    try:
        store.update_call(
            call_id,
            status=final_status,
            artifact_path=artifact_path_str,
            artifact_sha256=artifact_hash,
            trajectory_path=artifact_path_str,    # legacy column kept in sync
            error=error_text,
        )
    except Exception as persist_exc:  # noqa: BLE001
        print(f"[status] failed to persist final status for {call_id}: {persist_exc}")

    return {
        "call_id": call_id,
        "model": model_friendly,
        "condition": condition_id,
        "attempt": trial_index,
        "status": final_status,
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
        "judge_error": judge_error,
    }


class FrozenPromptSetMismatch(RuntimeError):
    """Raised at run start when the live DB diverges from the frozen artifact."""


def resolve_prompt_set_sha256(store: Store, prompt_id: str) -> str | None:
    """Return the prompt_set_sha256 to stamp on calls for this prompt.

    Rules:
      - Adhoc prompts (source='adhoc') are dev-only and not part of the
        benchmark grid; they get None — no freeze guard, no stamp.
      - For benchmark-eligible prompts, the live DB's canonical hash MUST
        match the on-disk frozen artifact. If the artifact is missing or the
        hashes diverge, abort loudly: a benchmark run with an unfrozen prompt
        set is not reproducible.
    """
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
    attempts: int = 1,
) -> list[dict[str, Any]]:
    """Fan out (model × condition × attempt) cells in parallel via asyncio.gather.

    Pre-allocates trial_index for each task BEFORE launching, so concurrent
    cells with the same (prompt, model, condition) don't collide on the
    unique index when an awaited API call yields the event loop between
    next_trial_index() and record_call().

    Run-start guard: if `prompt_id` belongs to the benchmark grid (not adhoc),
    the live DB's canonical prompt-set hash must match the frozen artifact.
    Mismatches raise FrozenPromptSetMismatch BEFORE any provider call.

    Prompt-text source of truth: for benchmark-eligible (non-adhoc) prompts,
    the DB's `reformulated_text` is what the freeze guard hashes and what the
    judge metadata pulls from — so the model MUST see the same text. The
    `prompt_text` argument is overridden with the DB value in that case.
    Adhoc prompts pass through verbatim (no frozen identity to protect).
    """
    prompt_set_sha256 = resolve_prompt_set_sha256(store, prompt_id)

    # If this is a frozen prompt, ignore caller-supplied text and use the
    # canonical DB text. Otherwise (adhoc, or prompt not found) keep the
    # caller's text. The caller is still the source of truth for adhoc runs.
    prompt_row = store.get_prompt(prompt_id)
    if prompt_row and str(prompt_row.get("source") or "") != "adhoc":
        db_text = prompt_row.get("reformulated_text") or prompt_row.get("original_text") or ""
        if db_text:
            prompt_text = db_text

    tasks = []
    for m in models:
        for c in conditions:
            base = store.next_trial_index(prompt_id, m, c)
            for i in range(attempts):
                tasks.append(run_cell(
                    store, prompt_id, prompt_text, m, c,
                    trial_index=base + i,
                    prompt_set_sha256=prompt_set_sha256,
                ))
    return await asyncio.gather(*tasks)
