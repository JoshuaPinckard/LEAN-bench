"""Unit tests for the sidecar artifact writer.

Covers spec §4 acceptance: each generated call writes an artifact whose
hash matches a recomputation, and the hash changes iff the content does.
"""

from __future__ import annotations

import hashlib
import json

from harness.artifacts import build_artifact, write_artifact


def _make_artifact(call_id="abc-123", **overrides):
    base = dict(
        call_id=call_id,
        prompt_id="lb-0001",
        model_friendly="claude-opus-4.7",
        model_pinned="claude-opus-4-7",
        condition_id="S1_base",
        trial_index=0,
        benchmark_version="LEAN-Bench-v1.0",
        prompt_set_sha256="deadbeef" * 8,
        judge_version="v2",
        judge_threshold=0.7,
        original_prompt="buy spy when rsi < 30",
        enriched_prompt="buy spy when rsi < 30",
        retrieval_snippet=None,
        response_text="```python\nclass A: ...\n```",
        generated_code="class A: ...",
        raw_response={"content": []},
        finish_reason="end_turn",
        tools_called=[],
        turns_used=1,
        error=None,
    )
    base.update(overrides)
    return build_artifact(**base)


def test_artifact_hash_is_reproducible(tmp_path):
    art = _make_artifact()
    path, sha_first = write_artifact(art, artifacts_dir=tmp_path)
    # Recompute from the on-disk bytes.
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha_first


def test_artifact_hash_changes_on_content_change(tmp_path):
    art1 = _make_artifact(response_text="version one")
    art2 = _make_artifact(response_text="version two")
    _, h1 = write_artifact(art1, artifacts_dir=tmp_path / "a")
    _, h2 = write_artifact(art2, artifacts_dir=tmp_path / "b")
    assert h1 != h2


def test_artifact_contains_provenance_and_hashes(tmp_path):
    art = _make_artifact(original_prompt="hello", generated_code="x = 1")
    path, _ = write_artifact(art, artifacts_dir=tmp_path)
    data = json.loads(path.read_text(encoding="ascii"))
    assert data["benchmark_version"] == "LEAN-Bench-v1.0"
    assert data["judge_threshold"] == 0.7
    assert data["prompt_set_sha256"] == "deadbeef" * 8
    # SHA256 of "hello"
    assert data["original_prompt_sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert data["generated_code_sha256"] == hashlib.sha256(b"x = 1").hexdigest()


def test_anthropic_web_citations_extracted():
    art = _make_artifact(
        raw_response={
            "content": [
                {
                    "type": "web_search_tool_result",
                    "content": [
                        {"type": "web_search_result", "title": "QC Docs", "url": "https://qc.example/x"},
                    ],
                },
            ],
        },
    )
    assert any(c.get("url") == "https://qc.example/x" for c in art["web_citations"])
    assert art["web_citations"][0]["provider"] == "anthropic"
