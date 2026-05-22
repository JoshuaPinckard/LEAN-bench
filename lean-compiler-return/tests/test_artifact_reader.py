"""Unit tests for artifact_reader — synthetic JSON, no I/O on real artifacts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lean_backtest_tool.artifact_reader import read_orders


def _write(dir_: Path, name: str, payload) -> Path:
    p = dir_ / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_missing_directory(tmp_path: Path):
    assert read_orders(tmp_path / "does_not_exist") is None


def test_empty_directory(tmp_path: Path):
    assert read_orders(tmp_path) is None


def test_total_orders_field_top_level(tmp_path: Path):
    _write(tmp_path, "results.json", {"totalOrders": 7})
    assert read_orders(tmp_path) == 7


def test_total_orders_capitalized(tmp_path: Path):
    _write(tmp_path, "results.json", {"TotalOrders": 5})
    assert read_orders(tmp_path) == 5


def test_statistics_total_orders(tmp_path: Path):
    _write(tmp_path, "results.json", {"statistics": {"Total Orders": "3"}})
    assert read_orders(tmp_path) == 3


def test_orders_array_count(tmp_path: Path):
    payload = {"orders": [{"id": 1}, {"id": 2}, {"id": 3}]}
    _write(tmp_path, "results.json", payload)
    assert read_orders(tmp_path) == 3


def test_orders_dict_count(tmp_path: Path):
    payload = {"orders": {"0": {}, "1": {}}}
    _write(tmp_path, "results.json", payload)
    assert read_orders(tmp_path) == 2


def test_malformed_json_returns_none(tmp_path: Path):
    (tmp_path / "results.json").write_text("not valid json {", encoding="utf-8")
    assert read_orders(tmp_path) is None


def test_skips_order_events_file(tmp_path: Path):
    """The '-order-events.json' file is NOT the main results."""
    _write(tmp_path, "abc-order-events.json", {"totalOrders": 999})
    assert read_orders(tmp_path) is None


def test_skips_summary_file(tmp_path: Path):
    _write(tmp_path, "abc-summary.json", {"totalOrders": 999})
    assert read_orders(tmp_path) is None


def test_picks_main_results_when_multiple_jsons(tmp_path: Path):
    _write(tmp_path, "abc-order-events.json", {"totalOrders": 999})
    _write(tmp_path, "abc.json", {"totalOrders": 42})
    assert read_orders(tmp_path) == 42


def test_unrecognized_schema_returns_none(tmp_path: Path):
    _write(tmp_path, "results.json", {"some_other_field": True})
    assert read_orders(tmp_path) is None
