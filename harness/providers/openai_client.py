"""OpenAI provider client with v2 tool-use round-trip support.

Uses the Responses API. Tool use is expressed as `function_call` items in
`resp.output`. The follow-up call sends `function_call_output` items in the
`input` list referencing the prior call_id.

For simplicity and robustness across SDK versions we model the assistant
turn as a list of dict items (the same shape we will send back) rather than
the raw SDK object — this lets the orchestrator append+resend with no extra
serialization.
"""

from __future__ import annotations

import json
import time
from typing import Any

from openai import AsyncOpenAI

from harness.providers.base import ProviderResponse, ToolCall, extract_code


_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        # max_retries=6: SDK honors Retry-After on 429/5xx so transient TPM
        # ceilings recover automatically instead of surfacing as call errors.
        _client = AsyncOpenAI(max_retries=6, timeout=600.0)
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

    # Walk resp.output once to collect (a) the assistant turn items we'll
    # round-trip and (b) the structured tool_calls we'll dispatch.
    raw_items: list[dict] = []
    tool_calls: list[ToolCall] = []
    tools_called: list[str] = []
    for item in getattr(resp, "output", None) or []:
        item_type = getattr(item, "type", None)
        if item_type == "message":
            # Assistant text — re-emit as a message dict with normalized text.
            content_parts: list[dict] = []
            for c in (getattr(item, "content", None) or []):
                c_type = getattr(c, "type", None)
                if c_type == "output_text":
                    content_parts.append({"type": "output_text", "text": getattr(c, "text", "")})
            raw_items.append({
                "type": "message",
                "role": "assistant",
                "content": content_parts,
            })
        elif item_type == "function_call":
            name = getattr(item, "name", "")
            args_raw = getattr(item, "arguments", "")
            call_id = getattr(item, "call_id", None) or getattr(item, "id", "")
            try:
                parsed_input = json.loads(args_raw) if args_raw else {}
            except json.JSONDecodeError:
                parsed_input = {"_raw_arguments": args_raw}
            tool_calls.append({"id": call_id, "name": name, "input": parsed_input})
            tools_called.append(name)
            raw_items.append({
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": args_raw,
            })
        else:
            # web_search_call or similar — capture for telemetry, no dispatch.
            if item_type:
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
        tool_calls=tool_calls,
        raw_assistant_turn=raw_items,   # list of items to splice back into `input`
        raw_response=resp.model_dump(),
    )


def build_tool_result_message(tool_call: ToolCall, tool_output: dict) -> dict:
    """Render a single function_call_output item per the Responses API."""
    return {
        "type": "function_call_output",
        "call_id": tool_call["id"],
        "output": tool_output["output"],
    }
