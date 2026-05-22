"""Pytest config — shared fixtures and the docker-required marker.

Most tests run without Docker. Tests that need real Docker / pinned LEAN
image are marked `@pytest.mark.requires_docker` and skipped by default; run
them with `pytest -m requires_docker`.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
PY_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "python"
CS_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "csharp"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_docker: test requires real Docker + pinned LEAN image",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # If user didn't ask for requires_docker explicitly, skip those tests so
    # the default `pytest` invocation is fast and offline.
    if config.getoption("-m") and "requires_docker" in config.getoption("-m"):
        return
    skip = pytest.mark.skip(reason="needs Docker; run with `pytest -m requires_docker`")
    for item in items:
        if "requires_docker" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def tmp_workdir(tmp_path: Path) -> Path:
    d = tmp_path / "wd"
    d.mkdir()
    return d


@pytest.fixture
def python_fixture():
    def _read(name: str) -> str:
        return (PY_FIXTURES / name).read_text(encoding="utf-8")
    return _read


@pytest.fixture
def csharp_fixture():
    def _read(name: str) -> str:
        return (CS_FIXTURES / name).read_text(encoding="utf-8")
    return _read


@pytest.fixture(autouse=True)
def reset_runner_invoker():
    """Make sure each test starts with the default Docker invoker.

    Tests that swap it (mock invoker, etc.) should still pass after running
    in any order.
    """
    from lean_backtest_tool import runner
    runner.reset_invoker()
    yield
    runner.reset_invoker()
