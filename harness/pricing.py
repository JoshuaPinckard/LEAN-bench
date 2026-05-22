"""Cost computation for LEAN-Bench calls.

PRICING is intentionally seeded with None values. cost_usd() will refuse to
compute and raise a clear error until rates are explicitly set, so we never
silently mis-report budget. Verify against each provider's pricing page on
the FROZEN_DATE and update before running any batch.

Rates are USD per 1,000,000 tokens.
"""

from __future__ import annotations

# model_pinned -> rates per 1M tokens.
#   input:      fresh prompt tokens
#   output:     generated tokens
#   cache_read: cached prompt tokens (Anthropic prompt caching, Gemini cached
#               content). Set to None to fall back to input rate.
PRICING: dict[str, dict[str, float | None]] = {
    # Anthropic — verified May 2026
    "claude-opus-4-7":        {"input": 5.00,  "output": 25.00, "cache_read": None},
    "claude-opus-4-6":        {"input": 5.00,  "output": 25.00, "cache_read": None},
    "claude-sonnet-4-6":      {"input": 3.00,  "output": 15.00, "cache_read": None},
    # Anthropic — UNVERIFIED placeholder rates, confirm against pricing page.
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_read": None},
    # OpenAI — verified May 2026
    "gpt-5.5-2026-04-23":     {"input": 5.00,  "output": 30.00, "cache_read": None},
    "gpt-5.4-2026-03-05":     {"input": 2.50,  "output": 15.00, "cache_read": None},
    # OpenAI — UNVERIFIED placeholder rates, confirm against pricing page.
    "gpt-5.4-mini-2026-03-17": {"input": 0.25, "output": 2.00, "cache_read": None},
    "gpt-5.4-nano-2026-03-17": {"input": 0.05, "output": 0.40, "cache_read": None},
    "gpt-4.1-mini":            {"input": 0.40, "output": 1.60, "cache_read": None},
    # Google — verified May 2026
    "gemini-3.1-pro-preview": {"input": 2.00,  "output": 12.00, "cache_read": None},
}


class PricingNotSetError(RuntimeError):
    """Raised when cost_usd() is called for a model whose rates are still None."""


def cost_usd(
    model_pinned: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """Compute call cost in USD.

    cached_tokens is the subset of input_tokens served from cache (Anthropic
    cache_read_input_tokens, Gemini cachedContentTokenCount).
    """
    rates = PRICING.get(model_pinned)
    if rates is None:
        raise KeyError(
            f"No pricing entry for model_pinned={model_pinned!r}. "
            f"Add an entry to harness/pricing.py PRICING dict."
        )
    if rates["input"] is None or rates["output"] is None:
        raise PricingNotSetError(
            f"Pricing for {model_pinned!r} is not set. Verify input/output rates "
            f"against the provider's pricing page (as of FROZEN_DATE) and update "
            f"harness/pricing.py PRICING before running batches."
        )

    fresh_input = max(0, input_tokens - cached_tokens)
    cost = (
        fresh_input * rates["input"] + output_tokens * rates["output"]
    ) / 1_000_000

    if cached_tokens:
        cache_rate = rates.get("cache_read")
        if cache_rate is None:
            # Conservative: bill cached tokens at full input rate when no
            # discount rate is specified.
            cost += (cached_tokens * rates["input"]) / 1_000_000
        else:
            cost += (cached_tokens * cache_rate) / 1_000_000

    return cost


def is_priced(model_pinned: str) -> bool:
    """True if PRICING has non-None input/output rates for this model."""
    rates = PRICING.get(model_pinned)
    return bool(rates and rates["input"] is not None and rates["output"] is not None)


def unpriced_models() -> list[str]:
    """List of model_pinned strings still missing rates. Useful for pre-flight checks."""
    return [m for m in PRICING if not is_priced(m)]
