"""LEAN-Bench v2.0 condition surface — replaces the v1.0 A1 scope tests.

The v1.0 build had a single A1_agentic_full condition with a v1.0 scope note
because per-turn LEAN feedback wasn't yet wired. v2.0 implements the
proposal-faithful 2x2 factorial: C2 (docs), C3 (compiler feedback), C4 (both),
plus the C1 baseline. These tests lock the proposal-faithful surface.
"""

from __future__ import annotations

from harness.conditions.builder import is_agentic, max_turns_for, tool_names_for
from harness.models import CONDITION_ORDER, CONDITIONS


def test_v2_condition_set_matches_proposal():
    assert CONDITION_ORDER == (
        "C1_oneshot",
        "C2_docs",
        "C3_compiler",
        "C4_docs_compiler",
    )
    for cid in CONDITION_ORDER:
        assert cid in CONDITIONS


def test_baseline_is_single_turn_and_no_tools():
    assert max_turns_for("C1_oneshot") == 1
    assert tool_names_for("C1_oneshot") == []
    assert not is_agentic("C1_oneshot")


def test_agent_conditions_run_24_turns():
    for cid in ("C2_docs", "C3_compiler", "C4_docs_compiler"):
        assert is_agentic(cid), cid
        assert max_turns_for(cid) == 24, cid


def test_factorial_tool_assignment():
    # C2 has docs only; C3 has compiler only; C4 has both.
    assert tool_names_for("C2_docs") == ["qc_docs_retrieve"]
    assert tool_names_for("C3_compiler") == ["lean_backtest"]
    assert set(tool_names_for("C4_docs_compiler")) == {"qc_docs_retrieve", "lean_backtest"}


def test_per_condition_default_attempts_match_proposal():
    # Proposal: N=5 for the single-shot baseline, N=3 for agent conditions.
    from harness.models import default_attempts_for
    assert default_attempts_for("C1_oneshot") == 5
    for cid in ("C2_docs", "C3_compiler", "C4_docs_compiler"):
        assert default_attempts_for(cid) == 3, cid


def test_factor_flags_decompose_correctly():
    assert CONDITIONS["C1_oneshot"]["tool_docs_retrieval"] is False
    assert CONDITIONS["C1_oneshot"]["tool_compiler_feedback"] is False

    assert CONDITIONS["C2_docs"]["tool_docs_retrieval"] is True
    assert CONDITIONS["C2_docs"]["tool_compiler_feedback"] is False

    assert CONDITIONS["C3_compiler"]["tool_docs_retrieval"] is False
    assert CONDITIONS["C3_compiler"]["tool_compiler_feedback"] is True

    assert CONDITIONS["C4_docs_compiler"]["tool_docs_retrieval"] is True
    assert CONDITIONS["C4_docs_compiler"]["tool_compiler_feedback"] is True
