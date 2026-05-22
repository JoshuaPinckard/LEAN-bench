# `lean_backtest_tool` — Implementation Spec

**Status:** Build standalone. Plugs into the existing main project later as a dependency. The main project already has working backtest invocation, API calls, and orchestration — **do not assume your interface has to match theirs**. Build this as a clean, isolated tool. Integration is a downstream concern handled by whoever wires it in.

**Your job:** build a Python tool that takes a candidate LEAN algorithm and a small runtime config, runs a backtest in Docker against pinned LEAN, and returns a filtered, deterministic log string suitable for handing back to an LLM as feedback. Plus run a specific empirical investigation along the way to resolve four open questions whose answers go into the final spec constants.

This is not a glue script. It is the reference implementation of the F-arm tool in a research benchmark. Its determinism and tag-filtering logic are part of the paper's reproducibility claim. Build it accordingly.

---

## 0. Read this before writing any code

### 0.1 What this tool is and isn't

It **is** a function: `(code, language, runtime_config) → filtered_log_string`.

It **is not**: a backtest orchestrator, a data downloader, a scheduler, a parallelism manager, an LLM-facing API endpoint, a results database, or a frontend. The main project handles all of that. This tool runs one backtest, filters the log, returns a string. Single responsibility.

### 0.2 The reproducibility contract

The same `(code, language, runtime_config)` input must produce a **byte-identical output string** across re-invocations on the same machine and across machines, modulo pinned LEAN behavior. This is non-negotiable. If you can't make it deterministic, the F-arm of the benchmark loses its reproducibility claim. Build with this constraint from day one — don't bolt determinism on at the end.

### 0.3 Greenfield, standalone, no migration

There's no existing tool to maintain compatibility with. Build the cleanest version. The main project will adopt this as a dependency after acceptance; until then you don't owe anything to its conventions.

### 0.4 Empirical work is part of the deliverable

Four decisions in this spec are marked **EMPIRICAL** — they cannot be settled from documentation, they require running LEAN against fixtures and observing behavior. Doing that investigation, recording the findings, and feeding them back into the constants file *is the work*. Don't guess and move on. The findings are also written up in `findings.md` in the repo so the reviewer can audit them.

---

## 1. Settled decisions (do not re-litigate)

