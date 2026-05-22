"""Provider-shaped tool definitions + a dispatcher for the v2 agent loop.

Two tools live here:
    qc_docs_retrieve   wraps lean_rag.retrieve()             — used in C2, C4
    lean_backtest      wraps lean_backtest_tool.run()        — used in C3, C4

Each provider (Anthropic, OpenAI, Google) wants the tool described in a
slightly different shape. The `tool_defs_for(provider, tool_names)` helper
returns the provider-correct list; `dispatch(tool_name, tool_input)` runs the
underlying Python function and returns a string the model can consume as a
tool_result.

Docker requirement is hard per spec: if the model invokes `lean_backtest`
and Docker isn't available, the tool surfaces the error to the model
(INFRASTRUCTURE_ERROR trailer from lean_backtest_tool) and the orchestrator
treats the cell as errored. No silent AST fallback.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

# Lazy imports: lean_rag pulls in faiss/sentence-transformers at import time
# (~1s of overhead); we don't want that hit on harness boot when no tool is
# actually used.
_lean_rag_retrieve = None
_lean_backtest_run = None
_lean_backtest_run_config = None
_lean_backtest_run_result_cls = None


def _retrieve_fn():
    global _lean_rag_retrieve
    if _lean_rag_retrieve is None:
        from lean_rag import retrieve  # type: ignore
        _lean_rag_retrieve = retrieve
    return _lean_rag_retrieve


def _backtest_fn():
    global _lean_backtest_run, _lean_backtest_run_config, _lean_backtest_run_result_cls
    if _lean_backtest_run is None:
        from lean_backtest_tool import run, RunConfig, RunResult  # type: ignore
        _lean_backtest_run = run
        _lean_backtest_run_config = RunConfig
        _lean_backtest_run_result_cls = RunResult
    return _lean_backtest_run, _lean_backtest_run_config, _lean_backtest_run_result_cls


# Tool descriptions seen by the model. Worded for an LLM audience: short,
# task-oriented, no implementation detail beyond what helps it call them
# correctly.
QC_DOCS_RETRIEVE_DESC = (
    "Retrieve up to 5 QuantConnect LEAN documentation chunks relevant to a "
    "natural-language query about LEAN APIs, indicators, classes, or methods. "
    "Use this when you are unsure of an exact LEAN API surface — e.g., the "
    "right method name on QCAlgorithm, valid Resolution values, indicator "
    "constructor parameters. Returns up to 5 doc chunks as a single string."
)

LEAN_BACKTEST_DESC = (
    "Run the given LEAN algorithm under the pinned LEAN engine in Docker, and "
    "return a filtered backtest log. The log will contain ERROR::, Log::, and "
    "DEBUG:: lines from LEAN plus a trailer of the form 'ORDERS_PLACED: <n>' "
    "and 'LEAN_RUN_FINISHED' (or 'TIMEOUT_EXCEEDED' / "
    "'INFRASTRUCTURE_ERROR'). Pass the COMPLETE source of your candidate "
    "algorithm in `code`. `language` defaults to 'python'."
)


def _input_schema_qc_docs() -> dict:
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language query (e.g., 'how to subscribe to minute-resolution equity data').",
            },
        },
        "required": ["query"],
    }


def _input_schema_lean_backtest() -> dict:
    return {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Complete LEAN algorithm source. For python, must define a QCAlgorithm subclass.",
            },
            "language": {
                "type": "string",
                "enum": ["python", "csharp"],
                "description": "Language of the code. Defaults to 'python'.",
            },
        },
        "required": ["code"],
    }


def tool_defs_for(provider: str, tool_names: list[str]) -> list[dict]:
    """Return the provider-shaped list of tool definitions.

    Anthropic Messages API: `tools=[{"name":..., "description":...,
        "input_schema": {...}}]`.
    OpenAI Responses API: `tools=[{"type":"function", "name":..., "description":...,
        "parameters":{...}}]`.
    Google Gemini: function_declarations consumed by the gemini client.
    """
    out: list[dict] = []
    for name in tool_names:
        if name == "qc_docs_retrieve":
            schema = _input_schema_qc_docs()
            desc = QC_DOCS_RETRIEVE_DESC
        elif name == "lean_backtest":
            schema = _input_schema_lean_backtest()
            desc = LEAN_BACKTEST_DESC
        else:
            raise KeyError(f"Unknown tool name: {name!r}")

        if provider == "anthropic":
            out.append({"name": name, "description": desc, "input_schema": schema})
        elif provider == "openai":
            out.append({
                "type": "function",
                "name": name,
                "description": desc,
                "parameters": schema,
            })
        elif provider == "google":
            out.append({
                "name": name,
                "description": desc,
                "parameters": schema,
            })
        else:
            raise ValueError(f"Unknown provider: {provider!r}")
    return out


# --- Dispatcher ----------------------------------------------------------

_LEAN_WORKDIR     = os.environ.get("LEANBENCH_LEAN_WORKDIR",  str(Path.cwd() / "lean_workspace" / "agent_runs"))
_LEAN_DATA_DIR    = os.environ.get("LEANBENCH_LEAN_DATA_DIR", str(Path.cwd() / "data"))
_LEAN_DOCKER_IMG  = os.environ.get(
    "LEANBENCH_LEAN_DOCKER_IMAGE",
    "quantconnect/lean@sha256:dc84a683464681b2e6c9579bc7655e16d4802380367c77004e40a6a504088bd7",
)

# Per-call output-string cap on retrieve output (after joining the 5 chunks).
# 8000 chars is plenty for 5 BGE chunks (~1-2k chars each) without blowing
# the conversation budget at T=24.
_RETRIEVE_OUTPUT_CAP_CHARS = 12_000


def _run_retrieve(query: str) -> str:
    """Call lean_rag.retrieve, render the 5 chunks for the model."""
    chunks = _retrieve_fn()(query)
    if not chunks:
        return "(no documentation chunks matched the query)"
    rendered: list[str] = []
    for i, text in enumerate(chunks, 1):
        rendered.append(f"--- chunk {i} ---\n{text.strip()}")
    out = "\n\n".join(rendered)
    if len(out) > _RETRIEVE_OUTPUT_CAP_CHARS:
        out = out[:_RETRIEVE_OUTPUT_CAP_CHARS] + "\n[truncated]"
    return out


def _run_lean_backtest(code: str, language: str = "python") -> dict:
    """Run lean_backtest_tool.run synchronously; return a dict carrying the
    output string AND the exit_status (so the orchestrator can detect Docker
    failures and abort the call instead of silently degrading).
    """
    run, RunConfig, _ = _backtest_fn()
    Path(_LEAN_WORKDIR).mkdir(parents=True, exist_ok=True)
    cfg = RunConfig(
        workdir=_LEAN_WORKDIR,
        lean_data_dir=_LEAN_DATA_DIR,
        docker_image=_LEAN_DOCKER_IMG,
    )
    result = run(code, language, cfg)
    return {"output": result.output, "exit_status": result.exit_status}


async def dispatch(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Run a tool by name with the model-supplied JSON input.

    Returns a dict:
        {
          "output":      str,        # text shown to the model as tool_result
          "is_error":    bool,       # provider may mark the tool_result as error
          "metadata":    {...},      # bookkeeping for the orchestrator/artifacts
        }

    Hard-requires Docker for `lean_backtest`: if the tool returns
    exit_status='docker_error' the orchestrator treats the call as errored
    (see harness/orchestrator.py).
    """
    if tool_name == "qc_docs_retrieve":
        query = str(tool_input.get("query") or "").strip()
        if not query:
            return {
                "output": "ERROR: qc_docs_retrieve requires a non-empty 'query'.",
                "is_error": True,
                "metadata": {"tool": tool_name},
            }
        # retrieve uses sentence-transformers under the hood — push to a
        # threadpool so the event loop stays free for other concurrent calls.
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _run_retrieve, query)
        return {
            "output": text,
            "is_error": False,
            "metadata": {"tool": tool_name, "query": query, "chars": len(text)},
        }

    if tool_name == "lean_backtest":
        code = tool_input.get("code")
        if not isinstance(code, str) or not code.strip():
            return {
                "output": "ERROR: lean_backtest requires non-empty 'code' string.",
                "is_error": True,
                "metadata": {"tool": tool_name},
            }
        language = str(tool_input.get("language") or "python").lower()
        if language not in ("python", "csharp"):
            return {
                "output": f"ERROR: lean_backtest language must be 'python' or 'csharp', got {language!r}.",
                "is_error": True,
                "metadata": {"tool": tool_name, "language": language},
            }
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_lean_backtest, code, language)
        # exit_status=docker_error means the Docker daemon was unreachable.
        # Surface the error AND mark is_error so the orchestrator can abort
        # the cell — we will NOT silently degrade to AST feedback.
        is_error = result["exit_status"] in ("docker_error", "infra_error")
        return {
            "output": result["output"],
            "is_error": is_error,
            "metadata": {
                "tool": tool_name,
                "language": language,
                "exit_status": result["exit_status"],
                "code_chars": len(code),
            },
        }

    return {
        "output": f"ERROR: unknown tool name {tool_name!r}.",
        "is_error": True,
        "metadata": {"tool": tool_name},
    }


__all__ = [
    "QC_DOCS_RETRIEVE_DESC",
    "LEAN_BACKTEST_DESC",
    "tool_defs_for",
    "dispatch",
]
