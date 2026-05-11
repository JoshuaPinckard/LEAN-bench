"""OpenAI provider client. Honors the ProviderResponse contract from base.py.

Uses chat.completions API. Tool support (web_search_preview) requires the
Responses API and is not wired in this build — conditions/builder.py emits
the tool spec but it is currently dropped here.
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
        _client = AsyncOpenAI()
    return _client


async def call(
    model_pinned: str,
    messages: list[dict],
    system_prompt: str = "",
    tools: list[dict] | None = None,  # not used yet (chat.completions path)
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> ProviderResponse:
    client = _get_client()

    full_messages: list[dict] = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    kwargs: dict[str, Any] = {
        "model": model_pinned,
        "messages": full_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    start = time.monotonic()
    resp = await client.chat.completions.create(**kwargs)
    latency_ms = int((time.monotonic() - start) * 1000)

    choice = resp.choices[0]
    response_text = choice.message.content or ""

    cached = 0
    details = getattr(resp.usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0

    return ProviderResponse(
        input_tokens=resp.usage.prompt_tokens,
        output_tokens=resp.usage.completion_tokens,
        cached_tokens=cached,
        latency_ms=latency_ms,
        finish_reason=choice.finish_reason or "unknown",
        response_text=response_text,
        generated_code=extract_code(response_text),
        tools_called=[],
        raw_response=resp.model_dump(),
    )
