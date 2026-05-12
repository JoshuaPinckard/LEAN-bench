"""OpenAI provider client. Honors the ProviderResponse contract from base.py.

Uses the Responses API (client.responses.create) — the chat.completions path
does not serve GPT-5.x and does not support the web_search_preview tool. The
function signature stays parallel to anthropic_client.call so the orchestrator
treats all providers identically; system prompt goes to `instructions`, the
message list to `input`, and the web search tool spec emitted by
conditions/builder.py flows through under `tools`.
"""

from __future__ import annotations

import time
from typing import Any

from openai import AsyncOpenAI

from harness.providers.base import ProviderResponse, extract_code


_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()  # picks up OPENAI_API_KEY from env
    return _client


async def call(
    model_pinned: str,
    messages: list[dict],
    system_prompt: str = "",
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> ProviderResponse:
    client = _get_client()

    kwargs: dict[str, Any] = {
        "model": model_pinned,
        "input": messages,
        "max_output_tokens": max_tokens,
    }
    # GPT-5.x reasoning models reject temperature/top_p (the internal reasoning
    # pass overrides sampling). Older models still accept it.
    if not model_pinned.startswith("gpt-5"):
        kwargs["temperature"] = temperature
    if system_prompt:
        kwargs["instructions"] = system_prompt
    if tools:
        kwargs["tools"] = tools

    start = time.monotonic()
    resp = await client.responses.create(**kwargs)
    latency_ms = int((time.monotonic() - start) * 1000)

    response_text = resp.output_text or ""

    # Responses API surfaces tool invocations as items in resp.output whose
    # type is something other than "message" (e.g. "web_search_call").
    tools_called: list[str] = []
    for item in getattr(resp, "output", None) or []:
        item_type = getattr(item, "type", None)
        if item_type and item_type != "message":
            tools_called.append(item_type)

    cached = 0
    details = getattr(resp.usage, "input_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0

    return ProviderResponse(
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        cached_tokens=cached,
        latency_ms=latency_ms,
        finish_reason=getattr(resp, "status", None) or "unknown",
        response_text=response_text,
        generated_code=extract_code(response_text),
        tools_called=tools_called,
        raw_response=resp.model_dump(),
    )
