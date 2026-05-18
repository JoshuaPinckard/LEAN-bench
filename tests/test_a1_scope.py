"""A1 in v1.0 is a compile-loop, not full-stack per-turn LEAN.

Locks the relabeled display name + scope language so the protocol/code
drift the user flagged in their audit cannot silently recur. If a future
change implements per-turn LEAN feedback, these assertions must be updated
in the same commit that flips the behavior (and bumps the benchmark
version per decision log §6).
"""

from __future__ import annotations

from harness.models import CONDITIONS


def test_a1_display_name_says_compile_loop_not_full_stack():
    """Display name must be honest about scope. 'full stack' implied per-turn
    LEAN backtest feedback, which v1.0 does NOT provide."""
    name = CONDITIONS["A1_agentic_full"]["display_name"].lower()
    assert "compile" in name
    assert "full stack" not in name


def test_a1_semantics_disclose_compile_only_feedback():
    """The semantics string must explicitly say what the per-turn signal is,
    so anyone reading CONDITIONS in isolation gets the right picture."""
    sem = CONDITIONS["A1_agentic_full"]["semantics"].lower()
    # Must mention what runs per turn (compile / parse / syntax / ast).
    assert any(tok in sem for tok in ("ast", "compile", "syntax", "parse")), sem
    # Must say LEAN backtest runs once at the end, not per turn.
    assert ("once" in sem and "final" in sem) or "after the loop" in sem, sem


def test_a1_id_is_still_locked():
    """ID stays A1_agentic_full to preserve DB schema continuity. The
    historical name lives on; the human-facing strings are what changed."""
    assert "A1_agentic_full" in CONDITIONS
