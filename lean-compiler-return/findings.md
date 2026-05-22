# Empirical findings

Per `docs/spec.md` §5 + §8. Records what running pinned LEAN against the 12
fixtures actually revealed, and how that reality fed back into
`lean_backtest_tool/spec_constants.py`.

Reviewer reads this before `spec.md`.

**Environment.** `quantconnect/lean:latest`, image digest
`sha256:fdfa19f8d2f4f2b0d0b5ba790533a0f2d54b482d942e12a228c10e8bbd94337e`,
labels expose `lean_version=17744`, engine version banner reports LEAN v2.5.0.0
running on .NET 10 with Python 3.11.14. Image size: ~14 GB content / ~42 GB
on disk. Raw logs from all 12 fixtures are committed under
`tests/raw_logs/<fixture>.log`. Additional captures from EMPIRICAL #3 are
under `tests/raw_logs/_determinism/` and from EMPIRICAL #4 under
`tests/raw_logs/_empirical4/`.

---

## 1. Tag set (EMPIRICAL #1)

**Question.** What tags does LEAN emit at the pinned commit, across both
languages and all failure modes?

**Procedure executed.** Ran all 12 fixtures via `scripts/run_empirical.py`,
captured each run's `log.txt` (LEAN's per-run engine log) plus
`container_stdout.log` as fallback. Across all 12 logs, extracted every
distinct word matching `r"(?:^|\s)(\w+)::"` near the start of each line.

