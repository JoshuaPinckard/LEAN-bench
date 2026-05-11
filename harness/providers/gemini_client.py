"""Google Gemini provider client. Honors the ProviderResponse contract.

Uses google-genai SDK. Tool support (google_search) is recognized in
conditions/builder.py but not yet plumbed through the API call here.
"""

from __future__ import annotations

import time
from typing import Any

from google import genai
from google.genai import types as genai_types

from harness.providers.base import ProviderResponse, extract_code


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()  # picks up GEMINI_API_KEY / GOOGLE_API_KEY
    return _client


def _messages_to_contents(messages: list[dict]) -> list[genai_types.Content]:
    """Translate OpenAI-style messages into Gemini Content objects.

    Gemini uses 'user' and 'model' roles; we map 'assistant' -> 'model'.
    """
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append(genai_types.Content(
            role=role,
            parts=[genai_types.Part(text=m["content"])],
        ))
    return contents


async def call(
    model_pinned: str,
    messages: list[dict],
    system_prompt: str = "",
    tools: list[dict] | None = None,  # not yet plumbed
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> ProviderResponse:
    client = _get_client()

    config = genai_types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
    if system_prompt:
        config.system_instruction = system_prompt

    contents = _messages_to_contents(messages)

    start = time.monotonic()
    resp = await client.aio.models.generate_content(
        model=model_pinned,
        contents=contents,
        config=config,
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    response_text = resp.text or ""

    usage = resp.usage_metadata
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    cached = getattr(usage, "cached_content_token_count", 0) or 0

    finish_reason = "unknown"
    if resp.candidates:
        fr = resp.candidates[0].finish_reason
        finish_reason = fr.name if fr is not None else "unknown"

    # Convert response to dict for storage; fall back to repr if model_dump not available
    try:
        raw = resp.model_dump()
    except Exception:
        raw = {"repr": repr(resp)}

    return ProviderResponse(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached,
        latency_ms=latency_ms,
        finish_reason=finish_reason,
        response_text=response_text,
        generated_code=extract_code(response_text),
        tools_called=[],
        raw_response=raw,
    )
