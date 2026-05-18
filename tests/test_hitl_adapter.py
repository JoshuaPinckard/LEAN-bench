"""Regression tests for the HITL adapter / failure-mode coercion.

Production bug surfaced by the user audit: human_failure_mode arrives as
a single CSV string (e.g. "wrong_indicator"); the validator iterated over
it as a list, comparing only the first character. Test that the adapter
normalizes strings to single-element lists so the comparison is right.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make scripts/ importable for the adapter under test.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

from scripts.validate_judge import _adapt_export_format  # type: ignore


def test_csv_style_string_failure_mode_becomes_single_element_list():
    item = _adapt_export_format({
        "prompt_record": {"reformulated_text": "x"},
        "generated_code": "x = 1",
        "backtest_result": {},
        "human_score": 0.5,
        "human_failure_mode": "wrong_indicator",
    })
    assert item["human_failure_mode"] == ["wrong_indicator"]


def test_jsonl_style_list_failure_mode_passes_through():
    item = _adapt_export_format({
        "prompt_record": {"reformulated_text": "x"},
        "generated_code": "x = 1",
        "backtest_result": {},
        "human_score": 0.5,
        "human_failure_mode": '["wrong_indicator", "missing_warmup"]',
    })
    assert item["human_failure_mode"] == ["wrong_indicator", "missing_warmup"]


def test_blank_failure_mode_becomes_empty_list():
    for blank in ("", "   ", None):
        item = _adapt_export_format({
            "prompt_record": {"reformulated_text": "x"},
            "generated_code": "x = 1",
            "backtest_result": {},
            "human_score": 0.5,
            "human_failure_mode": blank,
        })
        assert item["human_failure_mode"] == [], f"failed for {blank!r}"


def test_export_format_with_prompt_record_is_preserved():
    """When the exporter writes full prompt_record metadata, validate_judge
    should use it verbatim — not strip it down to reformulated_text only."""
    item = _adapt_export_format({
        "prompt_record": {
            "reformulated_text":         "buy SPY",
            "original_text":             "buy SPY",
            "strategy_type":             "directional",
            "evaluation_mode":           "trade_required",
            "interpretation_strictness": "unambiguous",
            "securities_type":           "equity",
            "tickers":                   '["SPY"]',
        },
        "generated_code": "x = 1",
        "backtest_summary": {"compile_success": True},
        "human_score": 0.7,
        "matches_prompt_intent_human": True,
    })
    pr = item["prompt_record"]
    assert pr["strategy_type"] == "directional"
    assert pr["securities_type"] == "equity"
    assert pr["tickers"] == '["SPY"]'
    # backtest_summary mirrored to backtest_result
    assert item["backtest_result"]["compile_success"] is True
    # matches_prompt_intent_human aliased
    assert item["human_matches_prompt_intent"] is True
