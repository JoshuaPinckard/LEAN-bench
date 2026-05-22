"""Dual-judge LLM scoring for LEAN-Bench v2.0 (proposal §Judge Validation).

Two INDEPENDENT judges score every (prompt, code, backtest) tuple in parallel
with the same locked rubric. The call's `judge_score` is the AVERAGE of the
two judge scores. The pass cutoff (JUDGE_PASS_THRESHOLD = 0.7) is applied to
the average.

Judge models (locked):
    Judge A — claude-sonnet-4-6   (Anthropic)
    Judge B — gpt-5.4-2026-03-05  (OpenAI)

Different families avoid same-vendor judge bias. The proposal also requires
a subset of prompts to be expert-reviewed (HITL) and the judge-vs-human
agreement to be published; scripts/validate_judge.py covers the calculation
side once HITL labels exist.

Bump `JUDGE_VERSION` whenever the rubric, system prompt, or judge model
identity changes. Bump triggers a full rejudge of affected calls.

Returned dict — what update_call_with_judge expects:
    {
        "judge_score":             float,    # AVERAGE of the two judges
        "judge_reasoning":         str,      # concat'd A | B for the audit trail
        "judge_version":           str,
        "failure_mode":            list[str],# unioned across the two judges
        "failure_notes":           str|None,
        "matches_prompt_intent":   bool,     # AND of the two judges
        # Per-judge breakdown:
        "judge_score_a":           float,
        "judge_score_b":           float,
        "judge_reasoning_a":       str,
        "judge_reasoning_b":       str,
        "judge_version_a":         str,
        "judge_version_b":         str,
        "judge_model_a":           str,
        "judge_model_b":           str,
        "judge_error_a":           str|None,
        "judge_error_b":           str|None,
    }
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from harness.constants import FAILURE_MODES, FAILURE_MODE_DESCRIPTIONS

JUDGE_VERSION = "v3"  # v3 = dual-judge averaged (was v2 single-judge sonnet).

JUDGE_MODEL_A = "claude-sonnet-4-6"
JUDGE_MODEL_B = "gpt-5.4-2026-03-05"

JUDGE_TEMPERATURE = 0
JUDGE_MAX_TOKENS = 1024

# Per-provider concurrency caps. The two judges talk to different APIs so
# their semaphores are independent — saturating Anthropic's TPM does not
# block OpenAI, and vice versa.
_JUDGE_CONCURRENCY_ANTHROPIC = 3
_JUDGE_CONCURRENCY_OPENAI = 3
_JUDGE_SEM_A: asyncio.Semaphore | None = None
_JUDGE_SEM_B: asyncio.Semaphore | None = None


class JudgeError(RuntimeError):
    """Raised when a judge returns malformed output that can't be salvaged."""


_anthropic_client: AsyncAnthropic | None = None
_openai_client: AsyncOpenAI | None = None


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(max_retries=4)
    return _anthropic_client


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(max_retries=4)
    return _openai_client


def _sem_a() -> asyncio.Semaphore:
    global _JUDGE_SEM_A
    if _JUDGE_SEM_A is None:
        _JUDGE_SEM_A = asyncio.Semaphore(_JUDGE_CONCURRENCY_ANTHROPIC)
    return _JUDGE_SEM_A


def _sem_b() -> asyncio.Semaphore:
    global _JUDGE_SEM_B
    if _JUDGE_SEM_B is None:
        _JUDGE_SEM_B = asyncio.Semaphore(_JUDGE_CONCURRENCY_OPENAI)
    return _JUDGE_SEM_B


def _failure_mode_block() -> str:
    return "\n".join(
        f'  - "{name}": {FAILURE_MODE_DESCRIPTIONS[name]}'
        for name in FAILURE_MODES
    )


