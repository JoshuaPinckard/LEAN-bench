"""Anthropic provider client with v2 tool-use round-trip support.

The Anthropic Messages API expresses tool use as:
  - assistant turn content blocks: [text, tool_use(id, name, input), ...]
  - user follow-up turn:
      {role: "user", content: [{type: "tool_result", tool_use_id: id, content: ...}, ...]}

This client returns a `tool_calls` list the orchestrator dispatches, plus a
`raw_assistant_turn` it appends to the message list before sending the
tool_result follow-up.
"""

from __future__ import annotations

import time
from typing import Any

from anthropic import AsyncAnthropic

from harness.providers.base import ProviderResponse, ToolCall, extract_code


_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        # max_retries=6: SDK respects Retry-After on 429/5xx, so this lets
        # transient rate-limit windows (sonnet-4.6 has a 30k-input-tpm tier
        # ceiling) clear themselves instead of bubbling up as a call error.
        _client = AsyncAnthropic(max_retries=6, timeout=600.0)
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
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if "opus-4-7" not in model_pinned:
        kwargs["temperature"] = temperature
    if system_prompt:
        kwargs["system"] = system_prompt
    if tools:
        kwargs["tools"] = tools

    start = time.monotonic()
    resp = await client.messages.create(**kwargs)
    latency_ms = int((time.monotonic() - start) * 1000)

    # Assistant turn content as the model returned it. We need this verbatim
    # to round-trip into the next turn's message list.
    raw_blocks: list[dict] = []
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    tools_called: list[str] = []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
            raw_blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "name": block.name,
                "input": dict(block.input) if isinstance(block.input, dict) else {},
            })
            tools_called.append(block.name)
            raw_blocks.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })

    response_text = "".join(text_parts)

    usage = resp.usage
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0

    return ProviderResponse(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_tokens=cached,
        latency_ms=latency_ms,
        finish_reason=resp.stop_reason or "unknown",
        response_text=response_text,
        generated_code=extract_code(response_text),
        tools_called=tools_called,
        tool_calls=tool_calls,
        raw_assistant_turn={"role": "assistant", "content": raw_blocks},
        raw_response=resp.model_dump(),
    )


def build_tool_result_message(tool_call: ToolCall, tool_output: dict) -> dict:
    """Render a single tool dispatch outcome as the user message Anthropic
    expects on the next turn. The orchestrator concatenates these into one
    user turn when the model emits multiple parallel tool_use blocks."""
    return {
        "type": "tool_result",
        "tool_use_id": tool_call["id"],
        "content": tool_output["output"],
        "is_error": bool(tool_output.get("is_error", False)),
    }
