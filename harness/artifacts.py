"""Sidecar artifact writer.

For every NON-excluded call, a JSON sidecar is written to
`results/artifacts/{call_id}.json` capturing everything a reviewer needs to
audit the row without re-running the model: identity, hashes, retrieval
snippet, raw provider response, extracted tool calls, web citations, and
text/code hashes.

The artifact path and SHA256 are persisted on `calls.artifact_path` and
`calls.artifact_sha256` so the DB and the file system can be cross-checked.

Important honesty caveat (S3): web search providers do not generally expose
the model's full internal retrieved context. The artifact captures the
provider-EXPOSED web artifacts (tool calls, citations, URLs, response items
where the provider surfaces them). The decision log explicitly disclaims
perfect reconstruction; that disclaimer is mirrored in the field comment
below for any reader inspecting one of these files directly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACTS_DIR_DEFAULT = Path("results/artifacts")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_hash(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_web_citations(raw: dict | None) -> list[dict]:
    """Best-effort extraction of provider-exposed web citations across the
    three SDKs. Returns a list of {provider, title, url, snippet?} dicts.

    Anthropic: content blocks of type=web_search_tool_result with `content`
    containing items {type:'web_search_result', title, url, ...}.
    OpenAI Responses API: items with type='web_search_call' / 'message' that
    include url_citation annotations on text blocks.
    Gemini: grounding_metadata in candidates[0].grounding_metadata.web_search_queries
    and .grounding_chunks[].web.{uri, title}.
    """
    if not isinstance(raw, dict):
        return []
    out: list[dict] = []

    # Anthropic
    for block in raw.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "web_search_tool_result":
            for item in block.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "web_search_result":
                    out.append({
                        "provider":      "anthropic",
                        "title":         item.get("title"),
                        "url":           item.get("url"),
                        "encrypted_id":  item.get("encrypted_content_id"),
                    })

    # OpenAI Responses
    for item in raw.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                for ann in content.get("annotations") or []:
                    if isinstance(ann, dict) and ann.get("type") in ("url_citation", "citation"):
                        out.append({
                            "provider": "openai",
                            "title":    ann.get("title"),
                            "url":      ann.get("url"),
                        })

    # Gemini
    for cand in raw.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        gm = cand.get("grounding_metadata") or {}
        for chunk in gm.get("grounding_chunks") or []:
            web = chunk.get("web") or {} if isinstance(chunk, dict) else {}
            if web.get("uri") or web.get("title"):
                out.append({
                    "provider": "google",
                    "title":    web.get("title"),
                    "url":      web.get("uri"),
                })
    return out


def _extract_tool_calls(raw: dict | None) -> list[dict]:
    """Best-effort extraction of tool invocations the model made."""
    if not isinstance(raw, dict):
        return []
    out: list[dict] = []
    # Anthropic
    for block in raw.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            out.append({
                "provider": "anthropic",
                "name":     block.get("name"),
                "input":    block.get("input"),
            })
    # OpenAI Responses surfaces tool calls as items in `output`.
    for item in raw.get("output") or []:
        if isinstance(item, dict) and item.get("type") and item.get("type") != "message":
            out.append({
                "provider": "openai",
                "type":     item.get("type"),
                # web_search_call has `action.query` plus `action.sources` per recent SDKs.
                "action":   item.get("action"),
            })
    # Gemini
    for cand in raw.get("candidates") or []:
        gm = cand.get("grounding_metadata") or {} if isinstance(cand, dict) else {}
        for q in gm.get("web_search_queries") or []:
            out.append({"provider": "google", "type": "web_search_call", "query": q})
    return out


def build_artifact(
    *,
    call_id: str,
    prompt_id: str,
    model_friendly: str,
    model_pinned: str,
    condition_id: str,
    trial_index: int,
    benchmark_version: str,
    prompt_set_sha256: str | None,
    judge_version: str,
    judge_threshold: float,
    original_prompt: str,
    enriched_prompt: str,
    retrieval_snippet: str | None,
    response_text: str | None,
    generated_code: str | None,
    raw_response: dict | None,
    finish_reason: str | None,
    tools_called: list[str] | None,
    turns_used: int,
    error: str | None,
) -> dict[str, Any]:
    """Compose the artifact dict. No I/O — `write_artifact` persists it."""
    return {
        "schema":              "lean_bench_call_artifact_v1",
        "call_id":             call_id,
        "prompt_id":           prompt_id,
        "model_friendly":      model_friendly,
        "model_pinned":        model_pinned,
        "condition_id":        condition_id,
        "trial_index":         trial_index,
        "turns_used":          turns_used,
        # Provenance
        "benchmark_version":   benchmark_version,
        "prompt_set_sha256":   prompt_set_sha256,
        "judge_version":       judge_version,
        "judge_threshold":     judge_threshold,
        "captured_at_utc":     _utc_now_iso(),
        # Prompt identity
        "original_prompt_sha256":  _safe_hash(original_prompt),
        "enriched_prompt_sha256":  _safe_hash(enriched_prompt),
        "retrieval_snippet":       retrieval_snippet,
        "retrieval_snippet_sha256": _safe_hash(retrieval_snippet),
        # Response
        "response_text":           response_text,
        "generated_code_sha256":   _safe_hash(generated_code),
        "finish_reason":           finish_reason,
        "tools_called":            tools_called or [],
        # Web artifacts (best-effort, provider-exposed only)
        "tool_calls":              _extract_tool_calls(raw_response),
        "web_citations":           _extract_web_citations(raw_response),
        # NOTE: web_citations captures the artifacts the provider EXPOSES.
        # Some providers retain internal retrieval context the API does not
        # surface. The benchmark does not claim perfect reconstruction of the
        # internal context — see docs/benchmark_decision_log.md §4.
        "raw_response":            raw_response,
        "error":                   error,
    }


def write_artifact(
    artifact: dict[str, Any],
    artifacts_dir: Path = ARTIFACTS_DIR_DEFAULT,
) -> tuple[Path, str]:
    """Write artifact JSON and return (path, sha256_hex).

    Output bytes are canonical (sort_keys, ascii) so the hash is reproducible
    from a fresh read+rewrite. The orchestrator stores both the path and the
    hash on the calls row.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    out_path = artifacts_dir / f"{artifact['call_id']}.json"
    payload = json.dumps(
        artifact, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("ascii")
    out_path.write_bytes(payload)
    return out_path, hashlib.sha256(payload).hexdigest()
