"""run_grid must use the DB's prompt text for benchmark-eligible prompts,
ignoring any caller-supplied `prompt_text`. Adhoc prompts pass through
verbatim. Without this, prompt_set_sha256 could be stamped on a run that
used different text than the frozen artifact records.
"""

from __future__ import annotations

import asyncio

import harness.orchestrator as orch
from harness.orchestrator import run_grid
from harness.storage import Store


def _stub_run_cell_capture(captured: list[str]):
    """Replace run_cell with a stub that records the prompt_text it was called
    with and returns a minimal result dict."""

    async def _stub(store, prompt_id, prompt_text, model, condition, *,
                    trial_index, prompt_set_sha256=None):
        captured.append(prompt_text)
        return {
            "call_id": "stub", "model": model, "condition": condition,
            "attempt": trial_index, "status": "completed",
            "generated_code": None, "response_text": None,
            "compile_pass": None, "backtest_pass": None, "trade_pass": None,
            "schema_pass": None,
            "judge_pass": None, "overall_pass": None,
            "judge_score_a": None, "judge_score_b": None,
            "cost_usd": None, "latency_ms": 0,
            "input_tokens": 0, "output_tokens": 0, "turns_used": 0,
            "error": None, "judge_error": None,
        }
    return _stub


def test_run_grid_uses_db_text_for_saved_prompt(tmp_path, monkeypatch):
    store = Store(tmp_path / "test.db")
    store.add_prompt(
        prompt_id="lb-0001",
        original_text="original",
        reformulated_text="CANONICAL DB TEXT",
        source="qc_forum",
    )

    captured: list[str] = []
    monkeypatch.setattr(orch, "run_cell", _stub_run_cell_capture(captured))
    # Skip the freeze guard for this test — pretend no artifact exists.
    monkeypatch.setattr(orch, "resolve_prompt_set_sha256", lambda *_: None)

    asyncio.run(run_grid(
        store, "lb-0001",
        prompt_text="CLIENT-SUPPLIED TEXT (should be ignored)",
        models=["claude-opus-4.7"],
        conditions=["C1_oneshot"],
        attempts=1,
    ))
    assert captured == ["CANONICAL DB TEXT"]


def test_run_grid_keeps_caller_text_for_adhoc_prompt(tmp_path, monkeypatch):
    store = Store(tmp_path / "test.db")
    store.add_prompt(
        prompt_id="adhoc-x",
        original_text="adhoc orig",
        reformulated_text="adhoc orig",
        source="adhoc",
    )

    captured: list[str] = []
    monkeypatch.setattr(orch, "run_cell", _stub_run_cell_capture(captured))
    monkeypatch.setattr(orch, "resolve_prompt_set_sha256", lambda *_: None)

    asyncio.run(run_grid(
        store, "adhoc-x",
        prompt_text="caller-supplied adhoc text",
        models=["claude-opus-4.7"],
        conditions=["C1_oneshot"],
        attempts=1,
    ))
    assert captured == ["caller-supplied adhoc text"]
