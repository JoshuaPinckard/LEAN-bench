"""Translate a condition_id into the provider-specific tool config that gets
passed to the LLM API.

For each provider we map the abstract tool flags from CONDITIONS into native
tool specs:

  - tool_web_search: Anthropic web_search server tool, OpenAI web_search_preview,
    Gemini google_search.
  - tool_docs_retrieval: TODO — QC docs RAG is not yet wired up. The condition
    is recognized in the schema but no tool is emitted today.
  - tool_agentic_loop: handled by the orchestrator (multi-turn flow), not by
    a tool spec.
"""

from __future__ import annotations

from harness.models import CONDITIONS, MAX_RETRIEVAL_CALLS_PER_TURN


def build_tools(condition_id: str, provider: str) -> list[dict]:
    """Return the provider-shaped tool list for this condition.

    Returns [] for S1_base or any condition with no tools wired up yet.
    """
    cond = CONDITIONS.get(condition_id)
    if cond is None:
        raise KeyError(f"Unknown condition_id={condition_id!r}")

    tools: list[dict] = []

    if cond["tool_web_search"]:
        if provider == "anthropic":
            tools.append({
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": MAX_RETRIEVAL_CALLS_PER_TURN,
            })
        elif provider == "openai":
            # Note: requires the Responses API path; chat.completions ignores it.
            tools.append({"type": "web_search_preview"})
        elif provider == "google":
            tools.append({"google_search": {}})

    # tool_docs_retrieval: QC docs RAG not yet implemented. Once a vector store
    # exists, emit a provider-shaped retrieval tool here.
    # if cond["tool_docs_retrieval"]: ...

    return tools


def is_agentic(condition_id: str) -> bool:
    """True iff this condition runs the multi-turn feedback loop."""
    return CONDITIONS[condition_id]["tool_agentic_loop"]


def max_turns_for(condition_id: str) -> int:
    return CONDITIONS[condition_id]["max_turns"]