JUDGE_SYSTEM_PROMPT = f"""You are an evaluation judge for LEAN-Bench, a benchmark measuring how well LLMs generate QuantConnect LEAN algorithmic-trading code.

Your job is to score IMPLEMENTATION CORRECTNESS — whether the generated code does what the prompt asked. You are NOT scoring profitability. A perfectly-implemented losing strategy scores 1.0. A profitable strategy that trades the wrong asset scores low. Profitability metrics (Sharpe, return) may inform your reasoning but never drive your numeric score.

## Scoring rubric (judge_score, 0.0 to 1.0)

| Score | Meaning |
|-------|---------|
| 1.0  | Perfect implementation. Code matches the prompt exactly, runs without error, produces the expected behavior. |
| 0.7  | Mostly correct. Minor gaps or reasonable interpretations of ambiguous requirements. Core logic intact. |
| 0.5  | Partial implementation. Core intent recognizable but key elements missing or incorrect. May run but doesn't fully match prompt. |
| 0.3  | Wrong approach. Significant deviation from prompt intent. Implements a related but incorrect strategy. |
| 0.0  | Complete failure. Doesn't compile, hallucinated APIs, wrong asset class entirely, or empty output. |

Interpolate between these anchors. Be calibrated.

## Critical: losing-but-correct strategies score 1.0

Examples that score 1.0 regardless of poor returns:
- Prompt: "SMA(50)/SMA(200) crossover on SPY." Code: correct golden-cross implementation on SPY. Backtest: -15% total return. SCORE: 1.0. The prompt did not request profitability.
- Prompt: "Long QQQ when RSI(14) < 30." Code: correctly buys QQQ on the stated trigger. Backtest: Sharpe -0.4. SCORE: 1.0.
- Prompt: "Pairs-trade MSFT/GOOGL on 20-day z-score." Code: correct spread + z-score + simultaneous long/short. Backtest: max drawdown -25%. SCORE: 1.0 (or 0.9 if one minor convention is off).

The benchmark measures code generation, not strategy quality. Drift toward equating bad returns with bad implementation is a known failure mode — actively guard against it.

## matches_prompt_intent (boolean, independent of score)

True when the code's STRUCTURE faithfully realises what the prompt asked, even if execution details fall short. False when the model misread the prompt at a conceptual level (wrong asset class, wrong direction, wrong strategy family).

## failure_mode (JSON array; empty if score >= 0.9)

Pick zero or more from the locked taxonomy below. First element is treated as the primary failure mode.

{_failure_mode_block()}

If the score is >= 0.9, `failure_mode` MUST be `[]`.
If the score is < 0.9, include at least one entry.

## failure_notes (string or null)

Freetext for edge cases the taxonomy doesn't capture, OR null. Keep it short — one sentence.

## judge_reasoning

Concise but specific. Typically 50-150 words. Cite the SPECIFIC element(s) of code that earned the score (correct/incorrect API call, indicator misuse, missing warmup, etc.). Avoid generalities. This goes into the audit trail; reviewers must be able to verify your call without re-reading the code.

## Output format

Return ONLY a single JSON object. No prose before, no prose after, no markdown fences. Schema:

{{
  "judge_score": <float, 0.0 to 1.0>,
  "judge_reasoning": "<string, 50-150 words>",
  "failure_mode": [<zero or more locked-taxonomy strings>],
  "failure_notes": <string or null>,
  "matches_prompt_intent": <true or false>
}}"""


_REQUIRED = {"judge_score", "judge_reasoning", "failure_mode", "matches_prompt_intent"}


