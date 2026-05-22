"""Unit tests for log_filter — pure, no I/O, no Docker.

Tests against synthetic LEAN-shaped log strings. The fixtures here are
hand-written so the test does not depend on real LEAN output; the empirical
phase separately confirms the real-world tag set in findings.md.
"""
from __future__ import annotations

import re

import pytest

from lean_backtest_tool import spec_constants
from lean_backtest_tool.log_filter import filter_log


def test_empty_input_returns_empty():
    assert filter_log("") == ""


def test_dropped_tags_are_removed():
    raw = "\n".join([
        "2024-03-14 12:00:00.123 TRACE:: should be dropped",
        "2024-03-14 12:00:00.456 STATISTICS:: also dropped",
    ])
    assert filter_log(raw) == ""


def test_kept_tags_are_retained():
    raw = "\n".join([
        "2024-03-14 12:00:00.123 ERROR:: bad thing",
        "2024-03-14 12:00:00.456 DEBUG:: telemetry",
        "2024-03-14 12:00:00.789 Algorithm:: started",
    ])
    out = filter_log(raw)
    assert "ERROR:: bad thing" in out
    assert "DEBUG:: telemetry" in out
    assert "Algorithm:: started" in out


def test_continuation_lines_inherit_keep_decision():
    """A stack trace under ERROR:: has untagged continuation lines; they must
    inherit ERROR's keep decision so the stack trace stays together."""
    raw = "\n".join([
        "2024-03-14 12:00:00.123 ERROR:: KeyError: SPY",
        "  at /LeanCLI/main.py:14 in on_data",
        "  at AlgorithmPythonWrapper.OnData",
    ])
    out = filter_log(raw)
    assert "ERROR:: KeyError: SPY" in out
    assert "at /LeanCLI/main.py:14" in out
    assert "AlgorithmPythonWrapper.OnData" in out


def test_continuation_lines_inherit_drop_decision():
    """Continuation under TRACE:: should be dropped along with the header."""
    raw = "\n".join([
        "2024-03-14 12:00:00.123 TRACE:: loading assemblies",
        "  resolved /opt/lean/AlgoFoo.dll",
        "  resolved /opt/lean/AlgoBar.dll",
    ])
    assert filter_log(raw) == ""


def test_kept_then_dropped_then_continuation_inherits_dropped():
    """When the most recent tagged line is dropped, the untagged continuation
    after it inherits 'drop' even if there was an earlier kept line."""
    raw = "\n".join([
        "2024-03-14 12:00:00.123 ERROR:: kept header",
        "  kept continuation",
        "2024-03-14 12:00:00.456 TRACE:: dropped header",
        "  dropped continuation",
    ])
    out = filter_log(raw)
    assert "kept header" in out
    assert "kept continuation" in out
    assert "dropped header" not in out
    assert "dropped continuation" not in out


def test_unknown_tag_defaults_to_keep():
    """Spec §5 EMPIRICAL #1: default keep, false-keep > false-drop."""
    raw = "2024-03-14 12:00:00 NOVEL_TAG:: never seen before"
    out = filter_log(raw)
    assert "NOVEL_TAG:: never seen before" in out


def test_determinism_strips_timestamps():
    raw = "2024-03-14 12:00:00.123 ERROR:: bad thing"
    out = filter_log(raw)
    assert "2024-03-14" not in out
    assert "<TIMESTAMP>" in out


def test_determinism_strips_hex_addresses():
    raw = "2024-03-14 12:00:00 ERROR:: at 0x7f8a1c0042b8 some_method"
    out = filter_log(raw)
    assert "0x7f8a1c0042b8" not in out
    assert "<ADDR>" in out


def test_determinism_strips_uuids():
    raw = "2024-03-14 12:00:00 ERROR:: run id 91d9b3f8-7f2a-4e3d-9c8a-1b2c3d4e5f60"
    out = filter_log(raw)
    assert "91d9b3f8-7f2a-4e3d-9c8a-1b2c3d4e5f60" not in out
    assert "<UUID>" in out


def test_determinism_strips_dir_timestamps():
    raw = "2024-03-14 12:00:00 Log:: writing to backtests/2025-01-15_12-34-56/"
    out = filter_log(raw)
    assert "2025-01-15_12-34-56" not in out
    assert "<RUN_DIR>" in out


def test_filter_is_pure_no_global_state():
    """Two runs of the same input produce byte-identical output."""
    raw = "2024-03-14 12:00:00.123 ERROR:: test\n  continuation\n"
    assert filter_log(raw) == filter_log(raw)


def test_filter_no_tag_pattern_leaks_through():
    """Lines that look like tags but don't end in '::' are content, not tags."""
    raw = "2024-03-14 12:00:00 ERROR:: KeyError on SPY:notatag"
    out = filter_log(raw)
    assert "ERROR:: KeyError" in out


def test_tag_pattern_matches_word_boundary():
    pat = spec_constants.TAG_PATTERN
    assert pat.search(" ERROR::").group(1) == "ERROR"
    assert pat.search("ERROR::").group(1) == "ERROR"
    # No match without the '::'
    assert pat.search("ERROR foo") is None


def test_untagged_prefix_lines_handled():
    raw = "no tag at all\n  also no tag\n"
    # Default policy: keep
    out = filter_log(raw)
    assert "no tag at all" in out
