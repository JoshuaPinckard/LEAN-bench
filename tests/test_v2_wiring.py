"""v2.1 wiring sanity tests (harness-driven, no provider tools).

Covers things that ARE NOT exercised by the inherited v1 tests:
  - Provider tool-defs return []: v2.1 does not use native tool APIs.
  - {R} handshake parser correctly classifies rag_query / code / invalid.
  - render_user_message includes the labeled context history and the
    original prompt at the bottom.
  - The compiler-output parser reads the lean_backtest_tool trailer.
  - Schema-adherence evaluator catches mismatches and ignores fields the
    prompt didn't pin.
  - Dual-judge combination math (averaging + intent AND).
  - Storage's dual-judge column writes round-trip.
  - Storage migration provides the v2.1 first-pass and counter columns.
"""

from __future__ import annotations

import json

import pytest

from harness.agent_tools import tool_defs_for
from harness.conditions.builder import build_tools, max_turns_for, is_agentic
from harness.evaluator import derive_overall_pass, evaluate_schema
from harness.orchestrator import (
    SYSTEM_PROMPTS, _parse_compiler_output, parse_response, render_user_message,
)
from harness.storage import Store


# ----- v2.1: no native tool APIs -----------------------------------------

def test_build_tools_returns_empty_for_every_condition():
    for cond in ("C1_oneshot", "C2_docs", "C3_compiler", "C4_docs_compiler"):
        for prov in ("anthropic", "openai", "google"):
            assert build_tools(cond, prov) == []


def test_tool_defs_for_returns_empty():
    assert tool_defs_for("anthropic", ["qc_docs_retrieve"]) == []
    assert tool_defs_for("openai", []) == []


def test_tool_defs_for_unknown_provider_raises():
    with pytest.raises(ValueError):
        tool_defs_for("nonexistent")


def test_conditions_have_expected_max_turns():
    assert max_turns_for("C1_oneshot") == 1
    assert max_turns_for("C2_docs") >= 1
    assert is_agentic("C1_oneshot") is False
    assert is_agentic("C2_docs") is True


# ----- system prompts: per-condition + only C2/C4 mention {R} ------------

def test_only_c2_and_c4_advertise_rag_handshake():
    assert "{R}" in SYSTEM_PROMPTS["C2_docs"]
    assert "{R}" in SYSTEM_PROMPTS["C4_docs_compiler"]
    assert "{R}" not in SYSTEM_PROMPTS["C1_oneshot"]
    assert "{R}" not in SYSTEM_PROMPTS["C3_compiler"]


def test_system_prompts_never_mention_compiler_feedback():
    # C3/C4 have compiler feedback, but the system prompt MUST NOT describe
    # it — it shows up in the user's context history block instead.
    for cond in ("C1_oneshot", "C2_docs", "C3_compiler", "C4_docs_compiler"):
        text = SYSTEM_PROMPTS[cond].lower()
        assert "compiler feedback" not in text
        assert "lean_backtest" not in text


def test_system_prompts_never_describe_schema_fields():
    # Curator-pinned start/end/securities/resolution must NEVER appear in any
    # system prompt — the agent has to derive them from the user's natural
    # language. The schema check happens behind the scenes in evaluate_schema.
    for cond in ("C1_oneshot", "C2_docs", "C3_compiler", "C4_docs_compiler"):
        text = SYSTEM_PROMPTS[cond].lower()
        assert "required schema" not in text
        assert "setstartdate" not in text


# ----- {R} parser --------------------------------------------------------

def test_parse_response_strict_rag_prefix():
    kind, payload = parse_response("{R} how to subscribe to minute equity data")
    assert kind == "rag_query"
    assert payload == "how to subscribe to minute equity data"


def test_parse_response_rag_tolerates_leading_whitespace():
    kind, payload = parse_response("  \n{R}   how to add a Bollinger Bands  ")
    assert kind == "rag_query"
    assert payload == "how to add a Bollinger Bands"


def test_parse_response_empty_rag_query_is_invalid():
    kind, payload = parse_response("{R}")
    assert kind == "invalid"


