"""Public entry point. Composes runner + log_filter + artifact_reader.

Spec §3 + §4.4. The model only sees `RunResult.output`. `exit_status` is for
the caller's bookkeeping (retry on docker_error/infra_error, count timeouts,
etc.) and must NOT be exposed to the model — the model must not be able to
distinguish 'Docker died' from 'your code crashed.'
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import tiktoken

from . import log_filter, runner, spec_constants
from .artifact_reader import read_orders


@dataclass(frozen=True)
class RunConfig:
    """Runtime configuration. All fields required — determinism > convenience.

    workdir          base directory for the per-run project dir
    lean_data_dir    path to pre-staged LEAN data (D9 — tool does NOT download)
    docker_image     full image tag, ideally pinned by digest
    """
    workdir: str
    lean_data_dir: str
    docker_image: str


ExitStatus = Literal["completed", "timeout", "docker_error", "infra_error"]


@dataclass(frozen=True)
class RunResult:
    output: str
    exit_status: ExitStatus


# ---------------------------------------------------------------------------

def run(code: str, language: Literal["python", "csharp"], cfg: RunConfig) -> RunResult:
    """One backtest. Returns a filtered, deterministic, token-capped string.

    See docs/spec.md §3 for the contract. The caller — typically an agent loop
    — feeds `output` back to the model as tool-result. `exit_status` is for
    the caller's bookkeeping.
    """
    if language not in ("python", "csharp"):
        raise ValueError(f"language must be 'python' or 'csharp', got {language!r}")

    # Compute the deterministic path up-front so cleanup happens even when
    # run_backtest raises before binding the local. The dir may not exist yet
    # — cleanup_project_dir is best-effort and tolerates that.
    project_dir = runner.project_dir_for(code, cfg.workdir)
    try:
        _, runner_out = runner.run_backtest(
            code=code,
            language=language,
            workdir=cfg.workdir,
            lean_data_dir=cfg.lean_data_dir,
            docker_image=cfg.docker_image,
        )

        filtered = log_filter.filter_log(runner_out.raw_log)
        trailer = _build_trailer(runner_out)
        body = filtered + trailer
        capped = _apply_token_cap(body)

        return RunResult(output=capped, exit_status=runner_out.exit_status)
    finally:
        runner.cleanup_project_dir(project_dir)


def _build_trailer(runner_out: runner.RunnerOutput) -> str:
    """Pick the trailer per spec §4.4 step 5.

    Note on ordering: trailer is appended BEFORE truncation. On extreme
    overflow this may lose the trailer — that's the right tradeoff. Truncating
    first and then appending would decouple the trailer from the log content.
    """
    status = runner_out.exit_status
    if status == "completed":
        orders = read_orders(runner_out.output_dir) if runner_out.output_dir else None
        if orders is None:
            return spec_constants.TRAILER_ORDERS_UNKNOWN
        return spec_constants.TRAILER_COMPLETED_TEMPLATE.format(orders=orders)
    if status == "timeout":
        return spec_constants.TRAILER_TIMEOUT
    # docker_error / infra_error
    return spec_constants.TRAILER_INFRA_ERROR


def _apply_token_cap(text: str) -> str:
    """Tail-truncate to TOKEN_CAP. Prepend [TRUNCATED]\\n if cut (D6)."""
    enc = tiktoken.get_encoding(spec_constants.TOKEN_ENCODING)
    tokens = enc.encode(text)
    if len(tokens) <= spec_constants.TOKEN_CAP:
        return text
    # We need room for the marker too — measure it.
    marker_tokens = enc.encode(spec_constants.TRUNCATION_MARKER)
    budget = spec_constants.TOKEN_CAP - len(marker_tokens)
    if budget <= 0:
        # Pathological: cap smaller than marker. Just return the marker.
        return spec_constants.TRUNCATION_MARKER
    kept = tokens[-budget:]
    return spec_constants.TRUNCATION_MARKER + enc.decode(kept)
