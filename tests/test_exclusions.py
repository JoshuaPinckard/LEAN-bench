"""Unit tests for design-time cell exclusions.

Covers spec §2 acceptance: excluded rows are persisted with status='excluded'
and excluded_reason set, no provider call is fired, and they are dropped
from pass-rate denominators / attempted-call totals.
"""

from __future__ import annotations

import asyncio

import pytest

from harness.constants import EXCLUDED_CELLS, excluded_reason_for
from harness.orchestrator import run_cell
from harness.storage import Store


def test_excluded_cells_table_has_gemini_s3_and_a1():
    assert ("gemini-3.1-pro", "S3_web") in EXCLUDED_CELLS
    assert ("gemini-3.1-pro", "A1_agentic_full") in EXCLUDED_CELLS
    assert EXCLUDED_CELLS[("gemini-3.1-pro", "S3_web")] == "tooling_parity"


def test_excluded_reason_for_returns_none_for_non_excluded_cells():
    assert excluded_reason_for("claude-opus-4.7", "S3_web") is None
    assert excluded_reason_for("gemini-3.1-pro", "S1_base") is None
    assert excluded_reason_for("gemini-3.1-pro", "S2_docs") is None


def test_excluded_reason_for_returns_reason_for_excluded_cells():
    assert excluded_reason_for("gemini-3.1-pro", "S3_web") == "tooling_parity"
    assert excluded_reason_for("gemini-3.1-pro", "A1_agentic_full") == "tooling_parity"


def test_excluded_run_writes_row_without_provider_call(tmp_path, monkeypatch):
    """Hitting an excluded cell must create the row and skip the provider."""
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    store.add_prompt(
        prompt_id="lb-0001",
        original_text="x", reformulated_text="x",
        source="qc_forum",
    )

    # If any provider client is called, fail loudly.
    async def _no_call(*args, **kwargs):
        raise AssertionError("provider should not be called on excluded cell")

    import harness.orchestrator as orch
    monkeypatch.setitem(orch.PROVIDER_CALL, "google", _no_call)

    result = asyncio.run(run_cell(
        store, "lb-0001", "x", "gemini-3.1-pro", "S3_web", trial_index=0,
        prompt_set_sha256=None,
    ))

    assert result["status"] == "excluded"
    assert result["excluded_reason"] == "tooling_parity"
    row = store.get_call(result["call_id"])
    assert row is not None
    assert row["status"] == "excluded"
    assert row["excluded_reason"] == "tooling_parity"


def test_pass_rate_matrix_drops_excluded_rows_from_denominator(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    store.add_prompt(
        prompt_id="lb-0001",
        original_text="x", reformulated_text="x",
        source="qc_forum",
    )

    # 2 completed passing + 1 completed failing + 1 excluded
    for i in range(2):
        store.create_call(
            call_id=f"pass-{i}", prompt_id="lb-0001",
            model_id="claude-opus-4.7", condition="S1_base",
            pass_number=i, status="completed",
            judge_pass=True,
        )
    store.create_call(
        call_id="fail-0", prompt_id="lb-0001",
        model_id="claude-opus-4.7", condition="S1_base",
        pass_number=2, status="completed",
        judge_pass=False,
    )
    store.create_call(
        call_id="excluded-0", prompt_id="lb-0001",
        model_id="gemini-3.1-pro", condition="S3_web",
        pass_number=0, status="excluded", excluded_reason="tooling_parity",
    )

    matrix = store.pass_rate_matrix()
    by_cell = {(r["model_id"], r["condition_id"]): r for r in matrix}

    opus_s1 = by_cell[("claude-opus-4.7", "S1_base")]
    assert opus_s1["n"] == 3
    assert opus_s1["excluded"] == 0
    assert opus_s1["pass_rate"] == pytest.approx(2 / 3)
    assert opus_s1["status"] is None

    gemini_s3 = by_cell[("gemini-3.1-pro", "S3_web")]
    assert gemini_s3["n"] == 0
    assert gemini_s3["excluded"] == 1
    assert gemini_s3["pass_rate"] is None
    assert gemini_s3["status"] == "excluded"


def test_total_call_count_and_cost_exclude_excluded_rows(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    store.add_prompt(
        prompt_id="lb-0001", original_text="x", reformulated_text="x", source="qc_forum",
    )
    store.create_call(
        call_id="real", prompt_id="lb-0001",
        model_id="claude-opus-4.7", condition="S1_base",
        status="completed", total_cost_usd=0.02,
    )
    store.create_call(
        call_id="excluded", prompt_id="lb-0001",
        model_id="gemini-3.1-pro", condition="S3_web",
        status="excluded", excluded_reason="tooling_parity",
        total_cost_usd=0.0,
    )
    assert store.call_count() == 1
    assert store.excluded_count() == 1
    assert store.total_cost_usd() == pytest.approx(0.02)
    assert "gemini-3.1-pro" not in store.cost_by_model()
