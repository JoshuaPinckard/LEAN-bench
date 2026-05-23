"""Translate a v2 condition_id into provider-specific tool configuration.

In v2 the tools are NOT provider-native search tools — they are first-party
function tools:
    qc_docs_retrieve   wraps lean_rag.retrieve()             (C2, C4)
    lean_backtest      wraps lean_backtest_tool.run()        (C3, C4)

The actual tool definitions live in harness/agent_tools.py. This module just
maps a condition_id to the list of tool names that should be exposed to the
model for that condition.
"""

from __future__ import annotations

from harness.agent_tools import tool_defs_for
from harness.models import CONDITIONS


def tool_names_for(condition_id: str) -> list[str]:
    """Return the list of tool names exposed in this condition. Empty for
    the no-tool C1 baseline."""
    cond = CONDITIONS.get(condition_id)
    if cond is None:
        raise KeyError(f"Unknown condition_id={condition_id!r}")
    return list(cond["tools"])


def build_tools(condition_id: str, provider: str) -> list[dict]:
    """Return the provider-shaped tool list for this condition.

    Returns [] for conditions with no tools."""
    names = tool_names_for(condition_id)
    if not names:
        return []
    return tool_defs_for(provider, names)


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
