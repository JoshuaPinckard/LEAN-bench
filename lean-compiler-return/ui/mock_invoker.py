"""Mock Docker invoker for the UI's 'no Docker' mode.

Produces canned LEAN-shaped logs so the user can exercise the filter and see
exactly what gets dropped vs kept without spinning up a container. The
canned log is chosen by simple heuristic against the submitted code so the UI
feels responsive to inputs (error-shaped code returns an error-shaped log).

This module is part of the UI, not the package. Removing the `ui/` directory
removes this with no impact on the library.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from lean_backtest_tool.exceptions import TimeoutKilled
from lean_backtest_tool.runner import DockerInvocation


# ---------------------------------------------------------------------------
# Canned LEAN-shaped logs. Each includes a mix of tag categories so the
# filter's keep/drop behavior is visible. Includes nondeterministic-looking
# tokens (timestamps, hex addresses) so the determinism stripping is visible.
# ---------------------------------------------------------------------------

_LOG_NO_TRADES = """\
2024-03-14 12:00:00.123 TRACE:: Loading LEAN engine at 0x7f8a1c0042b8 (123ms)
2024-03-14 12:00:00.234 TRACE:: Composer.LoadAssemblies() resolving plugins
2024-03-14 12:00:00.567 Algorithm:: Initializing BacktestAlgorithm
2024-03-14 12:00:00.589 Log:: SetStartDate 2020-01-06
2024-03-14 12:00:00.612 Log:: SetEndDate 2020-01-10
2024-03-14 12:00:00.634 Log:: SetCash 100000
2024-03-14 12:00:00.711 Algorithm:: Added equity SPY at Resolution.Daily
2024-03-14 12:00:01.245 TRACE:: SubscriptionDataReader created for SPY hashed=a3f12c7e8b9d4e0f1a2b3c4d5e6f7a8b
2024-03-14 12:00:01.456 DEBUG:: Algorithm warm-up complete; no warmup window
2024-03-14 12:00:03.788 STATISTICS:: Total Trades: 0
2024-03-14 12:00:03.812 STATISTICS:: Average Win: 0%
2024-03-14 12:00:03.834 STATISTICS:: Average Loss: 0%
2024-03-14 12:00:03.856 STATISTICS:: Compounding Annual Return: 0%
2024-03-14 12:00:03.945 Algorithm:: Backtest complete; 0 orders placed
2024-03-14 12:00:04.001 TRACE:: ResultHandler.Exit() flushing 91d9b3f8-7f2a-4e3d-9c8a-1b2c3d4e5f60
"""

_LOG_WITH_TRADES = """\
2024-03-14 12:00:00.123 TRACE:: Loading LEAN engine at 0x7f8a1c0042b8 (97ms)
2024-03-14 12:00:00.234 TRACE:: Composer.LoadAssemblies() resolving plugins
2024-03-14 12:00:00.567 Algorithm:: Initializing BacktestAlgorithm
2024-03-14 12:00:00.711 Algorithm:: Added equity SPY at Resolution.Daily
2024-03-14 12:00:01.245 DEBUG:: First bar received for SPY
2024-03-14 12:00:01.298 Algorithm:: SetHoldings(SPY, 1.0)
2024-03-14 12:00:01.341 Log:: Order submitted: market buy 320 shares SPY @ 320.45
2024-03-14 12:00:01.402 Log:: Order filled: 320 SPY @ 320.45
2024-03-14 12:00:02.011 DEBUG:: Portfolio value: 100050.00
2024-03-14 12:00:03.788 STATISTICS:: Total Trades: 1
2024-03-14 12:00:03.812 STATISTICS:: Sharpe Ratio: 1.23
2024-03-14 12:00:03.945 Algorithm:: Backtest complete; 1 order placed
2024-03-14 12:00:04.001 TRACE:: ResultHandler.Exit() flushing run 91d9b3f8-7f2a-4e3d-9c8a-1b2c3d4e5f60
"""

_LOG_RUNTIME_ERROR = """\
2024-03-14 12:00:00.123 TRACE:: Loading LEAN engine at 0x7f8a1c0042b8 (108ms)
2024-03-14 12:00:00.567 Algorithm:: Initializing BacktestAlgorithm
2024-03-14 12:00:00.711 Algorithm:: Added equity SPY at Resolution.Daily
2024-03-14 12:00:01.245 DEBUG:: First bar received for SPY
2024-03-14 12:00:01.412 ERROR:: Algorithm.OnData() RuntimeError: division by zero
  at /LeanCLI/main.py:14 in on_data
  at Python.Runtime.PythonEngine.RuntimeImport (0x00007fab1c0034a0)
  at QuantConnect.Algorithm.AlgorithmPythonWrapper.OnData
