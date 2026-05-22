"""Run all fixtures against real pinned LEAN, capture raw logs and tag inventory.

Outputs:
  tests/raw_logs/<fixture>.log     — raw LEAN log (the larger of log.txt /
                                     <name>-log.txt, falling back to container
                                     stdout if neither exists).
  tests/raw_logs/_inventory.json   — tag inventory across all fixtures,
                                     populated for EMPIRICAL #1.
  tests/raw_logs/_outputs.txt      — filtered output (what the model sees) for
                                     each fixture, for spot-checks.

Usage:
  python scripts/run_empirical.py [--language python|csharp|both] [--workdir DIR]

NOT part of the published package.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lean_backtest_tool import RunConfig, run, runner, spec_constants  # noqa: E402


PYTHON_FIXTURES = [
    "compiles_no_trades.py",
    "import_error.py",
    "initialize_error.py",
    "runtime_error_ondata.py",
    "compiles_with_trades.py",
    "infinite_loop.py",
]

CSHARP_FIXTURES = [
    "Main_CompilesNoTrades.cs",
    "Main_CompileError.cs",
    "Main_InitializeError.cs",
    "Main_RuntimeError.cs",
    "Main_CompilesWithTrades.cs",
    "Main_InfiniteLoop.cs",
]


def _read_log_from_project(project_dir: Path) -> str:
    """Recover the raw LEAN log from a project dir that hasn't been cleaned."""
    candidates: list[Path] = []
    backtests = project_dir / "backtests"
    if backtests.is_dir():
        candidates += sorted(backtests.glob("log.txt"))
        candidates += sorted(backtests.glob("*-log.txt"))
        for sub in backtests.iterdir():
            if sub.is_dir():
                candidates += sorted(sub.glob("log.txt"))
                candidates += sorted(sub.glob("*-log.txt"))
    # Fall back to container stdout if no LEAN log exists.
    container = project_dir / "container_stdout.log"
    if container.exists():
        candidates.append(container)

    best: str = ""
    for p in candidates:
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(t) > len(best):
            best = t
    return best


def _extract_tags(raw_log: str) -> dict[str, list[str]]:
    """Return {tag: [example lines, up to 3]} for tags found in raw_log."""
    pattern = re.compile(r"(?:^|\s)(\w+)::")
    out: dict[str, list[str]] = defaultdict(list)
    for line in raw_log.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        tag = m.group(1)
        if len(out[tag]) < 3:
            out[tag].append(line.strip()[:160])
    return dict(out)


def run_one(fixture_name: str, language: str, workdir: Path,
            data_dir: str, image: str, raw_logs_dir: Path,
            outputs_sink: list[str]) -> dict:
    """Run one fixture, capture raw log + filtered output. Return inventory dict."""
    fixture_path = REPO_ROOT / "tests" / "fixtures" / language / fixture_name
    code = fixture_path.read_text(encoding="utf-8")

    project_dir_path = runner.project_dir_for(code, str(workdir))

    # Disable cleanup so we can read the raw log afterward.
    real_cleanup = runner.cleanup_project_dir
    runner.cleanup_project_dir = lambda p: None  # type: ignore[assignment]

    cfg = RunConfig(workdir=str(workdir), lean_data_dir=data_dir, docker_image=image)
    start = time.monotonic()
    try:
        result = run(code, language, cfg)
    finally:
        runner.cleanup_project_dir = real_cleanup  # type: ignore[assignment]
    elapsed = time.monotonic() - start

    raw_log = _read_log_from_project(project_dir_path)
    log_dest = raw_logs_dir / f"{fixture_name}.log"
    log_dest.write_text(raw_log, encoding="utf-8")

    tags = _extract_tags(raw_log)

    outputs_sink.append(f"\n========== {language}/{fixture_name} ==========\n"
                        f"exit_status: {result.exit_status}  wall: {elapsed:.1f}s\n"
                        f"--- FILTERED OUTPUT ---\n{result.output}\n")

    # Clean up the project dir now that we've extracted what we need.
    real_cleanup(project_dir_path)

    return {
        "fixture": fixture_name,
        "language": language,
        "exit_status": result.exit_status,
        "wall_seconds": round(elapsed, 1),
        "raw_log_bytes": len(raw_log),
        "tags": tags,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=("python", "csharp", "both"), default="both")
    parser.add_argument("--workdir", default=str(REPO_ROOT / "scripts" / ".workdir"))
    parser.add_argument("--data-dir", default=os.environ.get("LEAN_DATA_DIR", ""))
    parser.add_argument("--image", default=os.environ.get(
        "LEAN_DOCKER_IMAGE", spec_constants.DEFAULT_DOCKER_IMAGE,
    ))
    parser.add_argument("--only", default=None,
                        help="run only this fixture filename")
    args = parser.parse_args()

    workdir = Path(args.workdir).absolute()
    workdir.mkdir(parents=True, exist_ok=True)
    raw_logs_dir = REPO_ROOT / "tests" / "raw_logs"
    raw_logs_dir.mkdir(exist_ok=True)

    # Set the MSYS env var so Git Bash doesn't mangle docker paths.
    os.environ["MSYS_NO_PATHCONV"] = "1"

    inventory: list[dict] = []
    outputs_sink: list[str] = []

    targets: list[tuple[str, str]] = []
    if args.language in ("python", "both"):
        for f in PYTHON_FIXTURES:
            if args.only and f != args.only:
                continue
            targets.append((f, "python"))
    if args.language in ("csharp", "both"):
        for f in CSHARP_FIXTURES:
            if args.only and f != args.only:
                continue
            targets.append((f, "csharp"))

    for name, lang in targets:
        print(f"[run] {lang}/{name} ...", flush=True)
        try:
            info = run_one(name, lang, workdir, args.data_dir, args.image,
                           raw_logs_dir, outputs_sink)
            inventory.append(info)
            print(f"      -> exit_status={info['exit_status']}  "
                  f"wall={info['wall_seconds']}s  "
                  f"tags={sorted(info['tags'].keys())}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"      !! FAILED: {e!r}", flush=True)
            inventory.append({
                "fixture": name, "language": lang,
                "exit_status": "tool_exception", "error": repr(e),
            })

    (raw_logs_dir / "_inventory.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8")
    (raw_logs_dir / "_outputs.txt").write_text("".join(outputs_sink), encoding="utf-8")

    # Aggregate tag set across all runs.
    union: set[str] = set()
    for r in inventory:
        union.update(r.get("tags", {}).keys())
    print("\nUnion of all tags observed:", sorted(union))
    return 0


if __name__ == "__main__":
    sys.exit(main())
