"""Condition introspection helpers for the v2.1 agent loop.

In v2.1 the orchestrator drives RAG and compiler feedback itself — there are
no provider-native tools exposed to the model. This module therefore reduces
to: condition validation, max-turn lookup, and an agentic-flag predicate.

`build_tools` and `tool_names_for` are kept as thin compatibility shims (both
always return []) so any callers still asking for a tools list get a clean
empty response rather than crashing.
"""

from __future__ import annotations

from harness.models import CONDITIONS


def tool_names_for(condition_id: str) -> list[str]:
    """Always returns [] in v2.1. Kept as a back-compat shim."""
    if condition_id not in CONDITIONS:
        raise KeyError(f"Unknown condition_id={condition_id!r}")
    return []


def build_tools(condition_id: str, provider: str) -> list[dict]:
    """Always returns [] in v2.1.

    v2.1 does not use provider-native function/tool APIs. RAG is invoked when
    the model emits the `{R}` text marker (parsed by harness/orchestrator.py);
    compiler feedback is the verbatim output of lean_backtest_tool, appended
    to the next turn's context history. Neither facility is described to the
    model as a tool definition.
    """
    if condition_id not in CONDITIONS:
        raise KeyError(f"Unknown condition_id={condition_id!r}")
    if provider not in ("anthropic", "openai", "google"):
        raise ValueError(f"Unknown provider: {provider!r}")
    return []


def is_agentic(condition_id: str) -> bool:
    """True iff this condition runs the multi-turn loop."""
    cond = CONDITIONS.get(condition_id)
    if cond is None:
        raise KeyError(f"Unknown condition_id={condition_id!r}")
    return bool(cond["tool_agentic_loop"])


def max_turns_for(condition_id: str) -> int:
    cond = CONDITIONS.get(condition_id)
    if cond is None:
        raise KeyError(f"Unknown condition_id={condition_id!r}")
    return int(cond["max_turns"])
