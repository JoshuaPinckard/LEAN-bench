"""Docker invocation + per-run project directory lifecycle + timeout.

Responsibilities (spec §4.1):
  1. Compute a deterministic project dir name from the code hash.
  2. Create the project dir fresh (blow away any prior incomplete run).
  3. Write the algorithm source + LEAN config.json + (C#) the fixed .csproj.
  4. Invoke `docker run` against the pinned LEAN image with --cpus / --memory.
  5. Enforce the wall-clock timeout (SIGTERM, grace, then SIGKILL).
  6. Locate the artifacts (output dir + log file). Do not parse them.

Does NOT clean up the project dir. The caller in tool.py owns lifecycle via
try/finally so cleanup happens even on exceptions.

The actual docker subprocess call is isolated in `_invoke_docker` and can be
monkey-patched by tests / by the UI's mock mode. See `set_invoker()`.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

from . import spec_constants
from .exceptions import DockerUnavailable, InfraError, TimeoutKilled

# Type for the swappable docker invoker. Returns the process exit code. Raises
# DockerUnavailable / TimeoutKilled as appropriate. `log_sink` is a path the
# invoker should ensure receives the container's combined stdout+stderr.
Invoker = Callable[["DockerInvocation"], int]


@dataclass(frozen=True)
class DockerInvocation:
    """Everything the docker invoker needs to run one container.

    `data_dir` is Optional: when None, no /Lean/Data mount is added and the
    image's bundled data folder shows through. Production callers always pass
    a real local path (spec D9). The 'no mount' branch is a development
    convenience used by the empirical phase.
    """
    image: str
    project_dir: Path
    data_dir: Optional[Path]
    log_sink: Path
    timeout_seconds: int
    cpus: str
    memory: str


@dataclass(frozen=True)
class RunnerOutput:
    raw_log: str
    output_dir: Optional[Path]
    exit_status: Literal["completed", "timeout", "docker_error", "infra_error"]


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------

def run_backtest(
    code: str,
    language: Literal["python", "csharp"],
    workdir: str,
    lean_data_dir: str,
    docker_image: str,
    csproj_template_path: Optional[str] = None,
) -> tuple[Path, RunnerOutput]:
    """Run one backtest. Returns (project_dir, RunnerOutput).

    The caller (tool.py) is responsible for cleaning up project_dir.
    """
    project_dir = _create_project_dir(code, workdir)
    _write_sources(project_dir, code, language, csproj_template_path)
    _write_config(project_dir, language)

    log_sink = project_dir / "container_stdout.log"
    data_dir_path: Optional[Path]
    if lean_data_dir and lean_data_dir.strip():
        data_dir_path = Path(lean_data_dir)
    else:
        # Empty string -> no mount; image's bundled /Lean/Data shows through.
        data_dir_path = None
    invocation = DockerInvocation(
        image=docker_image,
        project_dir=project_dir,
        data_dir=data_dir_path,
        log_sink=log_sink,
        timeout_seconds=spec_constants.TIMEOUT_SECONDS,
        cpus=spec_constants.DOCKER_CPUS,
        memory=spec_constants.DOCKER_MEMORY,
    )

    try:
        exit_code = _invoker(invocation)
    except TimeoutKilled:
        raw_log = _read_best_effort_log(project_dir, log_sink)
        output_dir = _locate_output_dir(project_dir)
        return project_dir, RunnerOutput(
            raw_log=raw_log,
            output_dir=output_dir,
            exit_status="timeout",
        )
    except DockerUnavailable:
        return project_dir, RunnerOutput(
            raw_log="",
            output_dir=None,
            exit_status="docker_error",
        )
    except InfraError:
        return project_dir, RunnerOutput(
            raw_log=_read_best_effort_log(project_dir, log_sink),
            output_dir=None,
            exit_status="infra_error",
        )

    output_dir = _locate_output_dir(project_dir)
    raw_log = _read_best_effort_log(project_dir, log_sink)
    if output_dir is None:
        # Container ran and exited but produced no LEAN output dir. Two sub-cases:
        #
        # 1. The container produced log content anyway (e.g. C# `dotnet build`
        #    failed before LEAN was invoked — EMPIRICAL #2 Outcome C). The
        #    user's code is at fault, not the tool's infrastructure. Surface
        #    that as a normal completion-with-no-orders so the model reads
        #    the actual error rather than an INFRASTRUCTURE_ERROR trailer.
        #
        # 2. The container produced nothing at all. That's a genuine
        #    infra-side failure (image broken, mount unusable, etc.).
        if raw_log:
            return project_dir, RunnerOutput(
                raw_log=raw_log,
                output_dir=None,
                exit_status="completed",
            )
        return project_dir, RunnerOutput(
            raw_log="",
            output_dir=None,
            exit_status="infra_error",
        )
    return project_dir, RunnerOutput(
        raw_log=raw_log,
        output_dir=output_dir,
        exit_status="completed",
    )


# ---------------------------------------------------------------------------
# Invoker — swappable. Default invokes Docker; UI / tests can replace it.
# ---------------------------------------------------------------------------

def _default_invoker(inv: DockerInvocation) -> int:
    """The real Docker invocation.

    Mounts the project at /LeanCLI. The data dir is mounted read-only at
    /Lean/Data when `inv.data_dir` points at a real local directory; when the
    configured path is empty or missing, no data mount is added — the image's
    bundled /Lean/Data shows through (useful during the empirical phase, and
    documented as a development convenience).

    Language detection: if /LeanCLI/Main.cs is present in the bound project
    dir, the container runs `dotnet build` against the included .csproj
    first, then invokes the LEAN launcher with the same config. The two-step
    is folded into a single `docker run` via a shell entrypoint so resource
    limits (D12) apply to both phases.

    Container name: a UUID is assigned via `--name`. SIGTERM on the docker
    CLI process is unreliable on Windows — it kills the client but not the
    container — so the timeout handler uses `docker kill <name>` directly.

    The container's combined stdout+stderr is tee'd into `inv.log_sink` so
    we can recover partial output on timeout.
    """
    import uuid
    container_name = f"leanbt_{uuid.uuid4().hex[:12]}"

    has_csharp = (inv.project_dir / "Main.cs").exists()

    cmd = [
        "docker", "run", "--rm",
        "--name", container_name,
        f"--cpus={inv.cpus}",
        f"--memory={inv.memory}",
        "--mount", f"type=bind,source={inv.project_dir.as_posix()},target=/LeanCLI",
    ]
    if inv.data_dir is not None:
        cmd += ["--mount", f"type=bind,source={inv.data_dir.as_posix()},target=/Lean/Data,readonly"]

    if has_csharp:
        # Build then run, in one container, with `set -e` so a compile failure
        # halts before LEAN is invoked. The dotnet build output is appended to
        # the container's stdout (and thus to log_sink) so EMPIRICAL #2 sees
        # compile errors in the expected place.
        shell_script = (
            "set -e; "
            "cd /LeanCLI && dotnet build --nologo -c Release "
            "  --output /LeanCLI/bin/Release "
            "  /LeanCLI/QuantConnect.Algorithm.csproj && "
            "cd /Lean/Launcher/bin/Debug && "
            "dotnet QuantConnect.Lean.Launcher.dll --config /LeanCLI/config.json"
        )
        cmd += [
            "--entrypoint", "sh",
            inv.image,
            "-c", shell_script,
        ]
    else:
        cmd += [
            inv.image,
            "--config", "/LeanCLI/config.json",
        ]

    inv.log_sink.parent.mkdir(parents=True, exist_ok=True)
    try:
        with inv.log_sink.open("wb") as sink:
            proc = subprocess.Popen(
                cmd,
                stdout=sink,
                stderr=subprocess.STDOUT,
            )
    except FileNotFoundError as e:
        raise DockerUnavailable(f"`docker` not on PATH: {e}") from e

    start = time.monotonic()
    deadline = start + inv.timeout_seconds
    poll_interval = 0.5
    while True:
        rc = proc.poll()
        if rc is not None:
            # Distinguish a normal exit-non-zero from a 'docker daemon not
            # running' style failure. The signature for the latter shows up
            # in stderr — easiest tell is exit code 125 (docker run startup).
            if rc == 125:
                raise DockerUnavailable(
                    "docker run exit 125 — daemon unavailable or image missing"
                )
            return rc
        if time.monotonic() >= deadline:
            _kill_docker_container(container_name, proc)
            raise TimeoutKilled(
                f"backtest exceeded {inv.timeout_seconds}s wall-clock"
            )
        time.sleep(poll_interval)


def _kill_docker_container(container_name: str, proc: subprocess.Popen) -> None:
    """Kill the named container and then reap the local docker CLI process.

    On Windows, SIGTERM-ing the local `docker run` process does not propagate
    to the container — Docker keeps the container running. So we have to use
    `docker kill <name>` directly. After that, the local CLI exits on its own;
    we just reap it.
    """
    grace = spec_constants.SIGTERM_GRACE_SECONDS
    # docker kill defaults to SIGKILL which doesn't give the algorithm a
    # chance to flush, but for our use case (infinite loop / hung algorithm)
    # SIGTERM-then-SIGKILL via docker doesn't get us much. Use SIGKILL.
    try:
        subprocess.run(
            ["docker", "kill", container_name],
            timeout=grace,
            capture_output=True,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # Reap the local CLI.
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.2)
    try:
        proc.kill()
    except ProcessLookupError:
        pass


_invoker: Invoker = _default_invoker


def set_invoker(invoker: Invoker) -> None:
    """Replace the docker invoker. Used by the UI's 'mock' toggle and by tests.

    The replacement must respect the same contract: return an int exit code,
    raise DockerUnavailable / TimeoutKilled / InfraError as appropriate, and
    write something to `inv.log_sink` if the run produced any output.
    """
    global _invoker
    _invoker = invoker


def reset_invoker() -> None:
    global _invoker
    _invoker = _default_invoker


# ---------------------------------------------------------------------------
# Project directory setup.
# ---------------------------------------------------------------------------

def project_dir_for(code: str, workdir: str) -> Path:
    """Compute the deterministic project dir path for `code` under `workdir`.

    Pure — does not create the directory. Used by tool.py to know what to
    clean up even when run_backtest raises before assigning a return value.
    """
    h = hashlib.sha256(code.encode("utf-8")).hexdigest()[: spec_constants.PROJECT_DIR_HASH_LEN]
    return Path(workdir) / f"{spec_constants.PROJECT_DIR_PREFIX}{h}"


def _create_project_dir(code: str, workdir: str) -> Path:
    """Per spec §4.1 + D8: deterministic name = lean_run_<short hash of code>.

    Fresh directory each invocation — if one already exists from a prior
    incomplete run with the same code, blow it away and recreate.
    """
    project_dir = project_dir_for(code, workdir)
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=False)
    project_dir.mkdir(parents=True, exist_ok=False)
    (project_dir / "backtests").mkdir()
    return project_dir


def _write_sources(
    project_dir: Path,
    code: str,
    language: str,
    csproj_template_path: Optional[str],
) -> None:
    if language == "python":
        (project_dir / "main.py").write_text(code, encoding="utf-8")
    elif language == "csharp":
        (project_dir / "Main.cs").write_text(code, encoding="utf-8")
        # Spec D10: ship a fixed .csproj, model cannot modify it.
        if csproj_template_path is None:
            csproj_template_path = str(
                Path(__file__).resolve().parent.parent / "docs" / "csproj_template.xml"
            )
        shutil.copyfile(csproj_template_path, project_dir / "QuantConnect.Algorithm.csproj")
    else:
        raise ValueError(f"Unsupported language: {language!r}")


def _write_config(project_dir: Path, language: str) -> None:
    """Minimal LEAN config.json for an in-image backtest run.

    The container sees the project dir mounted at /LeanCLI. We point LEAN at
    that path for algorithm location and at /Lean/Data for the data folder,
    with results written back into /LeanCLI/backtests for our retrieval.
    """
    config = {
        "environment": "backtesting",

        "algorithm-type-name": "BacktestAlgorithm",
        "algorithm-language": "Python" if language == "python" else "CSharp",
        # For C#, the launcher's working dir is /Lean/Launcher/bin/Debug,
        # so the algorithm-location is resolved relative to there UNLESS it
        # starts with '/'. We use the absolute path to the DLL the build step
        # produces under /LeanCLI/bin/Release.
        "algorithm-location": (
            "/LeanCLI/main.py" if language == "python"
            else "/LeanCLI/bin/Release/QuantConnect.Algorithm.dll"
        ),

        "data-folder": "/Lean/Data/",
        "results-destination-folder": "/LeanCLI/backtests/",
        "object-store-root": "/LeanCLI/storage/",

        "log-handler": "QuantConnect.Logging.CompositeLogHandler",
        "messaging-handler": "QuantConnect.Messaging.Messaging",
        "job-queue-handler": "QuantConnect.Queues.JobQueue",
        "api-handler": "QuantConnect.Api.Api",
        "map-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider",
        "factor-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider",
        "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",

        "environments": {
            "backtesting": {
                "live-mode": False,
                "setup-handler": "QuantConnect.Lean.Engine.Setup.ConsoleSetupHandler",
                "result-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
                "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
                "real-time-handler": "QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler",
                "history-provider": "QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider",
                "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler",
            },
        },
    }
    (project_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Artifact location.
# ---------------------------------------------------------------------------

def _locate_output_dir(project_dir: Path) -> Optional[Path]:
    """Find the backtest output directory inside project_dir.

    Two layouts observed (the spec described layout A; the pinned image
    actually emits layout B):

      A. Older LEAN: backtests/<timestamp>/<id>.json + <id>-log.txt
      B. v2.5+ LEAN: backtests/<algorithm-name>.json + <algorithm-name>-log.txt
         and an unprefixed log.txt — all files directly in backtests/.

    For layout A, return the most recent timestamped subdir. For layout B,
    return `backtests/` itself. Returns None if no results landed anywhere.
    """
    backtests = project_dir / "backtests"
    if not backtests.is_dir():
        return None

    subdirs = [p for p in backtests.iterdir() if p.is_dir()]
    if subdirs:
        # Layout A — pick most recent.
        subdirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return subdirs[0]

    # Layout B — files directly in backtests/. Confirm there is at least one
    # results-shaped file before claiming this dir, so a stub-empty backtests/
    # still returns None and surfaces as infra_error.
    has_results = any(backtests.glob("*.json")) or any(backtests.glob("*log*.txt"))
    return backtests if has_results else None


def _read_best_effort_log(project_dir: Path, container_log: Path) -> str:
    """Reconstruct the rawest log we can given whatever LEAN/Docker produced.

    Preference order:
      1. The richer of `log.txt` / `<algorithm>-log.txt` in the output dir
         (v2.5+ LEAN emits both — `log.txt` has the full engine trace, the
         prefixed one is a short summary).
      2. The container's combined stdout+stderr we tee'd at log_sink.
      3. Empty string.

    Picking the richer log: prefer the one with more characters. This handles
    LEAN versions where the prefixed log is the full one and versions where
    `log.txt` is.
    """
    output_dir = _locate_output_dir(project_dir)
    if output_dir is not None:
        candidates: list[Path] = []
        candidates += sorted(output_dir.glob("log.txt"))
        candidates += sorted(output_dir.glob("*-log.txt"))
        # Deduplicate while preserving order.
        seen: set[Path] = set()
        ordered: list[Path] = []
        for p in candidates:
            if p in seen:
                continue
            seen.add(p)
            ordered.append(p)
        best: Optional[str] = None
        best_len = -1
        for p in ordered:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(text) > best_len:
                best = text
                best_len = len(text)
        if best is not None:
            return best
    if container_log.exists():
        try:
            return container_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return ""


# ---------------------------------------------------------------------------
# Cleanup — called from tool.py's try/finally.
# ---------------------------------------------------------------------------

def cleanup_project_dir(project_dir: Path) -> None:
    """Best-effort cleanup. Logs are already in the returned string by now."""
    try:
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)
    except OSError:
        # Cleanup failures are noisy but non-fatal — the next run with the
        # same code hash will blow this dir away anyway.
        pass
