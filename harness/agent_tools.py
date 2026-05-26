"""v2.1: harness-driven tool wiring (no provider-native tool APIs).

The v2.0 build wired `qc_docs_retrieve` and `lean_backtest` as native
function-call tools described to each provider's tool-use API. v2.1 removes
that path entirely:

  - RAG is invoked when the model emits the literal `{R} <query>` handshake
    marker. See harness/orchestrator.py for the parser and the in-loop
    retrieval call.
  - Compiler feedback is the verbatim output of `lean_backtest_tool.run`
    appended to the next turn's context history. The model is NEVER told
    that "compiler feedback" exists — it just appears in context.

This module is kept as a thin compatibility shim so any caller still
importing `tool_defs_for` / `dispatch` gets a clean empty surface rather
than an ImportError. New callers should reach for the helpers in
`harness/orchestrator.py` directly.
"""

from __future__ import annotations

from typing import Any


def tool_defs_for(provider: str, tool_names: list[str] | None = None) -> list[dict]:
    """v2.1: always returns []. Provider validation is preserved so accidental
    misuse (an unknown provider name) still raises."""
    if provider not in ("anthropic", "openai", "google"):
        raise ValueError(f"Unknown provider: {provider!r}")
    return []


async def dispatch(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """v2.1: provider-native tool dispatch is disabled. Callers that reach
    this function have a wiring bug — return a structured error rather than
    silently no-op so the misuse surfaces in the artifact.
    """
    return {
        "output": (
            f"ERROR: tool dispatch is disabled in v2.1 "
            f"(attempted tool_name={tool_name!r}). RAG and compiler feedback "
            f"are driven by the orchestrator, not by provider tool-use."
        ),
        "is_error": True,
        "metadata": {"tool": tool_name, "disabled": True},
    }


__all__ = ["tool_defs_for", "dispatch"]
