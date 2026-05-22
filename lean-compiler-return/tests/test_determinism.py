"""Determinism tests. Two runs of the same input must produce byte-identical
output through the full pipeline.

Two flavors:
  - Default suite (no Docker): runs against a fake invoker that injects a
    realistic LEAN-shaped log with various nondeterministic tokens. This
    catches regressions in the filter / stripping logic.
  - @pytest.mark.requires_docker variant: runs the real LEAN container twice
    on the same fixture and asserts byte-identical RunResult.output. This is
    the variant the spec gates 'done' on.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from lean_backtest_tool import RunConfig, run, runner
from lean_backtest_tool.runner import DockerInvocation


def _stochastic_log(_seed: int) -> str:
    """Produce a LEAN-shaped log with varying nondeterministic tokens.

    Different timestamps, hex addresses, UUIDs, and run-dir names every call,
    but identical *content*. After determinism stripping the two logs must
    match byte-for-byte.
    """
    rng = random.Random(_seed)

    def ts() -> str:
        return f"2024-03-14 12:00:{rng.randint(0,59):02d}.{rng.randint(0,999):03d}"

    def addr() -> str:
        return f"0x{rng.randrange(0x100000000000):012x}"

    def uuid_() -> str:
        h = [f"{rng.randrange(0x10000):04x}" for _ in range(8)]
        return f"{h[0]}{h[1]}-{h[2]}-{h[3]}-{h[4]}-{h[5]}{h[6]}{h[7]}"

    def rundir() -> str:
        return f"2025-01-15_12-{rng.randint(0,59):02d}-{rng.randint(0,59):02d}"

    return "\n".join([
        f"{ts()} TRACE:: Loading LEAN engine at {addr()}",
        f"{ts()} TRACE:: Composer.LoadAssemblies()",
        f"{ts()} Algorithm:: Initializing BacktestAlgorithm",
        f"{ts()} Algorithm:: Added equity SPY at Resolution.Daily",
        f"{ts()} DEBUG:: First bar received for SPY",
        f"{ts()} DEBUG:: Portfolio value: 100050.00",
        f"{ts()} Algorithm:: Backtest complete; 1 order placed",
        f"{ts()} STATISTICS:: Sharpe Ratio: 1.23",
        f"{ts()} TRACE:: ResultHandler.Exit() flushing run {uuid_()}",
        f"{ts()} Log:: writing to backtests/{rundir()}/",
    ]) + "\n"


def _invoker_with_stochastic_log(seed: int):
    log = _stochastic_log(seed)

    def fake(inv: DockerInvocation) -> int:
        inv.log_sink.parent.mkdir(parents=True, exist_ok=True)
        inv.log_sink.write_text(log, encoding="utf-8")
        out_dir = inv.project_dir / "backtests" / "run"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "abc-log.txt").write_text(log, encoding="utf-8")
        (out_dir / "abc.json").write_text('{"totalOrders": 1}', encoding="utf-8")
        return 0
    return fake


@pytest.mark.parametrize("language", ["python", "csharp"])
def test_byte_identical_across_runs(language: str, tmp_workdir: Path):
    """The same code -> the same output, across runs whose nondeterministic
    tokens (timestamps, hex addrs, UUIDs, rundirs) differ pairwise."""
    cfg = RunConfig(
        workdir=str(tmp_workdir),
        lean_data_dir=str(tmp_workdir),
        docker_image="fake",
    )
    code = ("print('hello')\n" if language == "python"
            else "// hello\n")

    outputs = []
    for seed in (1, 2, 3, 4, 5):
        runner.set_invoker(_invoker_with_stochastic_log(seed))
        outputs.append(run(code, language, cfg).output)

    assert all(o == outputs[0] for o in outputs[1:]), (
        "Outputs diverged across runs — a nondeterministic token slipped past "
        "the stripping regex set. Diffs:\n" +
        "\n---\n".join(o[:500] for o in outputs)
    )


@pytest.mark.requires_docker
@pytest.mark.parametrize("fixture_name,language", [
    ("compiles_no_trades.py", "python"),
    ("Main_CompilesNoTrades.cs", "csharp"),
])
def test_byte_identical_real_lean(fixture_name: str, language: str, tmp_workdir: Path):
    """Real LEAN, real Docker, twice. Must produce byte-identical output.

    This is the test the spec gates 'done' on. Requires the pinned LEAN image
    pulled and the data directory configured. See findings.md and README.
    """
    from tests.conftest import PY_FIXTURES, CS_FIXTURES
    fixtures_dir = PY_FIXTURES if language == "python" else CS_FIXTURES
    code = (fixtures_dir / fixture_name).read_text(encoding="utf-8")

    import os
    data_dir = os.environ.get("LEAN_DATA_DIR", "")
    # Empty/unset data_dir is allowed: the runner skips the /Lean/Data mount
    # and uses the image's bundled data folder (documented in
    # runner.DockerInvocation). Set LEAN_DATA_DIR="" explicitly in CI to opt
    # into the bundled-data path; set it to a real directory for the
    # production data layout.
    if data_dir and not Path(data_dir).is_dir():
        pytest.skip("LEAN_DATA_DIR is set but not a directory")
    image = os.environ.get("LEAN_DOCKER_IMAGE", "quantconnect/lean:latest")
    os.environ.setdefault("MSYS_NO_PATHCONV", "1")

    cfg = RunConfig(
        workdir=str(tmp_workdir),
        lean_data_dir=data_dir,
        docker_image=image,
    )
    runner.reset_invoker()

    a = run(code, language, cfg).output
    b = run(code, language, cfg).output
    assert a == b, "Real-LEAN outputs differ across runs"
