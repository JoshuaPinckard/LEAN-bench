"""Anthropic provider client. Honors the ProviderResponse contract from base.py.

Reads ANTHROPIC_API_KEY from the environment (auto-detected by the SDK).
The smoke test bridges VITE_ANTHROPIC_API_KEY -> ANTHROPIC_API_KEY for
convenience with the Vite-style .env that the dev UI uses.
"""

from __future__ import annotations

import time
from typing import Any

from anthropic import AsyncAnthropic

from harness.providers.base import ProviderResponse, extract_code


_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()  # picks up ANTHROPIC_API_KEY from env
    return _client


async def call(
    model_pinned: str,
    messages: list[dict],
    system_prompt: str = "",
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> ProviderResponse:
    """Single Anthropic API call. The orchestrator owns the message list,
    appending {role:'assistant', ...} + {role:'user', ...feedback} between
    turns of the A1 agentic loop.
    """
    client = _get_client()

    kwargs: dict[str, Any] = {
        "model": model_pinned,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    if tools:
        kwargs["tools"] = tools

    start = time.monotonic()
    resp = await client.messages.create(**kwargs)
    latency_ms = int((time.monotonic() - start) * 1000)

    # Anthropic returns content as a list of blocks (text | tool_use | ...).
    response_text = "".join(
        getattr(block, "text", "") for block in resp.content if block.type == "text"
    )
    tools_called = [
        block.name for block in resp.content if block.type == "tool_use"
    ]

    usage = resp.usage
    cached = (
        getattr(usage, "cache_read_input_tokens", 0) or 0
    )

    return ProviderResponse(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_tokens=cached,
        latency_ms=latency_ms,
        finish_reason=resp.stop_reason or "unknown",
        response_text=response_text,
        generated_code=extract_code(response_text),
        tools_called=tools_called,
        raw_response=resp.model_dump(),
    )
