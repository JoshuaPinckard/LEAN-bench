"""v2.0 wiring sanity tests.

Covers things that ARE NOT exercised by the inherited v1 tests:
  - Tool definitions render correctly per provider.
  - Schema-adherence evaluator catches mismatches and ignores fields the
    prompt didn't pin.
  - Dual-judge combination math (averaging + intent AND).
  - Storage's dual-judge column writes round-trip.
"""

from __future__ import annotations

import json

import pytest

from harness.agent_tools import tool_defs_for
from harness.conditions.builder import build_tools
from harness.evaluator import derive_overall_pass, evaluate_schema
from harness.storage import Store


# ----- tool defs ---------------------------------------------------------

def test_anthropic_tool_defs_for_c4_have_input_schema():
    tools = build_tools("C4_docs_compiler", "anthropic")
    names = [t["name"] for t in tools]
    assert names == ["qc_docs_retrieve", "lean_backtest"]
    for t in tools:
        assert "input_schema" in t
        assert t["input_schema"]["type"] == "object"


def test_openai_tool_defs_use_function_type():
    tools = build_tools("C2_docs", "openai")
    assert tools[0]["type"] == "function"
    assert tools[0]["name"] == "qc_docs_retrieve"
    assert "parameters" in tools[0]


def test_gemini_tool_defs_carry_parameters():
    tools = build_tools("C3_compiler", "google")
    assert tools[0]["name"] == "lean_backtest"
    assert "parameters" in tools[0]


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        tool_defs_for("nonexistent", ["qc_docs_retrieve"])


# ----- schema-adherence stage -------------------------------------------

_GOOD = """
from AlgorithmImports import *
class A(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2021, 1, 1)
        self.AddEquity("SPY", Resolution.Daily)
    def OnData(self, data):
        pass
"""


def test_schema_pass_when_everything_matches():
    record = {
        "securities_type": "equity",
        "start_date": "2020-01-01",
        "end_date": "2021-01-01",
        "resolution": "daily",
    }
    out = evaluate_schema(_GOOD, record)
    assert out["schema_pass"] is True
    assert out["schema_violations"] == []


def test_schema_fail_wrong_resolution():
    record = {"securities_type": "equity", "resolution": "minute"}
    out = evaluate_schema(_GOOD, record)
    assert out["schema_pass"] is False
    assert any("wrong_resolution" in v for v in out["schema_violations"])


def test_schema_ignores_fields_prompt_didnt_pin():
    # No resolution or dates in prompt — code's daily/2020-... must not penalise.
    record = {"securities_type": "equity"}
    out = evaluate_schema(_GOOD, record)
    assert out["schema_pass"] is True


def test_schema_no_code_fails():
    out = evaluate_schema(None, {"securities_type": "equity"})
    assert out["schema_pass"] is False
    assert out["schema_violations"] == ["no_code_emitted"]


# ----- overall_pass combinator ------------------------------------------

def test_overall_pass_demands_all_stages_true_for_trade_required():
    assert derive_overall_pass(
        compile_pass=True, runtime_pass=True, trade_pass=True,
        schema_pass=True, judge_pass=True,
        evaluation_mode="trade_required",
    ) is True


def test_overall_pass_code_only_ignores_trade_field():
    # code_only prompts: zero trades is fine.
    assert derive_overall_pass(
        compile_pass=True, runtime_pass=True, trade_pass=False,
        schema_pass=True, judge_pass=True,
        evaluation_mode="code_only",
    ) is True


def test_overall_pass_short_circuits_on_compile_fail():
    assert derive_overall_pass(
        compile_pass=False, runtime_pass=None, trade_pass=None,
        schema_pass=None, judge_pass=None,
        evaluation_mode="trade_required",
    ) is False


# ----- dual-judge storage write -----------------------------------------

def test_update_call_with_judge_persists_dual_judge_columns(tmp_path):
    store = Store(tmp_path / "v2.db")
    store.add_prompt(prompt_id="lb-0001", original_text="x", reformulated_text="x", source="qc_forum")
    store.create_call(
        call_id="cid", prompt_id="lb-0001",
        model_id="claude-opus-4.7", condition="C1_oneshot",
        status="started", compile_pass=True,
    )
    store.update_call_with_judge(
        "cid",
        judge_score=0.85,
        judge_reasoning="combined reasoning",
        judge_version="v3",
        failure_mode=[],
        matches_prompt_intent=True,
        judge_score_a=0.8,
        judge_score_b=0.9,
        judge_reasoning_a="reasoning a",
        judge_reasoning_b="reasoning b",
        judge_version_a="v3",
        judge_version_b="v3",
        judge_model_a="claude-sonnet-4-6",
        judge_model_b="gpt-5.4-2026-03-05",
        judge_error_a=None,
        judge_error_b=None,
    )
    row = store.get_call("cid")
    assert row["judge_score"] == pytest.approx(0.85)
    assert row["judge_score_a"] == pytest.approx(0.8)
    assert row["judge_score_b"] == pytest.approx(0.9)
    assert row["judge_pass"] == 1  # 0.85 >= 0.7
    assert row["judge_model_a"] == "claude-sonnet-4-6"
    assert row["judge_model_b"] == "gpt-5.4-2026-03-05"
