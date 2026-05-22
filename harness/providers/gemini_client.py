"""Google Gemini provider client with v2 function-call round-trip support.

Gemini's function-calling shape:
  - Tools are declared as types.Tool(function_declarations=[...]).
  - Model emits Part.function_call(name=..., args={...}) within the model
    Content.
  - We respond with a Content(role='user', parts=[Part.function_response(
        name=..., response={"output": "..."})]) in the next turn.

The harness keeps an OpenAI-style message list ({role, content[parts]}) as
the canonical conversation; we translate to/from Gemini Content objects at
the API boundary.
"""

from __future__ import annotations

import time
from typing import Any

from google import genai
from google.genai import types as genai_types

from harness.providers.base import ProviderResponse, ToolCall, extract_code


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


def _messages_to_contents(messages: list[dict]) -> list[genai_types.Content]:
    """Translate the canonical message list into Gemini Content objects.

    Recognised message shapes:
      {role: 'user'|'assistant', content: str}                     plain text
      {role: 'assistant', _gemini_parts: [Part,...]}               raw assistant turn (round-trip)
      {role: 'user', _gemini_parts: [Part,...]}                    raw function_response turn
    """
    contents: list[genai_types.Content] = []
    for m in messages:
        role = "model" if m.get("role") == "assistant" else "user"
        if "_gemini_parts" in m:
            contents.append(genai_types.Content(role=role, parts=list(m["_gemini_parts"])))
            continue
        content = m.get("content")
        if isinstance(content, str):
            contents.append(genai_types.Content(role=role, parts=[genai_types.Part(text=content)]))
        elif isinstance(content, list):
            # Defensive: support content as a list of {type:'text', text:'...'} or {output:'...'}.
            parts: list[genai_types.Part] = []
            for c in content:
                if isinstance(c, dict):
                    txt = c.get("text") or c.get("output") or ""
                    if txt:
                        parts.append(genai_types.Part(text=str(txt)))
            contents.append(genai_types.Content(role=role, parts=parts))
    return contents


def _build_tools_arg(tools: list[dict] | None) -> list[genai_types.Tool] | None:
    if not tools:
        return None
    decls = [
        genai_types.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters=t.get("parameters"),
        )
        for t in tools
    ]
    return [genai_types.Tool(function_declarations=decls)]


async def call(
    model_pinned: str,
    messages: list[dict],
    system_prompt: str = "",
    tools: list[dict] | None = None,
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
    tool_arg = _build_tools_arg(tools)
    if tool_arg is not None:
        config.tools = tool_arg

    contents = _messages_to_contents(messages)

    start = time.monotonic()
    resp = await client.aio.models.generate_content(
        model=model_pinned,
        contents=contents,
        config=config,
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    tools_called: list[str] = []
    raw_parts: list[genai_types.Part] = []

    if resp.candidates:
        for part in (resp.candidates[0].content.parts or []):
            # text part
            if getattr(part, "text", None):
                text_parts.append(part.text)
                raw_parts.append(part)
                continue
            fc = getattr(part, "function_call", None)
            if fc is not None and getattr(fc, "name", None):
                args = dict(fc.args) if fc.args is not None else {}
                # Gemini doesn't issue stable per-call ids; we generate one
                # from name + a monotonic counter so the orchestrator can
                # round-trip by-position.
                gen_id = f"gemini-{len(tool_calls)}-{fc.name}"
                tool_calls.append({"id": gen_id, "name": fc.name, "input": args})
                tools_called.append(fc.name)
                raw_parts.append(part)

    response_text = "".join(text_parts)

    usage = resp.usage_metadata
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    cached = getattr(usage, "cached_content_token_count", 0) or 0

    finish_reason = "unknown"
    if resp.candidates:
        fr = resp.candidates[0].finish_reason
        finish_reason = fr.name if fr is not None else "unknown"

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
        tools_called=tools_called,
        tool_calls=tool_calls,
        # Store the raw assistant Parts list under our convention so the
        # round-trip in _messages_to_contents can replay them verbatim.
        raw_assistant_turn={"role": "assistant", "_gemini_parts": raw_parts},
        raw_response=raw,
    )


def build_tool_result_message(tool_call: ToolCall, tool_output: dict) -> dict:
    """Render a function_response Part for the next user turn."""
    part = genai_types.Part.from_function_response(
        name=tool_call["name"],
        response={"output": tool_output["output"]},
    )
    return {"role": "user", "_gemini_parts": [part]}
