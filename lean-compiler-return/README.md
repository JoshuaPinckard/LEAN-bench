# lean_backtest_tool

A single-responsibility Python tool. Takes `(code, language, runtime_config)`,
runs one backtest against a pinned LEAN Docker image, and returns a filtered
deterministic log string. Built to be the F-arm tool of an LLM benchmark,
where reproducibility and tag-filter behavior are part of the published claims.

This README points to the canonical sources of truth:
- **`docs/spec.md`** — the implementation contract (do not edit lightly).
- **`findings.md`** — what the empirical phase revealed and how the constants
  in `lean_backtest_tool/spec_constants.py` were derived from it.

## Install

```powershell
# From the repo root
pip install -e .
pip install -e ".[test]"
```

## Public interface

```python
from lean_backtest_tool import run, RunConfig

cfg = RunConfig(
    workdir="C:/path/to/scratch",        # per-run dirs get created/torn down here
    lean_data_dir="C:/path/to/lean/data", # pre-staged data; tool does NOT download
    docker_image="quantconnect/lean:<digest>",
)
result = run(code, "python", cfg)        # or "csharp"
print(result.output)                     # string the model sees
print(result.exit_status)                # caller bookkeeping; NOT shown to model
```

## Run tests

Offline suite (fast, no Docker):
```powershell
python -m pytest tests/
```

Real-LEAN suite (slow, requires Docker + pinned image + LEAN data dir):
```powershell
$env:LEAN_DATA_DIR = "C:/lean-data"
$env:LEAN_DOCKER_IMAGE = "quantconnect/lean:<digest>"
python -m pytest tests/ -m requires_docker
```

The spec gates "done" on `test_determinism.py::test_byte_identical_real_lean`
passing — same code, same output, byte-for-byte.

## Test UI (optional, removable)

A Tkinter desktop harness lives under `ui/`. It exists so you can drop in
candidate code, hit Run, and see the filter behavior side-by-side with the
raw log. **It is not part of the published package.** Delete the entire
`ui/` directory before integrating the package into a parent project.

```powershell
python -m ui.app
```

The UI defaults to **Mock mode** (no Docker). The mock invoker writes a
canned LEAN-shaped log keyed off heuristics in the submitted code, so you
can exercise the filter, the trailer logic, and the timeout path without
spinning up a container. Uncheck Mock to invoke real Docker.

The right pane has three tabs:
- **Filtered (model sees this)** — `RunResult.output`.
- **Raw log** — pre-filter content (mock mode only; real mode does not
  retain the raw log by design, see Diff tab note in `ui/app.py`).
- **Diff** — raw log with kept lines green, dropped lines struck-through;
  shows the filter behavior visually.

## Repository layout

```
lean_backtest_tool/         # library — the deliverable
  spec_constants.py         # ALL POLICY (tags, regexes, timeout, cap, markers)
  log_filter.py             # pure tag-based filter + determinism stripping
  artifact_reader.py        # parses orders count from LEAN results JSON
  runner.py                 # Docker invocation + project-dir lifecycle + timeout
  tool.py                   # public entry; composes the above
  exceptions.py             # tool-internal exception types
docs/
  spec.md                   # the implementation contract
  csproj_template.xml       # fixed .csproj for C# fixtures (spec D10)
tests/
  fixtures/                 # 12 minimal LEAN algorithms (6 Python, 6 C#)
  raw_logs/                 # raw LEAN log captures from the empirical phase
    _determinism/           # EMPIRICAL #3 captures (5 paired runs per language)
    _empirical4/            # EMPIRICAL #4 silent-failure fixture captures
    _inventory.json         # tag inventory across all 12 fixtures
    _outputs.txt            # filtered RunResult.output per fixture
  test_*.py                 # unit + e2e + determinism suite
scripts/                    # empirical-phase runner helpers — REMOVABLE
  run_empirical.py          # runs all 12 fixtures, captures raw logs
  run_determinism.py        # 5x same fixture, asserts byte-identical
  run_empirical4.py         # 3 silent-failure fixtures
ui/                         # Tkinter test harness — REMOVABLE
findings.md                 # empirical-phase write-up
```

`scripts/` and `ui/` are development utilities. Delete both before
integrating the library into a parent project; the package itself only
needs `lean_backtest_tool/`, `docs/`, and (optionally) `tests/`.

## Definition of done

See `docs/spec.md` §9.
- [x] Repo layout matches spec §2.
- [x] All offline tests pass (`pytest tests/`) — 50 tests.
- [x] Pinned LEAN image pulled (`quantconnect/lean:latest`, lean_version 17744).
- [x] All four EMPIRICAL investigations complete; raw logs committed under
      `tests/raw_logs/`; `findings.md` written up.
- [x] `test_determinism.py::test_byte_identical_real_lean` passes for both
      Python and C# — byte-identical output across re-runs on real LEAN
      (`LEAN_DATA_DIR="" pytest tests/ -m requires_docker`).
- [ ] `findings.md` has **3 open escalation items** for the project owner —
      see `findings.md` §6. None of them block the tool's current behavior,
      but they affect what the benchmark can claim.

## Open escalation items (from `findings.md` §6)

1. **Pin verification.** The latest QC docker image exposes `lean_version`
   but not a git commit hash; verifying it matches the spec's pinned
   commit `d2daf42…` requires guidance from the project owner.
2. **`Debug()` / `Log()` invisibility.** LEAN v2.5.0.0 wraps user
   `Debug()` / `Log()` calls inside `TRACE::`, which must be dropped for
   volume reasons. The model has reduced visibility into happy-path
   algorithm internals.
3. **`infinite_loop` flakiness check.** Spec hints Python's GIL behavior may
   sometimes let the fixture complete before the 900s timeout; single
   observation here was a clean timeout.

## Integration into the parent project

After acceptance, the parent project imports the package directly:

```python
from lean_backtest_tool import run, RunConfig
```

Delete `ui/` first — it has no purpose downstream and pulls in Tkinter
implicitly via `python -m ui.app`. The package itself has only one runtime
dependency, `tiktoken`.
