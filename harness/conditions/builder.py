"""Translate a condition_id into the provider-specific tool config that gets
passed to the LLM API.

Web search is uncapped on all providers — each provider's native tool decides
how many searches to run, and we log observed counts from
ProviderResponse.tools_called rather than enforce an asymmetric numeric cap.
See CONDITIONS docstring in harness/models.py for the methodology rationale.

QC docs retrieval (when wired) is hard-capped at the MCP server we own, so the
cap is uniform across providers; see cond["qc_docs_max_uses"].
"""

from __future__ import annotations

from harness.models import CONDITIONS


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
            })
        elif provider == "openai":
            tools.append({"type": "web_search_preview"})
        elif provider == "google":
            tools.append({"google_search": {}})

    # tool_docs_retrieval: QC docs RAG not yet implemented. Once an MCP server
    # exists, emit a provider-shaped retrieval tool here. The MCP server itself
    # enforces cond["qc_docs_max_uses"] (5/turn) — uniform across providers.
    # if cond["tool_docs_retrieval"]: ...

    return tools


def is_agentic(condition_id: str) -> bool:
    """True iff this condition runs the multi-turn feedback loop."""
    return CONDITIONS[condition_id]["tool_agentic_loop"]


def max_turns_for(condition_id: str) -> int:
    return CONDITIONS[condition_id]["max_turns"]