2024-03-14 12:00:01.498 ERROR:: Backtest aborted due to algorithm exception
2024-03-14 12:00:01.521 TRACE:: ResultHandler.Exit() flushing run 8a1c0042-b8f7-2a4e-3d9c-8a1b2c3d4e5f
"""

_LOG_INITIALIZE_ERROR = """\
2024-03-14 12:00:00.123 TRACE:: Loading LEAN engine at 0x7f8a1c0042b8
2024-03-14 12:00:00.567 Algorithm:: Initializing BacktestAlgorithm
2024-03-14 12:00:00.722 ERROR:: Algorithm.Initialize() ValueError: intentional initialize() failure for fixture
  at /LeanCLI/main.py:11 in initialize
2024-03-14 12:00:00.789 ERROR:: Algorithm initialization failed; aborting backtest
2024-03-14 12:00:00.812 TRACE:: ResultHandler.Exit() flushing run 91d9b3f8-7f2a-4e3d-9c8a-1b2c3d4e5f60
"""

_LOG_IMPORT_ERROR = """\
2024-03-14 12:00:00.123 TRACE:: Loading LEAN engine at 0x7f8a1c0042b8
2024-03-14 12:00:00.244 ERROR:: ModuleNotFoundError: No module named 'nonexistent_module'
  at /LeanCLI/main.py:2 in <module>
  at Python.Runtime.PythonEngine.ImportModule
