"""Unit tests for runner. Uses a fake invoker — no real Docker required."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from lean_backtest_tool import runner, spec_constants
from lean_backtest_tool.exceptions import DockerUnavailable, TimeoutKilled
from lean_backtest_tool.runner import DockerInvocation


def make_fake_invoker(
    log_content: str = "2024-03-14 12:00:00 Algorithm:: hi\n",
    results_payload: dict | None = None,
    raise_exc: Exception | None = None,
) -> Callable[[DockerInvocation], int]:
    """Build a fake invoker that writes canned log + results into the project."""
    def _fake(inv: DockerInvocation) -> int:
        if raise_exc is not None:
            raise raise_exc
        inv.log_sink.parent.mkdir(parents=True, exist_ok=True)
        inv.log_sink.write_text(log_content, encoding="utf-8")
        out_dir = inv.project_dir / "backtests" / "run"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "abc-log.txt").write_text(log_content, encoding="utf-8")
        if results_payload is not None:
            (out_dir / "abc.json").write_text(json.dumps(results_payload), encoding="utf-8")
        return 0
    return _fake


def test_creates_fresh_project_dir(tmp_workdir: Path):
    runner.set_invoker(make_fake_invoker())
    code = "print('hi')\n"
    project_dir, out = runner.run_backtest(
        code=code,
        language="python",
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )
    assert project_dir.exists()
    assert project_dir.name.startswith(spec_constants.PROJECT_DIR_PREFIX)
    # Cleanup is the caller's job — runner left it for us.
    runner.cleanup_project_dir(project_dir)
    assert not project_dir.exists()


def test_writes_python_source(tmp_workdir: Path):
    runner.set_invoker(make_fake_invoker())
    project_dir, _ = runner.run_backtest(
        code="print('x')\n",
        language="python",
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )
    assert (project_dir / "main.py").exists()
    assert (project_dir / "main.py").read_text(encoding="utf-8") == "print('x')\n"
    assert not (project_dir / "Main.cs").exists()
    runner.cleanup_project_dir(project_dir)


def test_writes_csharp_source_and_csproj(tmp_workdir: Path):
    runner.set_invoker(make_fake_invoker())
    project_dir, _ = runner.run_backtest(
        code="// minimal cs\n",
        language="csharp",
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )
    assert (project_dir / "Main.cs").exists()
    assert (project_dir / "QuantConnect.Algorithm.csproj").exists()
    runner.cleanup_project_dir(project_dir)


def test_writes_lean_config(tmp_workdir: Path):
    runner.set_invoker(make_fake_invoker())
    project_dir, _ = runner.run_backtest(
        code="print('x')\n",
        language="python",
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )
    cfg_path = project_dir / "config.json"
    assert cfg_path.exists()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["algorithm-language"] == "Python"
    assert cfg["algorithm-location"] == "/LeanCLI/main.py"
    runner.cleanup_project_dir(project_dir)


def test_locates_output_dir(tmp_workdir: Path):
    runner.set_invoker(make_fake_invoker(results_payload={"totalOrders": 2}))
    project_dir, out = runner.run_backtest(
        code="print('hi')\n",
        language="python",
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )
    assert out.exit_status == "completed"
    assert out.output_dir is not None
    assert (out.output_dir / "abc.json").exists()
    runner.cleanup_project_dir(project_dir)


def test_timeout_returns_partial_log(tmp_workdir: Path):
    """When the invoker raises TimeoutKilled, the runner surfaces the partial
    log (whatever was written to log_sink before the kill)."""
    partial = "2024-03-14 12:00:00 Algorithm:: first bar\n"

    def fake(inv: DockerInvocation) -> int:
        inv.log_sink.parent.mkdir(parents=True, exist_ok=True)
        inv.log_sink.write_text(partial, encoding="utf-8")
        raise TimeoutKilled("simulated")

    runner.set_invoker(fake)
    project_dir, out = runner.run_backtest(
        code="while True: pass\n",
        language="python",
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )
    assert out.exit_status == "timeout"
    assert "first bar" in out.raw_log
    runner.cleanup_project_dir(project_dir)


def test_docker_unavailable(tmp_workdir: Path):
    runner.set_invoker(make_fake_invoker(raise_exc=DockerUnavailable("no daemon")))
    project_dir, out = runner.run_backtest(
        code="print('x')\n",
        language="python",
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )
    assert out.exit_status == "docker_error"
    assert out.raw_log == ""
    runner.cleanup_project_dir(project_dir)


def test_blows_away_existing_dir(tmp_workdir: Path):
    """If a prior incomplete run left a project dir with the same hash,
    the runner clears it and creates fresh."""
    code = "print('same_code')\n"
    # Pre-create a stale project dir at the expected path.
    import hashlib
    h = hashlib.sha256(code.encode()).hexdigest()[: spec_constants.PROJECT_DIR_HASH_LEN]
    stale = tmp_workdir / f"{spec_constants.PROJECT_DIR_PREFIX}{h}"
    stale.mkdir()
    (stale / "stale_marker.txt").write_text("stale", encoding="utf-8")

    runner.set_invoker(make_fake_invoker())
    project_dir, _ = runner.run_backtest(
        code=code,
        language="python",
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )
    assert project_dir == stale
    assert not (project_dir / "stale_marker.txt").exists()
    runner.cleanup_project_dir(project_dir)


def test_invoker_swap_and_reset(tmp_workdir: Path):
    """set_invoker / reset_invoker swap the module-level invoker correctly."""
    sentinel = make_fake_invoker(log_content="SENTINEL\n")
    runner.set_invoker(sentinel)
    assert runner._invoker is sentinel
    runner.reset_invoker()
    assert runner._invoker is runner._default_invoker


def test_invalid_language_raises():
    with pytest.raises(ValueError):
        from lean_backtest_tool.runner import _write_sources
        # Use an empty Path; the function should fail on language check first.
        _write_sources(Path("/tmp/whatever"), "code", "rust", None)