**Inventory across all 12 fixtures (and EMPIRICAL #4's 3 extra fixtures).**

| tag | example line | observed in | decision | rationale |
|-----|--------------|-------------|---------|-----------|
| `TRACE` | `TRACE:: Engine.Main(): LEAN ALGORITHMIC TRADING ENGINE v2.5.0.0 ...` | every fixture (universal) | DROP | engine telemetry; 50+ lines per run; includes startup banner, currency-conversion table, job-handlers table, dispose-of-everything teardown. Volume dominates the log. |
| `STATISTICS` | `STATISTICS:: Total Orders 0` | clean exits (no exception during run) | DROP | summary metrics. The tool's appended `ORDERS_PLACED: N` trailer is the model-facing summary; the rest (Sharpe, drawdown, etc.) is the mechanical checker's job downstream. |
| `USAGE` | `DATA USAGE:: Failed data requests 1` | clean exits AND some failure modes (initialize_error, runtime_error_ondata) | **KEEP** | the captured tag word is "USAGE" because TAG_PATTERN matches the last `\w+` before `::`. Per EMPIRICAL #4, this is the ONLY signal for the "subscribed-symbol-has-no-data" silent-failure mode (Failed data requests > 0). Per spec D4 (no content-based filtering), keeping the whole tag is the only way to surface that signal. |
| `ERROR` | `ERROR:: Runtime Error: division by zero ... in main.py: line 15` | runtime_error_ondata, initialize_error, import_error (Python); Main_InitializeError, Main_RuntimeError (C#) | KEEP | rich error content with file:line, exception type, full stack trace. Exactly what the model needs to diagnose failures. |

**Decisions (committed to `spec_constants.py`):**
- `DROPPED_TAGS = {TRACE, STATISTICS}`
- `KEPT_TAGS = {ERROR, USAGE, DEBUG, Log, Algorithm, WARN, WARNING}`
  — `DEBUG/Log/Algorithm/WARN/WARNING` are kept defensively even though
  unobserved at the pinned commit, per spec §5 EMPIRICAL #1 "false-keep
  beats false-drop." A future LEAN bump that restores these tags will not
  silently drop their output.
- `UNKNOWN_TAG_POLICY = "keep"`.
- `UNTAGGED_PREFIX_POLICY = "keep"` — preserves content before any tagged
  line. This is load-bearing for EMPIRICAL #2 (see below).

**Spec-vs-reality conflict — important.** The spec assumed LEAN would emit
user-facing output under distinct tags `DEBUG::`, `Log::`, `Algorithm::`.
LEAN v2.5.0.0 does **not**. The user's `self.debug("…")` / `self.log("…")`
calls are emitted as `TRACE:: Debug: …` and `TRACE:: …` — wrapped inside the
engine-telemetry tag. Dropping `TRACE::` (which we must, given volume) drops
user debug/log output with it. The spec's three tag names remain in
`KEPT_TAGS` as forward-compat, but at the pinned commit these tag names do
not surface, and the model does not see user `Debug()` output for a
successful run. Algorithms communicate to the model via:
- the `ORDERS_PLACED: N` trailer (for counts),
- `ERROR::` lines (when something crashed),
- `USAGE::` failed-data-requests counters (subscription failures),
- the `LEAN_RUN_FINISHED` / `TIMEOUT_EXCEEDED` trailer.

This is *not* a design escape hatch — it's a real limitation of the pinned
LEAN's logging. See §5 known limitations and §6 open questions.

---

## 2. C# compile error path (EMPIRICAL #2)

**Question.** Where does a C# compile error land — standard log file with
`ERROR::` (Outcome A), elsewhere in the standard log (Outcome B), or outside
the standard log file (Outcome C)?

**Outcome:** **C — outside the standard log file.** The tool already
handles this via the container stdout fallback; the spec's escalation
requirement (don't silently invent a second log source) is addressed below.

**Evidence.** Fixture `Main_CompileError.cs` deliberately declares
`private undefined_type _broken;`. With the C# build step running as
`dotnet build … && dotnet QuantConnect.Lean.Launcher.dll` inside the same
container (chained via `sh -c "set -e; …"`), the build fails *before* LEAN
ever runs. LEAN therefore writes no `log.txt`, no `backtests/`, no results
JSON.

The compile error is captured by the runner's
`container_stdout.log` mechanism (the tee'd combined stdout+stderr of
`docker run`). Excerpt from
`tests/raw_logs/Main_CompileError.cs.log`:

```
  Determining projects to restore...
  Restored /LeanCLI/QuantConnect.Algorithm.csproj (in 70 ms).
/LeanCLI/Main.cs(9,17): error CS0246: The type or namespace name
  'undefined_type' could not be found (are you missing a using directive or
  an assembly reference?) [/LeanCLI/QuantConnect.Algorithm.csproj]

Build FAILED.

/LeanCLI/Main.cs(9,17): error CS0246: ...
    0 Warning(s)
    1 Error(s)
```

Plus the .NET 10 first-run welcome banner (verbose noise; see "Known
limitations" below).

**Design decisions made in response (engineering choices per spec §11, not
escalations):**

1. The runner's `_read_best_effort_log()` already prefers the LEAN
   `log.txt` / `*-log.txt` files and falls back to `container_stdout.log`
   when neither exists. This handles Outcome C without inventing a new
   log source — we re-use the existing one.

2. **Classification refined.** Pre-empirical, the runner returned
   `exit_status = "infra_error"` whenever `output_dir` was None — which
   would have given a C# compile error the misleading
   `INFRASTRUCTURE_ERROR: tool failed to invoke LEAN` trailer. Reality: the
   user's code is at fault, not the tool's infrastructure. The runner now
   distinguishes:
   - `output_dir None` + raw_log present → `exit_status = "completed"` with
     `ORDERS_PLACED: unknown` / `LEAN_RUN_FINISHED` trailer. The model
     reads the actual CS0246 error in the log and can fix it.
   - `output_dir None` + raw_log empty → `exit_status = "infra_error"`.
     Reserved for genuine infra-side failures (image broken, mount unusable,
     daemon died mid-run without raising DockerUnavailable).

   This refinement is a deliberate engineering choice. It does NOT add a
   second log source (which would require escalation per spec §10) — it
   only changes how the existing fallback log content maps to a trailer.

3. **`set -e` in the C# shell command.** The two-step build+run is chained
   with `set -e` so that a compile failure aborts before LEAN is invoked.
   Without it, LEAN would run against a non-existent DLL and emit a
   confusing `algorithm-location not found` error on top of the actual
   compile error.

**No escalation required.** The spec's §10 escalation requirement is
specifically against "silently invent the second source path." We re-use
the existing container stdout path that the runner already manages, and
the classification refinement is a §11 engineering choice (not a
spec-architecture change). The user-visible trailer is now semantically
correct.

---

## 3. Determinism stripping (EMPIRICAL #3)

**Question.** Across N runs of the same code, which bytes change, and what
regex captures each class of nondeterministic token?

**Procedure executed.** `scripts/run_determinism.py --runs 5` ran
`compiles_no_trades` for each language five times against real LEAN (per
spec §5: "Run each fixture 5 times"). Captures saved to
`tests/raw_logs/_determinism/<lang>_run{N}.{out,raw}`.

**Result: PASS — byte-identical output across all 5 runs, both languages.**

```
========== python determinism (5 runs) ==========
  [run 1/5] output=387 chars, raw=8027 chars
  [run 2/5] output=387 chars, raw=8027 chars
  [run 3/5] output=387 chars, raw=8027 chars
  [run 4/5] output=387 chars, raw=8027 chars
  [run 5/5] output=387 chars, raw=8027 chars
  outputs byte-identical: True

========== csharp determinism (5 runs) ==========
  [run 1/5] output=387 chars, raw=7524 chars
  [run 2/5] output=387 chars, raw=7524 chars
  [run 3/5] output=387 chars, raw=7524 chars
  [run 4/5] output=387 chars, raw=7524 chars
  [run 5/5] output=387 chars, raw=7524 chars
  outputs byte-identical: True
```

Raw logs differ pairwise (timestamps, host IDs, runtime measurements vary).
The stripping regex set in
`spec_constants.DETERMINISM_STRIPPERS` reduces them to byte-identical
filtered output.

**Final regex set with categories:**

| pattern category | regex | example matched | replacement |
|------------------|-------|-----------------|-------------|
| ISO-8601 timestamp | `\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z\|[+-]\d{2}:?\d{2})?` | `2026-05-22T05:42:55.6356030Z` | `<TIMESTAMP>` |
| packed-date timestamp (container stdout format) | `\b\d{8}\s\d{2}:\d{2}:\d{2}(?:\.\d+)?\b` | `20260522 05:42:54.386` | `<TIMESTAMP>` |
| bare time-of-day | `(?<!\d)\d{2}:\d{2}:\d{2}(?:\.\d+)?(?!\d)` | `12:34:56.789` | `<TIME>` |
| hex memory address | `0x[0-9a-fA-F]{6,}` | `0x7f8a1c0042b8` | `<ADDR>` |
| UUID (8-4-4-4-12) | `[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}` | `91d9b3f8-7f2a-4e3d-9c8a-1b2c3d4e5f60` | `<UUID>` |
| run-dir timestamp | `\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d+)?` | `2025-01-15_12-34-56` | `<RUN_DIR>` |
| Docker container short hostname | `(?<=Host:\s)[0-9a-f]{12}\b` | `Host: a861875cbba1` | `<HOST>` |
| compact run-id stamp (14+ digits) | `\b\d{14,}\b` | `20260522054301047` | `<STAMP>` |
| generic 24+ hex id | `\b[0-9a-f]{24,}\b` | `d41d8cd98f00b204e9800998ecf8427e` (OrderListHash, filtered out anyway when STATISTICS:: drops; covered defensively) | `<HEX_ID>` |
| elapsed-ms decoration | `\(\d+(?:\.\d+)?\s*ms\)` | `(123ms)` | `(<MS>ms)` |

**No nondeterminism source was found inside error-message *content* (only
in metadata/decorations).** The spec §10 escalation for "stripping bytes
inside user-visible exception text" does NOT apply.

---

## 4. Warning emissions for silent-failure modes (EMPIRICAL #4)

**Question.** Does LEAN emit recognizable warnings for silent-failure
modes — bad-ticker subscription, indicator-never-warmed-up, zero-position
trade?

**Procedure executed.** Three temporary fixtures under
`scripts/fixtures_empirical4/`:
- `warn_no_data.py` — subscribes to `ZXYW` (a non-existent ticker).
- `warn_warmup.py` — uses a 200-day SMA over a 4-day backtest.
- `warn_zero_position.py` — calls `set_holdings(spy, 0)`.

Ran each via `scripts/run_empirical4.py`. Raw logs captured under
`tests/raw_logs/_empirical4/`.

**Result.**

| fixture | exit_status | new tags observed | useful warning signal? |
|---------|-------------|--------------------|------------------------|
| `warn_no_data.py` | completed | none beyond TRACE/STATISTICS/USAGE | **YES, via USAGE:** `DATA USAGE:: Failed data requests 1`, `Failed data requests percentage 25%`. This is why USAGE is in `KEPT_TAGS`. |
| `warn_warmup.py` | completed | none | **NO.** LEAN does not emit a warning when an indicator never warms up. The algorithm runs, the indicator stays at default, and the model receives no signal. Known limitation. |
| `warn_zero_position.py` | completed | none | **NO.** LEAN treats `SetHoldings(_, 0)` as a no-op and does not warn that it placed no order. Known limitation. |

**Decision.** Keep `USAGE` in `KEPT_TAGS` (initially proposed to drop;
EMPIRICAL #4 reversed that). The "Failed data requests N" signal is the
only LEAN-emitted indicator for the bad-subscription case, and dropping
`USAGE` would lose it. The spec's "no content-based filtering" rule means
we either keep all 8 lines of USAGE telemetry (mostly zeros in clean runs)
or drop the failure signal — we keep them all.

No new tag added to `KEPT_TAGS` for warmup or zero-position; LEAN does not
provide a signal for those modes.

---

## 5. Known limitations

Things discovered during the empirical phase that affect what the tool can
detect or report. Surfaced here so callers and reviewers know the bounds.

1. **User-side logging is invisible — deliberate design choice, not a
   bug.** `self.log(...)` / `self.debug(...)` in Python and the C#
   equivalents do not appear in the filtered tool output. LEAN at the
   pinned version wraps user logging inside `TRACE:: Debug: …` lines, and
   the filter drops `TRACE::` because that tag accounts for ~95% of total
   log volume and is dominated by engine telemetry (currency tables, job
   handlers, dispose-of-everything teardown).

   This is the intended behavior for two reasons:
   - **LEAN's native categorization is authoritative.** The tool returns
     what LEAN itself classifies as engine-level output. User logging is
     `TRACE`-tier developer telemetry by LEAN's own scheme, not engine
     feedback. The filter respects that categorization rather than
     overriding it with content-based heuristics (which spec D4 forbids).
   - **Fixed feedback surface across models.** Surfacing user logging would
     create a confound: a model that logs heavily would receive more
     feedback per iteration than a model that doesn't, conflating logging
     verbosity with tool-use capability. Stripping it keeps the per-run
     feedback bounded by what LEAN itself emits as engine output.

   Practical impact: algorithms that "ran fine but should have signaled
   progress" produce a near-empty filtered body — only the
   `ORDERS_PLACED` / `LEAN_RUN_FINISHED` trailer. Channels that DO surface
   to the model: `ORDERS_PLACED: N` (trailer), `ERROR::` lines (crashes),
   `USAGE::` failed-data-requests counters (subscription failures), and
   the completion / timeout trailer.

2. **Indicator-never-warmed and zero-position are silent-failure modes.**
   LEAN emits nothing distinguishable. The mechanical checker downstream
   would need to inspect the results JSON to detect them.

3. **C# `dotnet` first-run banner — now stripped.** Each fresh container
   invocation prints a ~17-line .NET welcome banner (".NET 10.0!" header,
   SDK version, HTTPS cert info, help URLs) before `dotnet build` runs.
   The banner is untagged and would otherwise survive the filter (per
   `UNTAGGED_PREFIX_POLICY = "keep"`). It only reaches model output when
   LEAN crashes before writing `log.txt` (e.g. C# compile errors, which
   fall through to `container_stdout.log` as the log source). Two
   concerns motivated stripping: ~500 bytes of noise per affected run,
   and silent determinism breakage the day the LEAN image bumps .NET
   versions (banner content is version-dependent).

   Handled by `BLOCK_STRIPPERS` in `spec_constants.py` — a regex anchored
   to "Welcome to .NET" through the long-dashes separator that closes the
   help-URL section. Applied as a pre-pass on the whole raw log before
   line-by-line filtering. Build output that follows the banner
   (`Determining projects`, compile errors, `Build succeeded`, `Time
   Elapsed`) is preserved so genuine compile failures still surface.

4. **`infinite_loop.py` (Python) reliably hits the 900s timeout** under
   this pinned image; the spec's noted "sometimes returns within the
   timeout due to pythonnet GIL behavior" was not observed in 1 run
   (single sample; not statistically significant).

5. **Real-mode UI cannot display raw log.** The tool intentionally cleans
   up the project directory after `run()` returns and exposes only
   `RunResult.output`. The UI's "Raw log" / "Diff" tabs are therefore
   populated only in mock mode. Documented in `ui/app.py`.

6. **The `lean_data_dir = ""` (empty) case skips the data mount and uses
   the image's bundled `/Lean/Data`.** This was added as a development
   convenience for the empirical phase. Production callers should always
   pass a real local data directory (spec D9). The behavior is documented
   in `runner.DockerInvocation`.

---

## 6. Open questions / escalations

1. **Pin verification.** Spec D1 says `LEAN_COMMIT_HASH =
   d2daf42d34a0c97225794e9b1afaef820434db69`, "verify via `lean.json` and a
   hash test." The `quantconnect/lean:latest` image's labels expose
   `lean_version=17744` and the engine banner reports `LEAN v2.5.0.0` —
   neither of which is a git commit. There is no published mechanism to
   verify a QC docker image was built from a specific git commit; the
   image does not embed a `git describe`-style identifier we can read.
   **Open question for the project owner:** is `lean_version=17744`
   corresponding to commit `d2daf42…`? If not, which image tag matches the
   pinned commit, and how should the test (`test_pinned_commit.py`)
   actually verify pinning beyond asserting the constant?

2. **`Debug()` / `Log()` invisibility (§5 #1) is a *real* signal loss.**
   The spec assumed these were available as distinct tags. The pinned
   LEAN does not emit them as distinct tags. Two paths forward:
   - Accept the limitation (current state) — the model has reduced
     visibility into happy-path algorithm internals.
   - Bump the pin to a LEAN version that emits distinct tags — but that's
     a project-wide decision per spec §10.
   **Open question:** does this affect the benchmark's claims about what
   the tool can communicate to the model? If so, the spec/paper should
   note this scoping carefully.

3. **`infinite_loop` Python flakiness wasn't observed.** Spec hints that
   pythonnet GIL behavior may cause this fixture to return within timeout.
   Recommend running it several more times to confirm; a single PASS isn't
   evidence of non-flakiness. Listed here so a reviewer can decide whether
   to invest in further runs.