2024-03-14 12:00:00.301 ERROR:: Algorithm import failed; aborting before initialization
2024-03-14 12:00:00.412 TRACE:: ResultHandler.Exit() flushing run 91d9b3f8-7f2a-4e3d-9c8a-1b2c3d4e5f60
"""

_LOG_COMPILE_ERROR = """\
2024-03-14 12:00:00.123 TRACE:: Loading LEAN engine at 0x7f8a1c0042b8
2024-03-14 12:00:00.456 TRACE:: Compiling C# algorithm from /LeanCLI/Main.cs
2024-03-14 12:00:01.234 ERROR:: Compilation failed: Main.cs(8,17): error CS0246: The type or namespace name 'undefined_type' could not be found (are you missing a using directive or an assembly reference?)
2024-03-14 12:00:01.301 ERROR:: Build FAILED. 1 Error(s).
2024-03-14 12:00:01.412 ERROR:: Algorithm assembly not produced; aborting
2024-03-14 12:00:01.501 TRACE:: ResultHandler.Exit() flushing run 91d9b3f8-7f2a-4e3d-9c8a-1b2c3d4e5f60
"""

_LOG_TIMEOUT_PARTIAL = """\
2024-03-14 12:00:00.123 TRACE:: Loading LEAN engine at 0x7f8a1c0042b8 (102ms)
2024-03-14 12:00:00.567 Algorithm:: Initializing BacktestAlgorithm
2024-03-14 12:00:00.711 Algorithm:: Added equity SPY at Resolution.Daily
2024-03-14 12:00:01.245 DEBUG:: First bar received for SPY
2024-03-14 12:00:01.301 DEBUG:: Entered on_data() at bar 1
"""


_FAKE_RESULTS_NO_TRADES = {
    "totalOrders": 0,
    "statistics": {"Total Trades": "0", "Total Orders": "0"},
    "orders": {},
}

_FAKE_RESULTS_WITH_TRADES = {
    "totalOrders": 1,
    "statistics": {"Total Trades": "1", "Total Orders": "1"},
    "orders": {"0": {"Id": 0, "Symbol": "SPY", "Quantity": 320}},
}


def _pick_log_and_results(code: str) -> tuple[str, dict | None, str]:
    """Pick canned (log, results, exit_status_hint) from heuristics on code.

    Hints let the mock surface different shapes (timeout, infra error, etc.)
    so the user can see the trailer logic and tag-set behavior. The hint maps
    to runner.RunnerOutput.exit_status, but the mock_invoker only controls
    the docker exit_code — the runner derives status from artifacts. See
    `MockInvoker.__call__`.
    """
    lc = code.lower()
    if "while true" in lc or "while (true)" in lc or "while(true)" in lc:
        return _LOG_TIMEOUT_PARTIAL, None, "timeout"
    if "from nonexistent_module" in lc or "modulenotfounderror" in lc:
        return _LOG_IMPORT_ERROR, None, "completed_with_error"
    if "undefined_type" in lc or "error cs0246" in lc:
        return _LOG_COMPILE_ERROR, None, "completed_with_error"
    if "raise valueerror" in lc and "initialize" in lc:
        return _LOG_INITIALIZE_ERROR, None, "completed_with_error"
    if "throw new invalidoperationexception" in lc and "initialize" in lc:
        return _LOG_INITIALIZE_ERROR, None, "completed_with_error"
    if "1 / 0" in lc or "1/0" in lc or "_bars_seen >= 2" in lc or "_bars >= 2" in lc:
        return _LOG_RUNTIME_ERROR, None, "completed_with_error"
    if "set_holdings" in lc or "setholdings" in lc:
        return _LOG_WITH_TRADES, _FAKE_RESULTS_WITH_TRADES, "completed"
    return _LOG_NO_TRADES, _FAKE_RESULTS_NO_TRADES, "completed"


class MockInvoker:
    """Replacement for `runner._default_invoker` in mock mode.

    Writes a canned LEAN-shaped log to `inv.log_sink`, fabricates a fake
    backtest output directory with a `<id>-log.txt` and a results JSON so
    that artifact_reader / runner can locate them normally. Returns 0.
    """

    def __init__(self, simulate_seconds: float = 0.3):
        self.simulate_seconds = simulate_seconds

    def __call__(self, inv: DockerInvocation) -> int:
        # Recover the original code from the project dir so the heuristic can
        # see it. main.py for Python, Main.cs for C#.
        code = self._read_source(inv.project_dir)
        log, results, hint = _pick_log_and_results(code)

        # Container stdout sink (used as fallback if output dir is missing).
        inv.log_sink.parent.mkdir(parents=True, exist_ok=True)
        inv.log_sink.write_text(log, encoding="utf-8")

        # Fabricate a normal backtest output directory.
        backtests = inv.project_dir / "backtests"
        backtests.mkdir(exist_ok=True)
        bt_id = "mock-run"
        out_dir = backtests / "mock-output"
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"{bt_id}-log.txt").write_text(log, encoding="utf-8")
        if results is not None:
            (out_dir / f"{bt_id}.json").write_text(json.dumps(results), encoding="utf-8")

        time.sleep(self.simulate_seconds)

        # Simulate a timeout when the canned log matches an infinite-loop
        # fixture so the timeout trailer path is exercisable from the UI.
        if hint == "timeout":
            raise TimeoutKilled("mock: simulated timeout for while-True fixture")

        # In the real path, exit code 0 means the container finished; the
        # 'completed' vs 'infra_error' decision is downstream from artifacts.
        # The artifacts above are well-formed for everything except `timeout`.
        return 0

    @staticmethod
    def _read_source(project_dir: Path) -> str:
        for name in ("main.py", "Main.cs"):
            p = project_dir / name
            if p.exists():
                try:
                    return p.read_text(encoding="utf-8")
                except OSError:
                    return ""
        return ""
