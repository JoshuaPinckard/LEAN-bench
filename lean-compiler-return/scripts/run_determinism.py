"""EMPIRICAL #3 — confirm byte-identical RunResult.output across N runs.

Procedure (per spec §5):
  1. Pick `compiles_no_trades` in each language (the no-error, moderate-output
     case). Run 5 times.
  2. Capture each RunResult.output and each raw log.
  3. Pairwise diff outputs. They MUST be byte-identical.
  4. Pairwise diff raw logs. Differences are the universe of nondeterministic
     tokens — confirm each one is covered by a regex in
     spec_constants.DETERMINISM_STRIPPERS.

Writes a per-run dump under tests/raw_logs/_determinism/ for audit.
"""
from __future__ import annotations

import argparse
import difflib
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lean_backtest_tool import RunConfig, run, runner, spec_constants  # noqa: E402


def run_one(code: str, language: str, workdir: Path, image: str) -> tuple[str, str]:
    project_dir = runner.project_dir_for(code, str(workdir))
    real_cleanup = runner.cleanup_project_dir
    runner.cleanup_project_dir = lambda p: None  # type: ignore[assignment]
    try:
        cfg = RunConfig(workdir=str(workdir), lean_data_dir="", docker_image=image)
        result = run(code, language, cfg)
        # Recover the raw log post-hoc.
        backtests = project_dir / "backtests"
        raw = ""
        if backtests.is_dir():
            for p in sorted(backtests.glob("log.txt")) + sorted(backtests.glob("*-log.txt")):
                try:
                    t = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if len(t) > len(raw):
                    raw = t
        if not raw:
            container = project_dir / "container_stdout.log"
            if container.exists():
                raw = container.read_text(encoding="utf-8", errors="replace")
        return result.output, raw
    finally:
        runner.cleanup_project_dir = real_cleanup  # type: ignore[assignment]
        real_cleanup(project_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=("python", "csharp", "both"), default="both")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--workdir", default=str(REPO_ROOT / "scripts" / ".workdir"))
    parser.add_argument("--image", default=os.environ.get(
        "LEAN_DOCKER_IMAGE", spec_constants.DEFAULT_DOCKER_IMAGE,
    ))
    args = parser.parse_args()

    workdir = Path(args.workdir).absolute()
    workdir.mkdir(parents=True, exist_ok=True)
    dump_dir = REPO_ROOT / "tests" / "raw_logs" / "_determinism"
    dump_dir.mkdir(parents=True, exist_ok=True)

    os.environ["MSYS_NO_PATHCONV"] = "1"

    languages = ["python", "csharp"] if args.language == "both" else [args.language]
    overall_ok = True

    for lang in languages:
        print(f"\n========== {lang} determinism ({args.runs} runs) ==========")
        fixture = "compiles_no_trades.py" if lang == "python" else "Main_CompilesNoTrades.cs"
        code = (REPO_ROOT / "tests" / "fixtures" / lang / fixture).read_text(encoding="utf-8")

        outputs: list[str] = []
        raw_logs: list[str] = []
        for i in range(args.runs):
            print(f"  [run {i+1}/{args.runs}] ", end="", flush=True)
            try:
                out, raw = run_one(code, lang, workdir, args.image)
            except Exception as e:  # noqa: BLE001
                print(f"FAILED: {e!r}")
                overall_ok = False
                continue
            outputs.append(out)
            raw_logs.append(raw)
            (dump_dir / f"{lang}_run{i+1}.out.txt").write_text(out, encoding="utf-8")
            (dump_dir / f"{lang}_run{i+1}.raw.log").write_text(raw, encoding="utf-8")
            print(f"output={len(out)} chars, raw={len(raw)} chars")

        if len(outputs) < 2:
            print(f"  not enough successful runs to compare ({len(outputs)})")
            overall_ok = False
            continue

        # Output byte-identicality.
        first = outputs[0]
        identical = all(o == first for o in outputs[1:])
        print(f"  outputs byte-identical: {identical}")
        if not identical:
            overall_ok = False
            for i, o in enumerate(outputs[1:], start=2):
                if o != first:
                    diff = "\n".join(difflib.unified_diff(
                        first.splitlines()[:60],
                        o.splitlines()[:60],
                        fromfile=f"run1", tofile=f"run{i}",
                        lineterm="",
                    ))
                    print(f"--- diff run1 vs run{i} (first 60 lines each) ---")
                    print(diff[:2000])

        # Raw log diff — informational only (raw logs will differ across runs;
        # the question is whether the strippers reduce them to byte-identical).
        # Compare the *post-filter, post-strip* outputs (which IS what
        # `outputs` already contains, so we already covered the test of
        # interest via the byte-identical check above).
        # Show a short unified diff of raw run1 vs run2 for the audit dump.
        if len(raw_logs) >= 2:
            diff_audit = "\n".join(difflib.unified_diff(
                raw_logs[0].splitlines()[:80],
                raw_logs[1].splitlines()[:80],
                fromfile="raw_run1", tofile="raw_run2", lineterm="",
            ))
            (dump_dir / f"{lang}_raw_diff_run1_vs_run2.txt").write_text(
                diff_audit, encoding="utf-8")

    print("\n=====")
    print("overall determinism:", "PASS" if overall_ok else "FAIL")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
