"""AI-assisted schema autofill for the Prompt curation form.

Given a prompt_text, asks Sonnet (claude-sonnet-4-6, temperature=0) to produce
a JSON object pre-filling every field the curator would otherwise enter by
hand. The curator can then accept, edit, or override any value.

The returned dict matches SchemaAutofillResponse — that's the snapshot the
frontend uses to compute `curator_modified_fields` (which AI suggestions the
curator subsequently changed) for the methodology section of the paper.

`fill_schema` raises:
  - `SchemaAutofillError` if Sonnet's response cannot be parsed as JSON or
    if a required field is missing. The HTTP layer maps this to a 500.
"""

from __future__ import annotations

import json
import re
from typing import Any

from anthropic import AsyncAnthropic


AUTOFILL_MODEL = "claude-sonnet-4-6"
MAX_AUTOFILL_TOKENS = 2048


class SchemaAutofillError(RuntimeError):
    """Sonnet returned malformed output or missing required fields."""


_SYSTEM_PROMPT = """You are a benchmark curator's assistant. The user will give you a natural-language description of a QuantConnect LEAN algorithmic-trading strategy. Your job is to populate every schema field below as JSON, deciding the most defensible value for each.

Return ONLY a valid JSON object — no prose before or after, no markdown fences, no commentary. If a field cannot be inferred from the prompt, choose the most likely default. Do not omit any field.

Field definitions (use exactly these keys and these allowed values):

- strategy_type: one of "directional" | "mean_reversion" | "derivatives" | "portfolio" | "execution" | "relative_value" | "other"
  directional = trend/momentum; mean_reversion = revert to mean; derivatives = options/volatility; portfolio = construction/risk parity; execution = market making; relative_value = arbitrage/pairs.
- strategy_complexity: integer 1, 2, or 3. (1=single asset + single rule; 2=multi-indicator or 2-3 assets; 3=portfolio-level / options / dynamic universe.)
- api_complexity: integer 1, 2, or 3. (1=built-in indicators only; 2=indicator pipelines + warmup/scheduling; 3=custom universe selection / option chain / alpha framework.)
- securities_type: one of "equity" | "option" | "multi_asset".
- securities_type_detailed: one of "equity" | "forex" | "crypto" | "future" | "option" | "cfd" | "mixed", or null. Use null if not clearly stated. (Set "crypto" for BTC/ETH, "forex" for currency pairs, etc.)
- resolution: one of "high_frequency" | "intraday" | "daily". (high_frequency = tick/second; intraday = minute/hour; daily = end-of-day.)
- implementation_type: one of "lean_native" | "custom_implementation" | "external_data_required" | "mixed".
  lean_native = built-in LEAN APIs only; custom_implementation = needs custom math/indicators; external_data_required = needs alt data; mixed = combination.
- indicators: JSON array of strings naming technical indicators referenced (e.g. ["SMA", "RSI"]). Empty array if none.
- universe_type: one of "single_asset" | "multi_asset_specific" | "index_components" | "screened_universe" | "custom_universe_logic".
- universe_index: one of "SP500" | "NASDAQ100" | "RUSSELL2000" | "DOW30" | "SP400_MIDCAP" | "RUSSELL1000" | "other", or null. Only set when universe_type is "index_components".
- tickers: JSON array of strings, uppercased (e.g. ["SPY", "QQQ"]). Required when universe_type is "single_asset" or "multi_asset_specific"; otherwise empty array.
- start_date: string "YYYY-MM-DD". Default "2020-01-01" unless the prompt specifies otherwise.
- end_date: string "YYYY-MM-DD". Default "2024-12-31" unless the prompt specifies otherwise.
- evaluation_mode: one of "trade_required" | "signal_required" | "code_only" | "metric_threshold_required". Default "trade_required" unless the prompt is about pure signal generation or pure code structure.
- interpretation_strictness: one of "unambiguous" | "mild_variation" | "broad_interpretation".
  unambiguous = a single correct interpretation; mild_variation = minor implementation gaps; broad_interpretation = multiple meaningfully different valid implementations.
- curator_notes: a substantive string (MINIMUM 80 characters) describing what the prompt tests, the LEAN-specific failure modes a model might hit, and any ambiguities. Be specific and useful — this is for benchmark curators reviewing the prompt later.

Output: a single JSON object containing all fields above, nothing else."""


# Required keys checked after parsing
_REQUIRED_KEYS = {
    "strategy_type", "strategy_complexity", "api_complexity",
    "securities_type", "resolution", "implementation_type",
    "indicators", "universe_type", "tickers",
    "start_date", "end_date", "evaluation_mode",
    "interpretation_strictness", "curator_notes",
}

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()
    return _client


def _extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first balanced JSON object from `text`. Tolerates stray prose
    or markdown fences (we strip ``` first, then take the {..} span)."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`")
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise SchemaAutofillError(f"No JSON object found in autofill response: {text[:200]}")
    blob = cleaned[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        raise SchemaAutofillError(f"Malformed JSON from autofill: {exc}; first 200 chars: {blob[:200]}") from exc


async def fill_schema(prompt_text: str) -> dict[str, Any]:
    """Call Sonnet to populate every schema field for a curator's prompt.

    Returns a dict matching SchemaAutofillResponse. Raises SchemaAutofillError
    on parse failure or missing required fields.
    """
    client = _get_client()
    resp = await client.messages.create(
        model=AUTOFILL_MODEL,
        max_tokens=MAX_AUTOFILL_TOKENS,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt_text}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    parsed = _extract_json_object(raw)

    missing = _REQUIRED_KEYS - parsed.keys()
    if missing:
        raise SchemaAutofillError(f"Autofill response missing required fields: {sorted(missing)}")

    # Defaults for optional fields
    parsed.setdefault("securities_type_detailed", None)
    parsed.setdefault("universe_index", None)
    return parsed