| # | Decision | Rule |
|---|----------|------|
| D1 | **LEAN version** | Pin to commit `d2daf42d34a0c97225794e9b1afaef820434db69`. Match the main project. Verify via `lean.json` and a hash test. |
| D2 | **Languages supported** | Python and C#. Two code paths, one external interface. Selected by the `language` input parameter, values `"python"` or `"csharp"`. |
| D3 | **Output shape** | A single string. Filtered LEAN log content + appended synthetic markers (`ORDERS_PLACED: <n>`, `LEAN_RUN_FINISHED` or `TIMEOUT_EXCEEDED` etc.). No structured object. The model parses the string. |
| D4 | **Filter principle** | Tag-based filter using LEAN's own line categorization. Drop `TRACE::` and `STATISTICS::`. Keep `ERROR::`, `DEBUG::`, `Log::`, `Algorithm::`, and any warning category (exact name to be confirmed empirically). **No content-based filtering, no summarization, no relevance ranking within categories.** |
| D5 | **Determinism stripping** | Strip nondeterministic tokens (timestamps, hex memory addresses, container UUIDs, generated paths) via a fixed regex set in `spec_constants.py`. Stripping rules are demonstrably nondeterminism-targeted, not relevance-targeted. The exact regex set comes from empirical work (§5). |
| D6 | **Token cap** | 4000 tokens, tail-truncated. Use `tiktoken` with `cl100k_base` encoding for the count (this is what the agent loop uses upstream, but the choice is fine for this tool too). If truncated, prepend `[TRUNCATED]\n` to the output. |
| D7 | **Per-backtest timeout** | 900 seconds (15 minutes) wall-clock from Docker start to Docker exit. On timeout, kill the container and return the partial log with `TIMEOUT_EXCEEDED: backtest killed after 900s` appended. |
| D8 | **Project directory lifecycle** | Fresh project directory per invocation, deterministic name = `lean_run_<short_hash_of_code>`, created under a configurable workdir, **cleaned up after read**. No state bleed between runs. |
| D9 | **Data provider** | Local only. The tool assumes pre-staged data exists at a configured path; it does not download data. The main project handles data staging. If data is missing for a requested symbol/range, LEAN will fail naturally and the failure surfaces in the log — that's correct behavior. |
| D10 | **`.csproj` policy (C# only)** | Fixed `.csproj` content shipped in the repo, model cannot modify it. Matches LEAN's standard template at the pinned commit. Document this as a known scope choice — real LEAN users can add NuGet packages, our benchmark's models cannot. |
| D11 | **Language-mismatch handling** | Trust the language tag. If the model writes C# in a Python-tagged invocation (or vice versa), let LEAN fail naturally and return whatever LEAN says. Do not pre-detect or pre-validate the code's language. |
| D12 | **Docker resource limits** | `--cpus=2.0 --memory=4g` per container. No parallelism inside the tool — the caller is responsible for parallel orchestration. |
| D13 | **Completion marker** | Tool-appended `LEAN_RUN_FINISHED` when the tool's invocation of LEAN exits without timeout or infrastructure failure. Not LEAN-native — the marker is our synthetic signal. Intentionally uses sequencing language ("finished"), not success language ("completed"): a runtime error in user code still ends with this marker because LEAN itself ran. Models judge algorithm success from `ERROR::` lines and `ORDERS_PLACED`, not from this trailer. |

---

## 2. Repo layout

Build this exact structure:

```
lean_backtest_tool/
  README.md                       # quickstart, install, run-tests, point to findings.md
  pyproject.toml                  # standalone installable package
  findings.md                     # written up at the END, records the four EMPIRICAL results
  docs/
    spec.md                       # this document, committed verbatim
    csproj_template.xml           # the fixed .csproj content (D10)
  lean_backtest_tool/
    __init__.py                   # exports `run()` and the input/output types
    runner.py                     # Docker invocation, project dir lifecycle, timeout
    log_filter.py                 # tag-based filter + determinism stripping
    artifact_reader.py            # parse orders count from results JSON
    tool.py                       # public entry: composes runner + log_filter + artifact_reader
    spec_constants.py             # ALL POLICY: tag set, stripping regexes, token cap, timeout, markers
    exceptions.py                 # tool-specific exception types (DockerUnavailable, etc.)
  tests/
    fixtures/
      python/
        compiles_no_trades.py
        import_error.py
        initialize_error.py
        runtime_error_ondata.py
        compiles_with_trades.py
        infinite_loop.py
      csharp/
        Main_CompilesNoTrades.cs
        Main_CompileError.cs
        Main_InitializeError.cs
        Main_RuntimeError.cs
        Main_CompilesWithTrades.cs
        Main_InfiniteLoop.cs
        QuantConnect.Algorithm.csproj    # the fixed csproj for fixture compilation
    test_runner.py
    test_log_filter.py
    test_artifact_reader.py
    test_determinism.py
    test_tool_e2e.py
    test_pinned_commit.py
    raw_logs/                     # raw log captures from EMPIRICAL phase, committed for audit
      .gitkeep
```

Why `findings.md` separate from `spec.md`: the spec is what the design promised. The findings are what reality showed. Keeping them separate lets a reviewer verify "did you do the empirical work or did you guess." Both ship.

---

## 3. Public interface

This is the contract. Don't deviate.

```python
# lean_backtest_tool/__init__.py
from .tool import run, RunConfig, RunResult

# tool.py
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class RunConfig:
    workdir: str                  # base directory for the fresh per-run project dir
    lean_data_dir: str            # path to pre-staged LEAN data (D9)
    docker_image: str             # full image tag, e.g. "quantconnect/lean:<digest>"
    # No optional fields. If you want a default, configure upstream. Determinism > convenience.

@dataclass(frozen=True)
class RunResult:
    output: str                   # the filtered log string (what the model sees)
    exit_status: Literal["completed", "timeout", "docker_error", "infra_error"]
    # exit_status is for the caller's bookkeeping. It is NOT shown to the model.
    # The model only sees `output`.

def run(code: str, language: Literal["python", "csharp"], cfg: RunConfig) -> RunResult: ...
```

Why `exit_status` exists alongside `output`: the caller (agent loop) needs to know whether to count this as a real iteration vs an infrastructure failure that should be retried. The model gets only `output`; the model must not be able to distinguish "Docker died" from "your code crashed." That distinction belongs to the orchestrator.

---

## 4. Implementation walkthrough

### 4.1 `runner.py`

Responsibilities:
1. Compute the run hash from `code` (sha256, take first 12 chars). Project dir = `<workdir>/lean_run_<hash>`.
2. Create the project dir fresh. If it exists from a prior incomplete run, blow it away and recreate.
3. Write the code:
   - Python: `main.py` at project root.
   - C#: `Main.cs` at project root, plus a copy of `docs/csproj_template.xml` as `QuantConnect.Algorithm.csproj` at project root.
4. Invoke `lean backtest` via Docker. Use the lean-cli's local backtest path. Mount the LEAN data dir. Apply the resource limits from D12.
5. Enforce the timeout from D7. On timeout, send SIGTERM to the container, give it 10 seconds, then SIGKILL. Capture whatever log was written before death.
6. Return the path to the output dir (`<project>/backtests/<timestamp>/`), the raw log file path, the exit code, and the exit_status enum.
7. Do not parse the log. Do not interpret. Just locate the artifacts and hand control to the caller in `tool.py`.

Edge cases to handle explicitly:
- Docker daemon not running → raise `DockerUnavailable`, caller maps this to `exit_status="docker_error"`.
- Output directory never created (e.g., LEAN crashed at process startup) → `exit_status="infra_error"`, return empty raw log.
- Multiple timestamped output dirs in the project dir (shouldn't happen with fresh-dir-per-run, but defensive) → pick the most recent.
- Project dir cleanup: do it in a `try/finally` in `tool.py`, not here. Runner doesn't own lifecycle.

### 4.2 `log_filter.py`

Takes a raw log string, returns a filtered string. Pure function. No I/O.

Algorithm:
1. Split on lines.
2. For each line, identify its tag. The tag is the substring matching `r"(?<=\s)(\w+)::"` near the start of the line (after the timestamp). Lines without a recognized tag are kept by default — see EMPIRICAL #2 below.
3. Drop the line if its tag is in `DROPPED_TAGS` (from `spec_constants.py`).
4. Apply the determinism stripping regex list from `spec_constants.py` to each surviving line.
5. Rejoin.

Critical: tag-filtering is line-level. A multi-line stack trace under an `ERROR::` line — the first line has the tag, subsequent lines do not. Your tag detection must handle continuation lines correctly: a line without a tag inherits the tag of the most recent tagged line. If the most recent tag was kept, keep the continuation; if dropped, drop the continuation. This is the only piece of "structure" you're allowed to infer. Document it.

### 4.3 `artifact_reader.py`

Reads the LEAN backtest results JSON (`<backtest-id>.json` in the output dir) and returns the order count. That's it. No other fields.

If the JSON is missing or malformed: return `None`. The caller treats `None` as "no order info available" and appends `ORDERS_PLACED: unknown` to the output.

Don't over-extend this. Reading order count is the only thing this tool needs from the results artifact. If you find yourself adding more fields, stop — the mechanical checker (separate downstream component) handles richer extraction.

### 4.4 `tool.py`

The composition. Roughly:

```
1. Call runner.run_backtest(code, language, cfg) → returns (raw_log_path, output_dir, exit_status)
2. Read raw_log_path → raw_log_string. (If timeout/infra_error and raw log is partial or missing, use what exists, possibly empty.)
3. Call artifact_reader.read_orders(output_dir) → orders_count or None
4. Call log_filter.filter(raw_log_string) → filtered
5. Append appropriate trailer:
   - exit_status == "completed":  filtered + f"\nORDERS_PLACED: {orders_count}\nLEAN_RUN_FINISHED"
   - exit_status == "timeout":    filtered + "\nTIMEOUT_EXCEEDED: backtest killed after 900s"
   - exit_status == "docker_error" or "infra_error": filtered + "\nINFRASTRUCTURE_ERROR: tool failed to invoke LEAN"
6. Apply token cap (D6) to the entire trailer-included string. If truncated, prepend "[TRUNCATED]\n".
7. Clean up the project dir (D8).
8. Return RunResult(output=..., exit_status=...).
```

Note on truncation ordering: append the trailer *before* truncating. This means on extreme overflow, the trailer line could be lost. That's acceptable — the model can still see the body content. If you truncate first then append, the trailer survives but the relationship between log content and trailer becomes inconsistent. The first ordering is right.

---

## 5. The EMPIRICAL phase — this is half the job

Four open questions. Each requires running fixtures against real pinned LEAN, capturing raw output, and writing findings to `findings.md`.

### EMPIRICAL #1 — The complete tag set

**Question:** What is the exhaustive set of `\w+::` tags LEAN emits in the log at the pinned commit, across both languages and across all failure modes?

**Procedure:**
1. Stand up pinned LEAN in Docker.
2. Run all 12 fixtures (6 Python + 6 C#). Capture the raw `log.txt` for each into `tests/raw_logs/<fixture_name>.log`. **Commit these raw captures to the repo.** They are evidence.
3. Across all 12 raw logs, extract every distinct tag (everything matching `\b\w+::` at the start of a line, after the timestamp).
4. List every distinct tag with: name, example line, which fixture(s) it appears in, your judgment on "is this engine telemetry or user-relevant feedback."
5. Based on that judgment, populate `DROPPED_TAGS` and `KEPT_TAGS` in `spec_constants.py`. Default to keeping anything you're unsure about — false-keep is better than false-drop.

**Where to write the answer:** `findings.md` section "Tag set." Include the full tag inventory with examples.

**What to escalate (do NOT silently decide):**
- A tag whose role you can't determine from observation. Note it as "unclassified" and ask before deciding.
- A tag that appears in some failure modes but not others in an unexpected way.
- Discovery that some failure modes bypass the tagged log infrastructure entirely (e.g., C# compile errors written to a separate file or to stderr without a tag). If this is the case, **the filter design has to change** and you need to escalate before proceeding.

### EMPIRICAL #2 — The C# compile-error path

**Question:** When a C# algorithm has a compile error, does the error message appear in `<backtest-id>-log.txt` with an `ERROR::` tag, or somewhere else? What does it look like? Is there a separate compile-error file? Does it ever go to Docker stderr without being captured by the LEAN CLI?

**Procedure:**
1. Use the `Main_CompileError.cs` fixture — code with a deliberate C# compile error (e.g., undefined symbol, type mismatch).
2. Run it. Capture *everything*: the contents of every file in the output dir, the Docker stdout, the Docker stderr, the exit code, and any other file that gets written.
3. Determine where the compile error lands.

**Three possible outcomes and what each means:**
- **Outcome A:** Compile error lands in the standard log file with `ERROR::` tag. → No special handling needed; the filter just works.
- **Outcome B:** Compile error lands in the standard log file *without* a recognized tag, or with a tag we hadn't planned to keep. → Spec adjusts: add the tag to `KEPT_TAGS`, or handle untagged-line policy.
- **Outcome C:** Compile error lands somewhere other than the standard log file (separate file, stderr only). → Material design change. The tool needs a second log source. **Escalate before implementing — do not silently invent the second source path.**

**Where to write the answer:** `findings.md` section "C# compile error path." Include the raw outputs from Outcome A/B/C, your determination, and exactly which constant(s) you updated as a result.

### EMPIRICAL #3 — The determinism stripping list

**Question:** Across two runs of the same code, which bytes change, and what regex captures each class of nondeterministic token?

**Procedure:**
1. Pick one fixture each from Python and C# — `compiles_no_trades` is good for both, since it produces a moderately verbose log without errors.
2. Run each fixture 5 times. Capture raw log each time.
3. Pairwise diff (run1 vs run2, run2 vs run3, etc.). Every differing token is a nondeterminism source.
4. Classify each diff into a category: timestamp, hex address, UUID, generated path component, run ID, sampled metric, etc.
5. Write a regex for each category. Apply the full regex set to all 5 runs and confirm they are byte-identical after stripping.
6. Document each regex with a comment in `spec_constants.py` showing the example bytes it matches.

**Critical:** if after stripping, runs are *still* not byte-identical, there's a deeper nondeterminism source you haven't classified. Don't ship until they match. If you find a class of nondeterminism that affects the *content* of error messages (not just metadata) — e.g., randomized memory addresses appearing inside user-visible exception text — escalate before deciding how to handle it. Stripping content from error messages crosses the "no relevance filtering" line.

**Where to write the answer:** `findings.md` section "Determinism stripping." Include before/after diffs and the final regex list.

### EMPIRICAL #4 — Warning emissions for silent-failure modes

**Question:** Does LEAN emit recognizable warnings for the common silent-failure modes (subscription resolution issues, indicator-never-warmed-up, zero-position trades)? If so, under what tag?

**Procedure:**
1. Write three small additional fixtures (these don't need to be part of the core fixture set, just temp test cases):
   - Algorithm that subscribes to a symbol with no data available for the date range.
   - Algorithm that uses an indicator with a warmup period longer than the entire backtest range.
   - Algorithm that calls `SetHoldings(symbol, 0)` and never anything else.
2. Run each. Identify any warning-like output in the log.
3. Determine: tag name (if any), whether the warning is consistent and informative, whether dropping it would hide important signal from the model.

**Where to write the answer:** `findings.md` section "Warning emissions." If warnings exist and are useful, add their tag to `KEPT_TAGS`. If they don't exist or aren't informative, document that the tool has no signal for these silent-failure modes — this is a known limitation that affects the paper's claims about what the tool can and can't do.

---

## 6. The fixtures

Each fixture is a minimal LEAN algorithm targeting one specific failure mode. Keep them tiny — five to fifteen lines of substantive content. Same backtest configuration across all fixtures (same date range, same symbol if possible) so they're directly comparable.

### Python fixtures (`tests/fixtures/python/`)

1. **`compiles_no_trades.py`** — Subscribes to SPY, defines `on_data` that does nothing. Runs cleanly, places no trades. The "happy path with no activity" case.
2. **`import_error.py`** — `from nonexistent_module import something` at the top. Fails at import time before `Initialize()` runs.
3. **`initialize_error.py`** — Throws an exception inside `initialize()` (e.g., `raise ValueError("intentional")`). Fails after import but before any market data.
4. **`runtime_error_ondata.py`** — Imports cleanly, initializes cleanly, throws in `on_data` after the first few bars (e.g., division by zero on a specific date).
5. **`compiles_with_trades.py`** — Subscribes to SPY, places a market buy in `on_data` on the first bar. Runs cleanly, places at least one trade.
6. **`infinite_loop.py`** — `while True: pass` inside `on_data`. Exists to test the timeout path.

### C# fixtures (`tests/fixtures/csharp/`)

Same six modes, plus one extra for the compile-error case which doesn't exist in Python:

1. **`Main_CompilesNoTrades.cs`** — Analogue of #1 above.
2. **`Main_CompileError.cs`** — Deliberate compile error (e.g., `private undefined_type _foo;`). **New mode**, only exists in C#. Fixture key for EMPIRICAL #2.
3. **`Main_InitializeError.cs`** — Throws in `Initialize()`.
4. **`Main_RuntimeError.cs`** — Throws in `OnData()`.
5. **`Main_CompilesWithTrades.cs`** — Analogue of #5.
6. **`Main_InfiniteLoop.cs`** — `while (true) { }` in `OnData()`.

Note: there's no C# `import_error` analogue — C# resolves dependencies at compile time, so any "imported thing not found" failure shows up as a compile error and is covered by `Main_CompileError.cs`. Document this asymmetry in `findings.md` so it's visible.

The `.csproj` file shipped at `tests/fixtures/csharp/QuantConnect.Algorithm.csproj` is the same one shipped at `docs/csproj_template.xml`. One canonical content; tests use it.

---

## 7. Test suite

### `test_pinned_commit.py`

Asserts that the LEAN commit hash in `lean.json` (or wherever you configure it) is exactly `d2daf42d34a0c97225794e9b1afaef820434db69`. This test catches version drift, including accidental Docker image bumps.

### `test_runner.py`

Tests the runner in isolation. Mock or use a minimal LEAN invocation:
- Fresh project dir gets created.
- Project dir gets cleaned up after run.
- Timeout triggers when expected.
- Docker-unavailable case raises the right exception.
- Output dir located correctly even with weird timestamp formats.

### `test_log_filter.py`

Tests the filter on synthetic raw-log strings (you write the inputs by hand based on real LEAN format). Doesn't require running LEAN.
- Dropped tags are dropped.
- Kept tags are kept.
- Continuation lines (no tag) inherit the most recent tag's keep/drop decision.
- Determinism regexes strip what they should and don't strip what they shouldn't.
- Empty input returns empty output without crashing.
- Input with no recognized tags is handled gracefully.

### `test_artifact_reader.py`

Synthetic JSON inputs. Verify order counts are extracted correctly. Verify missing/malformed JSON returns `None`.

### `test_determinism.py`

The big one. Runs the same fixture twice (real LEAN, real Docker), asserts byte-identical `RunResult.output`. Run for one Python fixture and one C# fixture. **This test must pass before the spec is considered satisfied.**

If you can't get it passing on your machine, escalate — don't ship.

### `test_tool_e2e.py`

End-to-end against all 12 fixtures. For each:
- Asserts `exit_status` is what you'd expect (`completed`, `timeout`).
- Asserts the output string contains key markers (e.g., `LEAN_RUN_FINISHED` for the success cases, `TIMEOUT_EXCEEDED` for the infinite-loop ones).
- Asserts the output is under the token cap.
- Snapshots the output to a file for manual review (so a reviewer can diff against future runs).

The snapshots are checked in. They serve as regression catches against accidental filter changes.

---

## 8. `findings.md` — what to write up

When the empirical phase is done, `findings.md` exists at the repo root with these sections:

1. **Tag set** — full inventory from EMPIRICAL #1. Table form: `tag | example_line | which_fixtures | kept_or_dropped | rationale`.
2. **C# compile error path** — outcome (A/B/C from EMPIRICAL #2) and resulting design decisions.
3. **Determinism stripping** — the regex set with example bytes for each. Before/after diff snippets.
4. **Warning emissions** — what LEAN does for silent-failure cases, and the tool's stance on them.
5. **Known limitations** — anything you discovered during the empirical phase that affects what the tool can detect or report. Examples that might end up here:
   - "LEAN does not emit a distinguishable signal for X failure mode."
   - "C# compile times average N seconds, contributing meaningfully to per-iteration cost."
   - "The fixture `Main_InfiniteLoop.cs` reliably triggers timeout at 900s; the Python infinite_loop fixture sometimes returns within timeout due to pythonnet GIL behavior — note for spec."
6. **Open questions** — anything you couldn't resolve and need a human decision on.

This document is read by the project owner before the PR merges. If it's missing or thin, the PR isn't done.

---

## 9. Definition of done

A short checklist. All items must pass before requesting review.

- [ ] Repo structure matches §2 exactly.
- [ ] `docs/spec.md` is this document, verbatim.
- [ ] `spec_constants.py` has every constant populated. No `TODO`, no `# fill in later`.
- [ ] All 12 fixtures exist and are correct minimal LEAN algorithms (verify by running each manually once outside the test harness).
- [ ] All four EMPIRICAL investigations are complete, raw log captures are committed under `tests/raw_logs/`, findings are written up in `findings.md`.
- [ ] `test_pinned_commit.py` passes.
- [ ] `test_runner.py`, `test_log_filter.py`, `test_artifact_reader.py` all pass.
- [ ] `test_determinism.py` passes — **byte-identical output across re-runs**, for both Python and C#.
- [ ] `test_tool_e2e.py` passes against all 12 fixtures.
- [ ] `README.md` has install instructions, how to run tests, and a pointer to `findings.md`.
- [ ] No escalation items unresolved in `findings.md` (if any exist, the PR is blocked on getting answers).

---

## 10. What to escalate — do NOT guess

- EMPIRICAL #2 Outcome C (C# compile errors land outside the standard log file). Changes the tool's architecture. Escalate before implementing the second log source.
- EMPIRICAL #3: a class of nondeterminism that affects the content of error messages rather than just metadata. Stripping such tokens crosses the "no content filtering" line and needs sign-off.
- A tag you can't classify after observation. Default to keeping, but flag it in `findings.md` under "Open questions."
- Determinism that can't be achieved even after applying your regex set — a deeper nondeterminism source than expected.
- Discovery that the pinned LEAN commit has a bug or quirk that materially affects what the tool can do (e.g., the version literally doesn't write a log file in some configuration, indicating you should bump pin — but bumping pin is a project-wide decision).
- Docker resource limits causing legitimate algorithms to fail (e.g., the `compiles_with_trades` fixture OOMs with 4GB). May need to revisit D12.

---

## 11. Engineering choices the implementer makes (do NOT escalate these)

These are yours. Pick, document, build. Listed so they're not mistaken for human decisions:

- Exact Docker invocation flavor (subprocess vs `docker` Python SDK vs lean-cli subprocess) — pick what's most reliable on your platform, document the choice.
- Hashing algorithm and length for run-dir names — sha256 first 12 chars is suggested but any deterministic hash with negligible collision risk is fine.
- File I/O patterns (pathlib vs os.path) — your call.
- Test framework (pytest assumed but unittest works too).
- Whether to use `tiktoken` or a different tokenizer for the token cap — `tiktoken` recommended for consistency with the agent loop, but the choice doesn't affect determinism.
- Logging within the tool itself (separate from LEAN's log) — fine to add stdlib `logging` for debugging the tool's own behavior. Not part of the returned output.
- Whether `RunConfig` includes additional optional fields for testing/debugging — fine to add, default behavior must match the spec.

---

## 12. Integration into the main project (FYI, not your job)

This standalone tool gets imported as a package by the main project's agent-loop code. The integration point is one line:

```python
from lean_backtest_tool import run, RunConfig
```

The main project provides `RunConfig` from its own settings, calls `run()`, and feeds the resulting `output` string back into the model's tool-result. That integration is handled by whoever owns the agent loop; it is not part of this PR.

You will not be asked to modify the main project. You will not be asked to match its existing API conventions. The clean interface is the deliverable.

---

## 13. Submission

One PR to the standalone repo. The reviewer will:
1. Read `findings.md` first.
2. Spot-check 2–3 raw log captures against your tag-set determination.
3. Run `test_determinism.py` themselves on their own machine.
4. Skim `spec_constants.py` for sanity.
5. Decide whether the empirical work is solid enough to merge.

If `findings.md` has unresolved escalations, the PR is held until those are answered. Don't try to merge with open questions — that's how the wrong decisions get baked in.