def test_parse_response_python_fence_returns_code():
    text = "Sure, here is the algorithm:\n\n```python\nclass A: pass\n```\n"
    kind, payload = parse_response(text)
    assert kind == "code"
    assert "class A: pass" in payload


def test_parse_response_neither_marker_nor_fence_invalid():
    kind, payload = parse_response("I am not sure how to do that")
    assert kind == "invalid"


# ----- user-message renderer --------------------------------------------

def test_render_user_message_no_history_is_just_original_prompt():
    out = render_user_message("Do the thing", [])
    assert out.endswith("Do the thing")
    assert "[Original prompt]" in out
    assert "[Context history" not in out


def test_render_user_message_history_includes_labels_and_results():
    history = [
        {"kind": "rag",  "model_text": "{R} bollinger", "rag_result": "chunk1\nchunk2"},
        {"kind": "code", "model_text": "```python\nx=1\n```",
         "compiler_feedback": "ERROR:: oops"},
    ]
    out = render_user_message("Implement BB strategy", history)
    assert "[Context history" in out
    assert "--- Attempt 1 ---" in out
    assert "--- Attempt 2 ---" in out
    assert "RAG result:" in out
    assert "chunk1" in out
    assert "Compiler feedback:" in out
    assert "ERROR:: oops" in out
    assert out.endswith("Implement BB strategy")


def test_render_user_message_omits_optional_blocks():
    # Schema/judge fail records carry no rag_result and no compiler_feedback.
    history = [{"kind": "code", "model_text": "```python\nx=1\n```"}]
    out = render_user_message("Do thing", history)
    assert "RAG result:" not in out
    assert "Compiler feedback:" not in out


# ----- compiler output parser -------------------------------------------

def test_parse_compiler_completed_with_trades():
    log = "Log:: starting up\n\nORDERS_PLACED: 12\nLEAN_RUN_FINISHED"
    out = _parse_compiler_output(log, "completed")
    assert out["runtime_success"] is True
    assert out["num_trades"] == 12
    assert out["runtime_error"] is None


def test_parse_compiler_completed_no_trades():
    log = "Log:: ran\n\nORDERS_PLACED: 0\nLEAN_RUN_FINISHED"
    out = _parse_compiler_output(log, "completed")
    assert out["runtime_success"] is True
    assert out["num_trades"] == 0


def test_parse_compiler_runtime_error():
    log = "ERROR:: During the algorithm execution: NoneType has no attribute 'Update'\n\nORDERS_PLACED: 0\nLEAN_RUN_FINISHED"
    out = _parse_compiler_output(log, "completed")
    assert out["runtime_success"] is False
    assert out["runtime_error"] is not None
    assert "NoneType" in out["runtime_error"]


def test_parse_compiler_timeout():
    log = "Log:: hung\n\nTIMEOUT_EXCEEDED: backtest killed after 900s"
    out = _parse_compiler_output(log, "timeout")
    assert out["runtime_success"] is False
    assert "timed out" in out["runtime_error"].lower()


def test_parse_compiler_infra_error():
    log = "\nINFRASTRUCTURE_ERROR: tool failed to invoke LEAN"
    out = _parse_compiler_output(log, "docker_error")
    assert out["runtime_success"] is False
    assert "infrastructure" in out["runtime_error"].lower()


def test_parse_compiler_orders_unknown():
    log = "\nORDERS_PLACED: unknown\nLEAN_RUN_FINISHED"
    out = _parse_compiler_output(log, "completed")
    assert out["runtime_success"] is True
    assert out["num_trades"] is None


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


# ----- storage migration: v2.1 columns present --------------------------

def test_v2_1_columns_added_by_migration(tmp_path):
    store = Store(tmp_path / "v2.1.db")
    cols = {r["name"] for r in store.conn.execute("PRAGMA table_info(calls)").fetchall()}
    for c in (
        "rag_call_count", "code_attempt_count",
        "first_pass_compile", "first_pass_runtime", "first_pass_trade",
        "first_pass_schema", "first_pass_judge",
    ):
        assert c in cols, f"missing v2.1 column: {c}"
