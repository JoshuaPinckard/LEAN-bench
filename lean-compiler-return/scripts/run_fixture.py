"""Run one fixture against real pinned LEAN, capture the raw log.

Used during the empirical phase to populate tests/raw_logs/*.log. NOT part of
the published package.

Usage:
    python scripts/run_fixture.py compiles_no_trades.py --language python
    python scripts/run_fixture.py Main_CompileError.cs   --language csharp \\
        --data-dir C:/lean-data --image quantconnect/lean:<tag>
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lean_backtest_tool import RunConfig, run, runner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", help="fixture filename, e.g. compiles_no_trades.py")
    parser.add_argument("--language", choices=("python", "csharp"), required=True)
    parser.add_argument("--data-dir", default=os.environ.get("LEAN_DATA_DIR"))
    parser.add_argument("--image", default=os.environ.get("LEAN_DOCKER_IMAGE",
                                                          "quantconnect/lean:latest"))
    parser.add_argument("--workdir", default=str(REPO_ROOT / "scripts" / ".workdir"))
    parser.add_argument("--out", default=None,
                        help="raw log destination (default: tests/raw_logs/<fixture>.log)")
    args = parser.parse_args()

    fixtures_dir = REPO_ROOT / "tests" / "fixtures" / args.language
    fixture_path = fixtures_dir / args.fixture
    if not fixture_path.exists():
        print(f"ERROR: fixture not found: {fixture_path}", file=sys.stderr)
        return 2

    if not args.data_dir or not Path(args.data_dir).is_dir():
        print("ERROR: --data-dir or $LEAN_DATA_DIR must point to a LEAN data folder",
              file=sys.stderr)
        return 2

    Path(args.workdir).mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else REPO_ROOT / "tests" / "raw_logs" / f"{args.fixture}.log"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    code = fixture_path.read_text(encoding="utf-8")
    cfg = RunConfig(workdir=args.workdir, lean_data_dir=args.data_dir, docker_image=args.image)

    # We need the raw log, not just the filtered string. So intercept it
    # by patching cleanup to a noop temporarily and recovering the raw log
    # from the project dir afterward.
    project_dir = runner.project_dir_for(code, args.workdir)
    real_cleanup = runner.cleanup_project_dir

    def no_cleanup(_: Path) -> None:
        return None

    runner.cleanup_project_dir = no_cleanup  # type: ignore[assignment]
    try:
        result = run(code, args.language, cfg)
    finally:
        runner.cleanup_project_dir = real_cleanup  # type: ignore[assignment]

    print(f"exit_status: {result.exit_status}")
    print(f"filtered output: {len(result.output)} chars")
    print(f"--- FILTERED ---")
    print(result.output)
    print(f"--- END FILTERED ---")

    # Look for the raw log in the project dir.
    log_files: list[Path] = []
    if project_dir.exists():
        log_files = list(project_dir.glob("backtests/**/*-log.txt"))
        log_files += [p for p in (project_dir / "container_stdout.log",) if p.exists()]

    raw = ""
    if log_files:
        # Prefer the LEAN log over the container stdout.
        for p in log_files:
            if "-log.txt" in p.name:
                raw = p.read_text(encoding="utf-8", errors="replace")
                break
        if not raw:
            raw = log_files[0].read_text(encoding="utf-8", errors="replace")

    if not raw:
        print("WARNING: no raw log found in project dir", file=sys.stderr)
    else:
        out_path.write_text(raw, encoding="utf-8")
        print(f"raw log saved: {out_path} ({len(raw)} chars)")

    # Cleanup now.
    real_cleanup(project_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
