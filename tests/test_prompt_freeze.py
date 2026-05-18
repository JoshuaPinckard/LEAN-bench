"""Unit tests for the canonical prompt-set freezing logic.

Covers spec §1 acceptance: stable ordering, stable hash, timestamps excluded,
adhoc / curator-excluded rows dropped.
"""

from __future__ import annotations

import json

from harness.prompt_freeze import (
    CANONICAL_PROMPT_FIELDS, EXCLUDED_FIELDS, canonicalize, is_eligible, sha256_of,
)


def _make_prompt(prompt_id: str, **overrides) -> dict:
    base = {
        "prompt_id":                "lb-0001",
        "version":                  "1.0.0",
        "original_text":            "buy spy when rsi < 30",
        "reformulated_text":        "Implement: buy SPY when RSI(14) < 30.",
        "source":                   "qc_forum",
        "source_date":              "2023-04-01",
        "is_post_cutoff":           0,
        "strategy_type":            "directional",
        "strategy_complexity":      2,
        "api_complexity":           2,
        "securities_type":          "equity",
        "resolution":               "daily",
        "implementation_type":      "lean_native",
        "indicators":               '["RSI"]',
        "universe_type":            "single_asset",
        "tickers":                  '["SPY"]',
        "start_date":               "2018-01-01",
        "end_date":                 "2022-12-31",
        "cash":                     100000,
        "evaluation_mode":          "trade_required",
        "interpretation_strictness": "unambiguous",
        "implementation_underspecified": 0,
        "leak_audit_status":        "clean",
        "excluded_from_benchmark":  0,
        "created_at":               "2025-09-15T14:22:00Z",  # ignored
        "ai_prepopulated":          1,                       # ignored
    }
    base.update(overrides)
    base["prompt_id"] = prompt_id
    return base


def test_canonicalize_is_stable_under_field_reordering():
    a = _make_prompt("lb-0001")
    b = {k: a[k] for k in reversed(list(a.keys()))}
    assert canonicalize([a]) == canonicalize([b])


def test_canonicalize_is_stable_under_prompt_reordering():
    a = _make_prompt("lb-0001")
    b = _make_prompt("lb-0002")
    assert canonicalize([a, b]) == canonicalize([b, a])


def test_canonicalize_excludes_timestamps_and_telemetry():
    a = _make_prompt("lb-0001")
    a2 = _make_prompt("lb-0001", created_at="2099-12-31T00:00:00Z",
                                 ai_prepopulated=0, curator_modified_fields='["x"]')
    assert canonicalize([a]) == canonicalize([a2])


def test_canonical_field_set_does_not_include_excluded_fields():
    for excluded in EXCLUDED_FIELDS:
        assert excluded not in CANONICAL_PROMPT_FIELDS


def test_hash_round_trips_via_load_frozen(tmp_path):
    prompt = _make_prompt("lb-0001")
    payload = canonicalize([prompt])
    expected = sha256_of(payload)

    out_path = tmp_path / "frozen.json"
    out_path.write_bytes(payload)

    from harness.prompt_freeze import load_frozen
    _, on_disk = load_frozen(out_path)
    assert on_disk == expected


def test_is_eligible_filters_adhoc_and_excluded():
    benchmark = _make_prompt("lb-0001", source="qc_forum", excluded_from_benchmark=0)
    adhoc     = _make_prompt("adhoc-1", source="adhoc")
    curator_excl = _make_prompt("lb-0002", excluded_from_benchmark=1)
    assert is_eligible(benchmark)
    assert not is_eligible(adhoc)
    assert not is_eligible(curator_excl)


def test_canonicalize_drops_ineligible_rows_silently():
    benchmark = _make_prompt("lb-0001")
    adhoc     = _make_prompt("adhoc-1", source="adhoc")
    out = json.loads(canonicalize([benchmark, adhoc]))
    assert out["count"] == 1
    assert out["prompts"][0]["prompt_id"] == "lb-0001"


def test_indicator_decoding_normalizes_strings_and_lists():
    a = _make_prompt("lb-0001", indicators='["RSI", "MACD"]')
    b = _make_prompt("lb-0001", indicators=["RSI", "MACD"])
    assert canonicalize([a]) == canonicalize([b])
