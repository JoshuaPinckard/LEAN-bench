"""LEAN backtest executor.

Pipeline stage between code generation and judging:
  1. Write generated code to a temporary project directory (main.py + config.json)
  2. Run `lean backtest <project>` via subprocess
  3. Parse the results JSON QC LEAN writes under <project>/backtests/<run>/
  4. Persist outcomes to the calls row via Store.update_call_with_backtest
  5. Return the same result dict so the judge stage can score against it

If the LEAN CLI is not installed on PATH (or LEAN_BIN), the executor returns a
"skipped" result with a clear runtime_error message and still writes it so the
call row reflects that the backtest never ran. The orchestrator continues with
the judge stage, which can score on code structure alone.

Timeouts: a backtest exceeding `timeout_s` is killed and recorded as a
runtime_error timeout — the judge stage still runs.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from harness.storage import Store

DEFAULT_BACKTEST_TIMEOUT_S = 120

# Minimal LEAN project config. LEAN reads this from the project root.
PROJECT_TEMPLATE_CONFIG: dict[str, Any] = {
    "algorithm-language": "Python",
    "parameters": {},
    "description": "leanbench autogen",
}


def _find_lean_workspace() -> Path:
    """Locate the LEAN workspace (directory containing `lean.json` + `data/`).

    Honors $LEAN_WORKSPACE; falls back to <repo_root>/lean_workspace. The
    CLI discovers data paths and credentials from the workspace `lean.json`,
    so the backtest subprocess runs with its cwd set here AND generated
    projects are materialized inside the workspace as subdirectories.
    """
    override = os.environ.get("LEAN_WORKSPACE")
    if override:
        return Path(override).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "lean_workspace").resolve()


LEAN_WORKSPACE = _find_lean_workspace()


# Placeholder org-id written into lean.json when the user ran `lean init` without
# logging in (the modern CLI refuses to run backtests against an "old root
# folder", i.e. a workspace lean.json with no job-organization-id). Local
# backtests against the local data folder don't actually authenticate, so any
# non-empty string satisfies the check.
_LEANBENCH_PLACEHOLDER_ORG_ID = "leanbench-local"


_ORG_KEY_RE = re.compile(
    r'^\s*"(?:job-organization-id|organization-id)"\s*:', re.MULTILINE
)


def _ensure_workspace_initialized() -> str | None:
    """Patch the workspace lean.json with a placeholder organization id if it
    lacks one. Returns None on success, or an error message on failure.

    Idempotent: a no-op once `job-organization-id` is present (the CLI's
    OrganizationManager accepts either `job-organization-id` or the legacy
    `organization-id`). We use a regex check rather than a JSON parse because
    QC's lean.json ships with `//` comments — including ones inside string
    values like URLs — which standard json.loads rejects."""
    lean_json = LEAN_WORKSPACE / "lean.json"
    try:
        raw = lean_json.read_text(encoding="utf-8")
    except OSError as exc:
        return f"could not read {lean_json}: {exc}"

    if _ORG_KEY_RE.search(raw):
        return None  # Already initialized.

    if not raw.lstrip().startswith("{"):
        return f"unexpected lean.json layout at {lean_json}"
    idx = raw.index("{") + 1
    insertion = f'\n  "job-organization-id": "{_LEANBENCH_PLACEHOLDER_ORG_ID}",\n'
    patched = raw[:idx] + insertion + raw[idx:]
    try:
        lean_json.write_text(patched, encoding="utf-8")
    except OSError as exc:
        return f"could not write {lean_json}: {exc}"
    return None

# Fields written to the calls row when no backtest is produced.
_RESULT_KEYS = (
    "compile_success", "runtime_success", "runtime_error", "lean_results_json",
    "total_return_pct", "sharpe_ratio", "max_drawdown_pct",
    "num_trades", "win_rate", "final_portfolio_value", "benchmark_return_pct",
)


# ---- LEAN CLI discovery -------------------------------------------------

def _find_lean_bin() -> str | None:
    """Locate the LEAN CLI binary. Honors $LEAN_BIN; then checks the active
    venv's Scripts dir (so subprocesses find it even when PATH omits the venv);
    falls back to PATH."""
    import sys
    override = os.environ.get("LEAN_BIN")
    if override:
        return shutil.which(override) or (override if Path(override).is_file() else None)
    scripts_dir = Path(sys.executable).parent
    for name in ("lean", "lean.exe"):
        candidate = scripts_dir / name
        if candidate.is_file():
            return str(candidate)
    return shutil.which("lean")


def is_lean_available() -> bool:
    return _find_lean_bin() is not None


# ---- Result helpers -----------------------------------------------------

def _skipped_result(reason: str) -> dict[str, Any]:
    """Result shape for cases where the backtest never executed."""
    return {
        "compile_success":       None,
        "runtime_success":       None,
        "runtime_error":         reason,
        "lean_results_json":     None,
        "total_return_pct":      None,
        "sharpe_ratio":          None,
        "max_drawdown_pct":      None,
        "num_trades":            None,
        "win_rate":              None,
        "final_portfolio_value": None,
        "benchmark_return_pct":  None,
    }


def _coerce_float(raw: Any) -> float | None:
    """LEAN reports many stats as strings like '12.34%' or '$1,234'. Coerce."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().rstrip("%").replace(",", "").replace("$", "")
    if not s or s in ("—", "N/A", "nan", "NaN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _coerce_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return None


def _extract_metrics(stats: dict) -> dict[str, Any]:
    """Pull the convenience fields out of LEAN's Statistics dict. Field names
    vary across LEAN versions; we handle the common variants."""
    def pick(*keys: str) -> Any:
        for k in keys:
            if k in stats:
                return stats[k]
        return None

    return {
        "total_return_pct":      _coerce_float(pick("Net Profit", "Total Return", "Compounding Annual Return")),
        "sharpe_ratio":          _coerce_float(pick("Sharpe Ratio")),
        "max_drawdown_pct":      _coerce_float(pick("Drawdown", "Max Drawdown")),
        "num_trades":            _coerce_int(pick("Total Trades", "Total Orders")),
        "win_rate":              _coerce_float(pick("Win Rate")),
        "final_portfolio_value": _coerce_float(pick("End Equity", "Final Portfolio Value")),
        "benchmark_return_pct":  _coerce_float(pick("Benchmark Return")),
    }


def _find_latest_result_json(project_dir: Path) -> Path | None:
    """LEAN writes results to <project>/backtests/<run_id>/<backtest_id>.json.
    Return the newest results file that contains a Statistics dict."""
    backtests = project_dir / "backtests"
    if not backtests.is_dir():
        return None
    runs = sorted(
        (d for d in backtests.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for run in runs:
        for path in sorted(run.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and ("Statistics" in data or "statistics" in data):
                return path
    return None


def _classify_outcome(stdout: str, stderr: str, exit_code: int) -> tuple[bool, bool, str | None]:
    """Heuristic classification of (compile_success, runtime_success, error_message)
    from LEAN's process output."""
    text = (stdout or "") + "\n" + (stderr or "")
    if re.search(r"\b(SyntaxError|IndentationError|ImportError|ModuleNotFoundError)\b", text):
        return False, False, _first_error_line(text)
    if re.search(r"RuntimeError|RuntimeException|During the algorithm initialization|During the algorithm execution", text):
        return True, False, _first_error_line(text)
    if exit_code != 0:
        return True, False, _first_error_line(text) or f"lean exited {exit_code}"
    return True, True, None


def _first_error_line(text: str) -> str | None:
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if any(tok in s for tok in ("Error", "error", "Exception", "Traceback")):
            return s[:500]
    return None


# ---- Public entry point -------------------------------------------------

async def run_backtest(
    generated_code: str | None,
    store: "Store",
    call_id: str,
    *,
    timeout_s: int = DEFAULT_BACKTEST_TIMEOUT_S,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Execute a LEAN backtest on `generated_code` and persist the result.

    Always writes to the calls row via store.update_call_with_backtest, even
    on skipped/failed paths, so the row state reflects what actually happened.
    Returns the same dict that was written (judge stage uses it directly).
    """
    if not generated_code:
        result = _skipped_result("no code extracted from model response")
        _persist(store, call_id, result)
        return result

    lean_bin = _find_lean_bin()
    if not lean_bin:
        result = _skipped_result(
            "lean CLI not installed; install with `pip install lean` "
            "and ensure it's on PATH (or set LEAN_BIN)"
        )
        _persist(store, call_id, result)
        return result

    if not (LEAN_WORKSPACE / "lean.json").is_file():
        result = _skipped_result(
            f"LEAN workspace not found at {LEAN_WORKSPACE}; "
            f"run `lean init` there or set $LEAN_WORKSPACE"
        )
        _persist(store, call_id, result)
        return result

    init_err = _ensure_workspace_initialized()
    if init_err is not None:
        result = _skipped_result(f"workspace not usable: {init_err}")
        _persist(store, call_id, result)
        return result

    # Projects must live inside the workspace so the CLI can resolve them
    # relative to the workspace `lean.json` (which configures data paths).
    project_dir = Path(tempfile.mkdtemp(prefix="leanbench_", dir=str(LEAN_WORKSPACE)))
    try:
        # 1. Materialize the project.
        (project_dir / "main.py").write_text(generated_code, encoding="utf-8")
        (project_dir / "config.json").write_text(
            json.dumps(PROJECT_TEMPLATE_CONFIG, indent=2), encoding="utf-8"
        )

        # 2. Run `lean backtest <project_name>` from the workspace root so the
        # CLI picks up the workspace lean.json (data folder, credentials).
        try:
            proc = await asyncio.create_subprocess_exec(
                lean_bin, "backtest", project_dir.name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(LEAN_WORKSPACE),
            )
        except (OSError, FileNotFoundError) as exc:
            result = _skipped_result(f"failed to launch lean: {exc}")
            _persist(store, call_id, result)
            return result

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            exit_code = proc.returncode or 0
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            result = _skipped_result(f"backtest timed out after {timeout_s}s")
            _persist(store, call_id, result)
            return result

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        # 3. Classify and parse.
        compile_ok, runtime_ok, err_msg = _classify_outcome(stdout, stderr, exit_code)

        lean_results_json: str | None = None
        metrics: dict[str, Any] = {
            "total_return_pct": None, "sharpe_ratio": None, "max_drawdown_pct": None,
            "num_trades": None, "win_rate": None, "final_portfolio_value": None,
            "benchmark_return_pct": None,
        }
        result_path = _find_latest_result_json(project_dir)
        if result_path is not None:
            try:
                raw = result_path.read_text(encoding="utf-8")
                lean_results_json = raw
                data = json.loads(raw)
                stats = data.get("Statistics") or data.get("statistics") or {}
                if isinstance(stats, dict):
                    metrics = _extract_metrics(stats)
            except (OSError, json.JSONDecodeError) as exc:
                err_msg = err_msg or f"could not read backtest results: {exc}"

        result = {
            "compile_success":   compile_ok,
            "runtime_success":   runtime_ok,
            "runtime_error":     err_msg,
            "lean_results_json": lean_results_json,
            **metrics,
        }
        _persist(store, call_id, result)
        return result

    finally:
        if cleanup:
            shutil.rmtree(project_dir, ignore_errors=True)


def _persist(store: "Store", call_id: str, result: dict[str, Any]) -> None:
    """Forward the result dict to the staged storage helper and fold the
    derived backtest_pass / trade_pass back onto the dict in place so callers
    (the orchestrator's return payload) can echo them without re-reading."""
    derived = store.update_call_with_backtest(
        call_id,
        compile_success=result["compile_success"],
        runtime_success=result["runtime_success"],
        runtime_error=result["runtime_error"],
        lean_results_json=result["lean_results_json"],
        total_return_pct=result["total_return_pct"],
        sharpe_ratio=result["sharpe_ratio"],
        max_drawdown_pct=result["max_drawdown_pct"],
        num_trades=result["num_trades"],
        win_rate=result["win_rate"],
        final_portfolio_value=result["final_portfolio_value"],
        benchmark_return_pct=result["benchmark_return_pct"],
    )
    result.update(derived)
