"""Abstract provider contract. Every concrete client (anthropic_client,
openai_client, gemini_client) returns a dict matching ProviderResponse so the
rest of the harness is provider-agnostic.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict


class ProviderResponse(TypedDict, total=True):
    input_tokens: int
    output_tokens: int
    cached_tokens: int          # subset of input_tokens served from prompt cache
    latency_ms: int
    finish_reason: str          # provider-specific string, normalize for analysis later
    response_text: str          # concatenated assistant text
    generated_code: str | None  # extracted python code block, None if absent
    tools_called: list[str]     # ordered list of tool names invoked this call
    raw_response: dict[str, Any]  # full provider response for the trajectory_path JSON


# Matches ```python ... ``` and bare ``` ... ``` fences. Greedy on the inner
# group with the final ``` as anchor; first match wins (most LEAN strategies
# come back as a single block).
_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_code(text: str) -> str | None:
    """Pull the first fenced Python block out of model output.

    Returns the inner code (no fences) stripped of leading/trailing whitespace,
    or None if the response contains no fenced block.
    """
    m = _CODE_FENCE.search(text)
    return m.group(1).strip() if m else None
