"""EMPIRICAL #4 — warning emission for silent-failure modes.

Procedure (per spec §5):
  1. Run three temporary fixtures targeting silent-failure modes.
  2. Inventory all tags in each raw log; in particular, look for any tag
     whose name suggests "warning."
  3. Compare against TRACE/STATISTICS/USAGE/ERROR baseline. Any *new* tag is
     a candidate signal.

Writes raw logs to tests/raw_logs/_empirical4/ and a summary to
findings.md (manually appended).
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lean_backtest_tool import RunConfig, run, runner, spec_constants  # noqa: E402


FIXTURES = [
    "warn_no_data.py",
    "warn_warmup.py",
    "warn_zero_position.py",
]


def main() -> int:
    os.environ["MSYS_NO_PATHCONV"] = "1"
    workdir = REPO_ROOT / "scripts" / ".workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    dump = REPO_ROOT / "tests" / "raw_logs" / "_empirical4"
    dump.mkdir(parents=True, exist_ok=True)

    image = os.environ.get("LEAN_DOCKER_IMAGE", spec_constants.DEFAULT_DOCKER_IMAGE)

    pattern = re.compile(r"(?:^|\s)(\w+)::")
    baseline = {"TRACE", "STATISTICS", "USAGE", "ERROR"}

    for fixture_name in FIXTURES:
        src = REPO_ROOT / "scripts" / "fixtures_empirical4" / fixture_name
        code = src.read_text(encoding="utf-8")

        project_dir = runner.project_dir_for(code, str(workdir))
        real_cleanup = runner.cleanup_project_dir
        runner.cleanup_project_dir = lambda p: None  # type: ignore[assignment]
        try:
            cfg = RunConfig(workdir=str(workdir), lean_data_dir="", docker_image=image)
            print(f"[run] {fixture_name} ...", flush=True)
            result = run(code, "python", cfg)
        finally:
            runner.cleanup_project_dir = real_cleanup  # type: ignore[assignment]

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

        (dump / f"{fixture_name}.log").write_text(raw, encoding="utf-8")
        (dump / f"{fixture_name}.filtered.txt").write_text(result.output, encoding="utf-8")

        tags: dict[str, list[str]] = defaultdict(list)
        for line in raw.splitlines():
            m = pattern.search(line)
            if not m:
                continue
            tag = m.group(1)
            if len(tags[tag]) < 5:
                tags[tag].append(line.strip()[:160])

        novel = sorted(set(tags.keys()) - baseline)
        print(f"  exit_status={result.exit_status}  raw={len(raw)} bytes  "
              f"all_tags={sorted(tags.keys())}  NEW_TAGS={novel}", flush=True)
        for tag in novel:
            print(f"    -- {tag}:: examples --")
            for line in tags[tag][:3]:
                print(f"       {line}")

        real_cleanup(project_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
