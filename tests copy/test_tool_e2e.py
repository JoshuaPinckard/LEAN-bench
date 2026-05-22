"""End-to-end through `run()` using fake invokers (no real Docker required).

The real-Docker E2E suite lives behind @pytest.mark.requires_docker and runs
against actual LEAN; this file exercises the contract surface — trailer
ordering, token cap, exit_status mapping, project-dir cleanup.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lean_backtest_tool import RunConfig, run, runner, spec_constants
from lean_backtest_tool.exceptions import DockerUnavailable, TimeoutKilled
from lean_backtest_tool.runner import DockerInvocation


def _make_log_invoker(log: str, results: dict | None = None):
    def _fake(inv: DockerInvocation) -> int:
        inv.log_sink.parent.mkdir(parents=True, exist_ok=True)
        inv.log_sink.write_text(log, encoding="utf-8")
        out_dir = inv.project_dir / "backtests" / "run"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "abc-log.txt").write_text(log, encoding="utf-8")
        if results is not None:
            (out_dir / "abc.json").write_text(json.dumps(results), encoding="utf-8")
        return 0
    return _fake


@pytest.fixture
def cfg(tmp_workdir: Path) -> RunConfig:
    return RunConfig(
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )


def test_completed_appends_orders_and_marker(cfg):
    log = "2024-03-14 12:00:00 Algorithm:: hi\n"
    runner.set_invoker(_make_log_invoker(log, {"totalOrders": 3}))
    result = run("print('x')\n", "python", cfg)
    assert result.exit_status == "completed"
    assert "ORDERS_PLACED: 3" in result.output
    assert result.output.rstrip().endswith("LEAN_RUN_FINISHED")


def test_completed_unknown_orders_when_no_json(cfg):
    log = "2024-03-14 12:00:00 Algorithm:: hi\n"
    runner.set_invoker(_make_log_invoker(log, results=None))
    result = run("print('x')\n", "python", cfg)
    assert result.exit_status == "completed"
    assert "ORDERS_PLACED: unknown" in result.output


def test_timeout_appends_timeout_marker(cfg):
    def fake(inv: DockerInvocation) -> int:
        inv.log_sink.parent.mkdir(parents=True, exist_ok=True)
        inv.log_sink.write_text("2024-03-14 12:00:00 Algorithm:: first bar\n", encoding="utf-8")
        raise TimeoutKilled("simulated")
    runner.set_invoker(fake)
    result = run("while True: pass\n", "python", cfg)
    assert result.exit_status == "timeout"
    assert "TIMEOUT_EXCEEDED: backtest killed after 900s" in result.output


def test_docker_unavailable_returns_infra_trailer(cfg):
    def fake(inv: DockerInvocation) -> int:
        raise DockerUnavailable("daemon offline")
    runner.set_invoker(fake)
    result = run("print('x')\n", "python", cfg)
    assert result.exit_status == "docker_error"
    assert "INFRASTRUCTURE_ERROR" in result.output


def test_project_dir_cleaned_up_after_run(cfg):
    """After run() returns, the per-run project dir must not exist (D8)."""
    runner.set_invoker(_make_log_invoker("2024-03-14 12:00:00 Algorithm:: hi\n"))
    code = "print('cleanup_check')\n"
    result = run(code, "python", cfg)
    assert result.exit_status == "completed"

    # Compute the deterministic project dir name and check it's gone.
    import hashlib
    h = hashlib.sha256(code.encode()).hexdigest()[: spec_constants.PROJECT_DIR_HASH_LEN]
    expected = Path(cfg.workdir) / f"{spec_constants.PROJECT_DIR_PREFIX}{h}"
    assert not expected.exists()


def test_project_dir_cleaned_up_after_exception(cfg):
    """Cleanup happens even when the runner raises something unexpected."""
    code = "print('cleanup_on_failure')\n"

    def fake(inv: DockerInvocation) -> int:
        raise RuntimeError("unexpected boom")

    runner.set_invoker(fake)
    with pytest.raises(RuntimeError):
        run(code, "python", cfg)

    import hashlib
    h = hashlib.sha256(code.encode()).hexdigest()[: spec_constants.PROJECT_DIR_HASH_LEN]
    expected = Path(cfg.workdir) / f"{spec_constants.PROJECT_DIR_PREFIX}{h}"
    assert not expected.exists()


def test_compile_failure_path_becomes_completed(cfg):
    """EMPIRICAL #2 outcome: invoker ran, container produced log content
    (e.g. C# dotnet build error), but no LEAN output dir exists. The runner
    must treat this as 'completed' (user code issue, not infra) so the
    trailer reads LEAN_RUN_FINISHED rather than INFRASTRUCTURE_ERROR.
    """
    def fake(inv: DockerInvocation) -> int:
        inv.log_sink.parent.mkdir(parents=True, exist_ok=True)
        inv.log_sink.write_text(
            "Build FAILED.\n"
            "/LeanCLI/Main.cs(9,17): error CS0246: 'undefined_type' not found\n"
            "1 Error(s)\n",
            encoding="utf-8",
        )
        # NOTE: no backtests/ dir created — LEAN never ran.
        return 1
    runner.set_invoker(fake)
    result = run("// cs", "csharp", cfg)
    assert result.exit_status == "completed"
    assert "error CS0246" in result.output
    assert result.output.rstrip().endswith("LEAN_RUN_FINISHED")
    assert "INFRASTRUCTURE_ERROR" not in result.output


def test_genuine_empty_output_is_infra_error(cfg):
    """Runner returns infra_error ONLY when there's no LEAN output dir AND
    no captured raw_log — i.e., the container produced nothing usable."""
    def fake(inv: DockerInvocation) -> int:
        # No log_sink write, no backtests/ — total silence.
        return 0
    runner.set_invoker(fake)
    result = run("print('x')\n", "python", cfg)
    assert result.exit_status == "infra_error"
    assert "INFRASTRUCTURE_ERROR" in result.output


def test_token_cap_truncates_long_logs(cfg):
    # Build a log that's clearly over 4000 tokens.
    big_chunk = "2024-03-14 12:00:00 Algorithm:: " + ("blah " * 50) + "\n"
    big_log = big_chunk * 500  # ~25k tokens probably
    runner.set_invoker(_make_log_invoker(big_log, {"totalOrders": 0}))

    result = run("print('big')\n", "python", cfg)
    import tiktoken
    enc = tiktoken.get_encoding(spec_constants.TOKEN_ENCODING)
    tokens = enc.encode(result.output)
    assert len(tokens) <= spec_constants.TOKEN_CAP
    assert result.output.startswith(spec_constants.TRUNCATION_MARKER)


def test_invalid_language_rejected(cfg):
    with pytest.raises(ValueError):
        run("code", "rust", cfg)
