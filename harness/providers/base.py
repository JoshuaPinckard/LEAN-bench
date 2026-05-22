"""Provider-agnostic contract for the v2 agent loop.

Every provider client returns a ProviderResponse describing one model
invocation. The v2 ProviderResponse extends v1 with structured tool-call
information so the orchestrator can:
  - decide whether the model emitted code, tool calls, or both,
  - dispatch the tool calls via harness.agent_tools.dispatch(),
  - feed tool results back in the next turn via the provider-specific
    tool_result message shape.

`tool_calls` is an ordered list of ToolCall dicts. Each carries the
provider's native id (Anthropic tool_use.id, OpenAI call_id, Gemini index)
and the parsed JSON input. The orchestrator round-trips this id back through
the message list when sending tool_result.

`raw_assistant_turn` is the provider-native object that needs to be appended
back to the conversation as the assistant turn (e.g., the list of content
blocks for Anthropic, or the assistant message dict for OpenAI). This is
provider-shaped on purpose: each provider re-consumes its own format for the
tool round-trip and breaking that round-trip is the easiest way to corrupt
the conversation.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict


class ToolCall(TypedDict, total=True):
    id: str                  # provider-native id (round-tripped on tool_result)
    name: str                # tool name (matches agent_tools)
    input: dict[str, Any]    # parsed JSON arguments


class ProviderResponse(TypedDict, total=True):
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    latency_ms: int
    finish_reason: str
    response_text: str            # concatenated assistant text (may be empty if model only called tools)
    generated_code: str | None    # extracted python code block, None if absent
    tools_called: list[str]       # ordered list of tool names invoked this call (for telemetry)
    tool_calls: list[ToolCall]    # structured tool calls the orchestrator will dispatch
    raw_assistant_turn: Any       # provider-native shape used to round-trip into the next turn's messages
    raw_response: dict[str, Any]  # full provider response, for the artifact JSON


_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_code(text: str) -> str | None:
    """Pull the first fenced Python block out of model output."""
    m = _CODE_FENCE.search(text)
    return m.group(1).strip() if m else None