def _build_user_message(
    prompt_record: dict,
    generated_code: str,
    backtest_result: dict,
) -> str:
    p = prompt_record
    parts: list[str] = []
    parts.append("# Original prompt")
    parts.append(p.get("reformulated_text") or p.get("original_text") or "")
    parts.append("")
    parts.append("# Prompt metadata")
    meta = {
        "strategy_type":               p.get("strategy_type"),
        "evaluation_mode":             p.get("evaluation_mode"),
        "interpretation_strictness":   p.get("interpretation_strictness"),
        "securities_type":             p.get("securities_type"),
        "resolution":                  p.get("resolution"),
        "universe_type":               p.get("universe_type"),
        "tickers":                     p.get("tickers"),
        "indicators":                  p.get("indicators"),
        "implementation_type":         p.get("implementation_type"),
        "start_date":                  p.get("start_date"),
        "end_date":                    p.get("end_date"),
    }
    parts.append(json.dumps(meta, indent=2))
    parts.append("")
    parts.append("# Curator notes")
    parts.append(p.get("leak_audit_notes") or p.get("curator_notes") or "(none)")
    parts.append("")
    parts.append("# Generated code")
    parts.append("```python")
    parts.append(generated_code or "(empty)")
    parts.append("```")
    parts.append("")
    parts.append("# Execution summary")
    compact = {
        "compile_success":          backtest_result.get("compile_success"),
        "runtime_success":          backtest_result.get("runtime_success"),
        "runtime_error":            (backtest_result.get("runtime_error") or "")[:300] or None,
        "total_return_pct":         backtest_result.get("total_return_pct"),
        "sharpe_ratio":             backtest_result.get("sharpe_ratio"),
        "max_drawdown_pct":         backtest_result.get("max_drawdown_pct"),
        "num_trades":               backtest_result.get("num_trades"),
        "win_rate":                 backtest_result.get("win_rate"),
        "starting_portfolio_value": backtest_result.get("starting_portfolio_value"),
        "final_portfolio_value":    backtest_result.get("final_portfolio_value"),
        "benchmark_return_pct":     backtest_result.get("benchmark_return_pct"),
    }
    parts.append(json.dumps(compact, indent=2))
    return "\n".join(parts)


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`")
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise JudgeError(f"No JSON object found in judge response: {text[:200]!r}")
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeError(f"Malformed JSON from judge: {exc}; got {cleaned[start:end+1][:200]!r}") from exc


def _coerce_failure_mode(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    allowed = set(FAILURE_MODES)
    return [v for v in value if isinstance(v, str) and v in allowed]


def _parse_judge_payload(raw: str) -> dict:
    parsed = _extract_json(raw)
    if "judge_score" not in parsed or "judge_reasoning" not in parsed:
        raise JudgeError(
            f"Judge missing required field: {sorted(_REQUIRED - parsed.keys())}"
        )
    try:
        score = float(parsed["judge_score"])
    except (TypeError, ValueError) as exc:
        raise JudgeError(f"judge_score not a float: {parsed.get('judge_score')!r}") from exc
    score = max(0.0, min(1.0, score))

    failure_mode = _coerce_failure_mode(parsed.get("failure_mode"))
    matches = parsed.get("matches_prompt_intent")
    if not isinstance(matches, bool):
        matches = score >= 0.7

    return {
        "judge_score":           score,
        "judge_reasoning":       str(parsed["judge_reasoning"]),
        "failure_mode":          failure_mode,
        "failure_notes":         parsed.get("failure_notes") if isinstance(parsed.get("failure_notes"), str) else None,
        "matches_prompt_intent": matches,
    }


async def _judge_anthropic(user_message: str) -> dict:
    client = _get_anthropic()
    async with _sem_a():
        resp = await client.messages.create(
            model=JUDGE_MODEL_A,
            max_tokens=JUDGE_MAX_TOKENS,
            temperature=JUDGE_TEMPERATURE,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    return _parse_judge_payload(raw)


async def _judge_openai(user_message: str) -> dict:
    client = _get_openai()
    async with _sem_b():
        resp = await client.responses.create(
            model=JUDGE_MODEL_B,
            max_output_tokens=JUDGE_MAX_TOKENS,
            instructions=JUDGE_SYSTEM_PROMPT,
            input=[{"role": "user", "content": user_message}],
        )
    raw = (resp.output_text or "").strip()
    return _parse_judge_payload(raw)


async def judge_call(
    prompt_record: dict,
    generated_code: str,
    backtest_result: dict,
    judge_version: str = JUDGE_VERSION,
) -> dict:
    """Run both judges in parallel and combine. Returns a dict ready to pass
    straight to Store.update_call_with_judge (minus `call_id`).

    Combination rules:
      - judge_score    = mean(a.score, b.score)  (if both succeeded)
      - judge_pass     = derived later, using the locked threshold (0.7)
      - failure_mode   = union of the two lists (a wins on order)
      - matches_prompt_intent = a.intent AND b.intent (consensus)
      - judge_reasoning = "[A] ... \\n\\n[B] ..." for the audit trail

    If exactly one judge fails, the other carries the call and the failed
    judge's score is `None`. If both fail, raises JudgeError.
    """
    user = _build_user_message(prompt_record, generated_code, backtest_result)

    a_task = asyncio.create_task(_judge_anthropic(user))
    b_task = asyncio.create_task(_judge_openai(user))
    a_res: dict | BaseException
    b_res: dict | BaseException
    a_res, b_res = await asyncio.gather(a_task, b_task, return_exceptions=True)

    a_ok = isinstance(a_res, dict)
    b_ok = isinstance(b_res, dict)

    if not a_ok and not b_ok:
        raise JudgeError(
            f"Both judges failed. A={type(a_res).__name__}: {a_res}; "
            f"B={type(b_res).__name__}: {b_res}"
        )

    # Score combination — both, or whichever survived.
    score_a = a_res["judge_score"] if a_ok else None
    score_b = b_res["judge_score"] if b_ok else None
    survivors = [s for s in (score_a, score_b) if s is not None]
    avg_score = sum(survivors) / len(survivors)

    # Reasoning audit trail: tag each side so reviewers can attribute.
    reasoning_parts: list[str] = []
    if a_ok:
        reasoning_parts.append(f"[A:{JUDGE_MODEL_A}] {a_res['judge_reasoning']}")
    else:
        reasoning_parts.append(f"[A:{JUDGE_MODEL_A}] ERROR: {type(a_res).__name__}: {a_res}")
    if b_ok:
        reasoning_parts.append(f"[B:{JUDGE_MODEL_B}] {b_res['judge_reasoning']}")
    else:
        reasoning_parts.append(f"[B:{JUDGE_MODEL_B}] ERROR: {type(b_res).__name__}: {b_res}")

    # Failure modes: union, preserving first-seen order from A.
    fm_union: list[str] = []
    seen: set[str] = set()
    for src in (a_res if a_ok else None, b_res if b_ok else None):
        if src is None:
            continue
        for fm in src["failure_mode"]:
            if fm not in seen:
                seen.add(fm)
                fm_union.append(fm)

    # matches_prompt_intent: consensus when both ran; surviving judge's value
    # when only one ran.
    if a_ok and b_ok:
        intent = bool(a_res["matches_prompt_intent"]) and bool(b_res["matches_prompt_intent"])
    elif a_ok:
        intent = bool(a_res["matches_prompt_intent"])
    else:
        intent = bool(b_res["matches_prompt_intent"])  # type: ignore[index]

    # Combined failure_notes: first non-empty.
    failure_notes: str | None = None
    if a_ok and a_res.get("failure_notes"):
        failure_notes = a_res["failure_notes"]
    elif b_ok and b_res.get("failure_notes"):
        failure_notes = b_res["failure_notes"]

    return {
        "judge_score":           avg_score,
        "judge_reasoning":       "\n\n".join(reasoning_parts),
        "failure_mode":          fm_union,
        "failure_notes":         failure_notes,
        "matches_prompt_intent": intent,
        "judge_version":         judge_version,
        # Per-judge breakdown for storage and downstream audit.
        "judge_score_a":         score_a,
        "judge_score_b":         score_b,
        "judge_reasoning_a":     a_res["judge_reasoning"] if a_ok else None,
        "judge_reasoning_b":     b_res["judge_reasoning"] if b_ok else None,
        "judge_version_a":       judge_version,
        "judge_version_b":       judge_version,
        "judge_model_a":         JUDGE_MODEL_A,
        "judge_model_b":         JUDGE_MODEL_B,
        "judge_error_a":         None if a_ok else f"{type(a_res).__name__}: {a_res}",
        "judge_error_b":         None if b_ok else f"{type(b_res).__name__}: {b_res}",
    }
