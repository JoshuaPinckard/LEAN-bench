"""Exclusion + denominator accounting tests under v2.0.

v2 has no design-time exclusions (the proposal-faithful tool wiring works
for all three providers), so EXCLUDED_CELLS is empty. The schema columns
(status, excluded_reason) still exist for forward compatibility and the
accounting helpers still distinguish excluded rows from completed ones —
those code paths are exercised here by manually seeding a status='excluded'
row.
"""

from __future__ import annotations

import pytest

from harness.constants import EXCLUDED_CELLS, excluded_reason_for
from harness.storage import Store


def test_excluded_cells_table_is_empty_in_v2():
    assert EXCLUDED_CELLS == {}


def test_excluded_reason_for_returns_none_for_every_v2_cell():
    for cid in ("C1_oneshot", "C2_docs", "C3_compiler", "C4_docs_compiler"):
        for model in ("claude-opus-4.7", "gpt-5.5", "gemini-3.1-pro"):
            assert excluded_reason_for(model, cid) is None, (model, cid)


def test_pass_rate_matrix_drops_excluded_rows_from_denominator(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    store.add_prompt(
        prompt_id="lb-0001",
        original_text="x", reformulated_text="x",
        source="qc_forum",
    )
    # 2 passing + 1 failing on C1; 1 manually-excluded on C2 to exercise the
    # accounting paths.
    for i in range(2):
        store.create_call(
            call_id=f"pass-{i}", prompt_id="lb-0001",
            model_id="claude-opus-4.7", condition="C1_oneshot",
            pass_number=i, status="completed",
            judge_pass=True,
        )
    store.create_call(
        call_id="fail-0", prompt_id="lb-0001",
        model_id="claude-opus-4.7", condition="C1_oneshot",
        pass_number=2, status="completed",
        judge_pass=False,
    )
    store.create_call(
        call_id="excluded-0", prompt_id="lb-0001",
        model_id="gemini-3.1-pro", condition="C2_docs",
        pass_number=0, status="excluded", excluded_reason="manual_test",
    )

    matrix = store.pass_rate_matrix()
    by_cell = {(r["model_id"], r["condition_id"]): r for r in matrix}

    opus_c1 = by_cell[("claude-opus-4.7", "C1_oneshot")]
    assert opus_c1["n"] == 3
    assert opus_c1["excluded"] == 0
    assert opus_c1["pass_rate"] == pytest.approx(2 / 3)
    assert opus_c1["status"] is None

    gemini_c2 = by_cell[("gemini-3.1-pro", "C2_docs")]
    assert gemini_c2["n"] == 0
    assert gemini_c2["excluded"] == 1
    assert gemini_c2["pass_rate"] is None
    assert gemini_c2["status"] == "excluded"


def test_total_call_count_and_cost_exclude_excluded_rows(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    store.add_prompt(
        prompt_id="lb-0001", original_text="x", reformulated_text="x", source="qc_forum",
    )
    store.create_call(
        call_id="real", prompt_id="lb-0001",
        model_id="claude-opus-4.7", condition="C1_oneshot",
        status="completed", total_cost_usd=0.02,
    )
    store.create_call(
        call_id="excluded", prompt_id="lb-0001",
        model_id="gemini-3.1-pro", condition="C2_docs",
        status="excluded", excluded_reason="manual_test",
        total_cost_usd=0.0,
    )
    assert store.call_count() == 1
    assert store.excluded_count() == 1
    assert store.total_cost_usd() == pytest.approx(0.02)
    assert "gemini-3.1-pro" not in store.cost_by_model()


def test_wipe_calls_clears_calls_and_turns(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    store.add_prompt(prompt_id="lb-0001", original_text="x", reformulated_text="x", source="qc_forum")
    store.create_call(
        call_id="A", prompt_id="lb-0001",
        model_id="claude-opus-4.7", condition="C1_oneshot",
        status="completed",
    )
    store.record_turn(
        call_id="A", turn_index=0,
        prompt_messages_json="[]",
        response_text="ok",
        ran_pipeline=True,
    )
    before = store.wipe_calls()
    assert before == {"calls_deleted": 1, "turns_deleted": 1}
    assert store.call_count() == 0
    assert len(store.list_prompts()) == 1  # prompts preserved
