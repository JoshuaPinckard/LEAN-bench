"""LLM judge for LEAN-Bench.

Given (prompt record, generated code, backtest result), asks claude-sonnet-4-6
to score implementation correctness — NOT profitability — and to classify any
failure mode from the locked taxonomy in harness/constants.py.

Returns a dict matching the structure that Store.update_call_with_judge expects:
    {
        "judge_score":           float,    # 0.0–1.0
        "judge_reasoning":       str,      # 50–150 words, auditable
        "failure_mode":          list[str],# empty if score >= 0.9, else from FAILURE_MODES
        "failure_notes":         str|None, # freetext for edge cases
        "matches_prompt_intent": bool,     # independent of score
    }

`judge_version` (default "v1") is stored on the call row. Bump this whenever
the rubric or system prompt materially changes — re-run scripts/rejudge.py to
update prior calls. Locked failure-mode taxonomy means changing the enum in
constants.py also requires a version bump.
"""

from __future__ import annotations

import json
import re
from typing import Any

from anthropic import AsyncAnthropic

from harness.constants import FAILURE_MODES, FAILURE_MODE_DESCRIPTIONS

JUDGE_MODEL = "claude-sonnet-4-6"
JUDGE_TEMPERATURE = 0
JUDGE_MAX_TOKENS = 1024
JUDGE_VERSION = "v1"


class JudgeError(RuntimeError):
    """Raised when the judge returns malformed output that can't be salvaged."""


_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()
    return _client


def _failure_mode_block() -> str:
    return "\n".join(
        f'  - "{name}": {FAILURE_MODE_DESCRIPTIONS[name]}'
        for name in FAILURE_MODES
    )


JUDGE_SYSTEM_PROMPT = f"""You are the evaluation judge for LEAN-Bench, a benchmark measuring how well LLMs generate QuantConnect LEAN algorithmic-trading code.

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

Independence examples:
- A correct golden-cross with a subtle off-by-one in warmup: score 0.5, matches_prompt_intent=true.
- A polished implementation of the WRONG strategy: score 0.3, matches_prompt_intent=false.

## failure_mode (JSON array; empty if score >= 0.9)

Pick zero or more from the locked taxonomy below. First element is treated as the primary failure mode.

{_failure_mode_block()}

If the score is >= 0.9, `failure_mode` MUST be `[]`.
If the score is < 0.9, include at least one entry.
Use "none" only when score == 1.0 AND you need to make the no-failure intent explicit (otherwise prefer an empty array).

## failure_notes (string or null)

Freetext for edge cases the taxonomy doesn't capture, OR null. Keep it short — one sentence.

## judge_reasoning

Concise but specific. Typically 50–150 words. Cite the SPECIFIC element(s) of code that earned the score (correct/incorrect API call, indicator misuse, missing warmup, etc.). Avoid generalities. This goes into the audit trail; reviewers must be able to verify your call without re-reading the code.

## Output format

Return ONLY a single JSON object. No prose before, no prose after, no markdown fences. Schema:

{{
  "judge_score": <float, 0.0 to 1.0>,
  "judge_reasoning": "<string, 50-150 words>",
  "failure_mode": [<zero or more locked-taxonomy strings>],
  "failure_notes": <string or null>,
  "matches_prompt_intent": <true or false>
}}"""


# Locked schema for parsed judge output
_REQUIRED = {"judge_score", "judge_reasoning", "failure_mode", "matches_prompt_intent"}


def _build_user_message(
    prompt_record: dict,
    generated_code: str,
    backtest_result: dict,
) -> str:
    """Render the per-call context into a single user message."""
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
    parts.append("# Backtest result")
    parts.append(json.dumps(backtest_result, indent=2, default=str))
    return "\n".join(parts)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first balanced JSON object from `text`, tolerant of fences/prose."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`")
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise JudgeError(f"No JSON object found in judge response: {text[:200]!r}")
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeError(f"Malformed JSON from judge: {exc}; got {cleaned[start:end+1][:200]!r}") from exc


def _coerce_failure_mode(value: Any) -> list[str]:
    """Accept list/str/None and return a list of allowed enum strings only."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    allowed = set(FAILURE_MODES)
    return [v for v in value if isinstance(v, str) and v in allowed]


async def judge_call(
    prompt_record: dict,
    generated_code: str,
    backtest_result: dict,
    judge_version: str = JUDGE_VERSION,
) -> dict:
    """Score one (prompt, code, backtest) tuple. Returns a dict ready to pass
    straight to Store.update_call_with_judge (minus `call_id`).

    On parse failure the response is salvaged where possible:
    - missing failure_mode -> []
    - missing failure_notes -> None
    - missing matches_prompt_intent -> derived from judge_score >= 0.7

    If judge_score or judge_reasoning are missing, raises JudgeError.
    """
    user = _build_user_message(prompt_record, generated_code, backtest_result)
    client = _get_client()
    resp = await client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=JUDGE_MAX_TOKENS,
        temperature=JUDGE_TEMPERATURE,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    parsed = _extract_json(raw)

    # Required fields
    if "judge_score" not in parsed or "judge_reasoning" not in parsed:
        raise JudgeError(f"Judge response missing required field: {sorted(_REQUIRED - parsed.keys())}")
    try:
        score = float(parsed["judge_score"])
    except (TypeError, ValueError) as exc:
        raise JudgeError(f"judge_score not a float: {parsed.get('judge_score')!r}") from exc
    score = max(0.0, min(1.0, score))

    failure_mode = _coerce_failure_mode(parsed.get("failure_mode"))
    matches_intent = parsed.get("matches_prompt_intent")
    if not isinstance(matches_intent, bool):
        matches_intent = score >= 0.7

    return {
        "judge_score":           score,
        "judge_reasoning":       str(parsed["judge_reasoning"]),
        "failure_mode":          failure_mode,
        "failure_notes":         parsed.get("failure_notes") if isinstance(parsed.get("failure_notes"), str) else None,
        "matches_prompt_intent": matches_intent,
        "judge_version":         judge_version,
    }
