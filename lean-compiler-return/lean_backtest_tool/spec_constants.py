"""ALL POLICY for the tool.

Every decision the spec calls out as a fixed parameter lives here. The rest of
the package reads these constants — nothing else should hard-code policy.

Initial values reflect spec defaults (D1, D4, D6, D7, D13). Values marked
EMPIRICAL are refined by the investigation in findings.md and the relevant
constants are updated in place when that work completes.
"""
import re

# ---------------------------------------------------------------------------
# D1 — pinned LEAN commit.
# Any LEAN Docker image used by the tool must be built from this commit.
# test_pinned_commit.py asserts the runner is pointed at this hash.
# ---------------------------------------------------------------------------
LEAN_COMMIT_HASH: str = "d2daf42d34a0c97225794e9b1afaef820434db69"

# Docker image tag is configured per-call via RunConfig.docker_image so the same
# tool binary can be repointed at different builds for QA. The default below is
# pinned by sha256 digest so callers that don't override get reproducible runs
# matching the digest used by test_determinism.py during empirical validation.
# See findings.md §"Pinned image digest" for the engine version this maps to.
DEFAULT_DOCKER_IMAGE: str = (
    "quantconnect/lean@sha256:"
    "fdfa19f8d2f4f2b0d0b5ba790533a0f2d54b482d942e12a228c10e8bbd94337e"
)

# ---------------------------------------------------------------------------
# D6 — token cap on the returned string.
# Tail-truncate. If truncated, prepend the marker below.
# ---------------------------------------------------------------------------
TOKEN_CAP: int = 4000
TOKEN_ENCODING: str = "cl100k_base"
TRUNCATION_MARKER: str = "[TRUNCATED]\n"

# ---------------------------------------------------------------------------
# D7 — per-backtest wall-clock timeout, seconds.
# ---------------------------------------------------------------------------
TIMEOUT_SECONDS: int = 900
SIGTERM_GRACE_SECONDS: int = 10

# ---------------------------------------------------------------------------
# D12 — Docker resource limits.
# ---------------------------------------------------------------------------
DOCKER_CPUS: str = "2.0"
DOCKER_MEMORY: str = "4g"

# ---------------------------------------------------------------------------
# D13 — synthetic trailer markers appended by the tool (not LEAN-native).
#
# The completion marker is intentionally LEAN_RUN_FINISHED rather than
# BACKTEST_COMPLETED: "finished" is sequencing language (the tool's
# invocation ended without timeout or infra failure) and does NOT imply the
# algorithm itself ran error-free. Models parsing the output should look at
# ERROR:: lines and ORDERS_PLACED to judge algorithm success — the trailer is
# the tool's exit-status signal, not a quality verdict on the user's code.
# ---------------------------------------------------------------------------
TRAILER_COMPLETED_TEMPLATE: str = "\nORDERS_PLACED: {orders}\nLEAN_RUN_FINISHED"
TRAILER_TIMEOUT: str = f"\nTIMEOUT_EXCEEDED: backtest killed after {TIMEOUT_SECONDS}s"
TRAILER_INFRA_ERROR: str = "\nINFRASTRUCTURE_ERROR: tool failed to invoke LEAN"
TRAILER_ORDERS_UNKNOWN: str = "\nORDERS_PLACED: unknown\nLEAN_RUN_FINISHED"

# ---------------------------------------------------------------------------
# D4 — tag-based filter sets. EMPIRICAL #1 finalizes these.
#
# Tags are LEAN's own line categorization, e.g. "ERROR::", "DEBUG::", "TRACE::".
# Lines without a recognized tag inherit the tag of the most recent tagged line
# (continuation lines under a stack trace, etc.); see log_filter.py.
#
# The initial sets below reflect the spec's stated principle:
#   - drop engine telemetry (TRACE, STATISTICS)
#   - keep user-relevant feedback (ERROR, DEBUG, Log, Algorithm, warnings)
# Empirical work refines this; updates go in findings.md "Tag set".
# ---------------------------------------------------------------------------
DROPPED_TAGS: frozenset = frozenset({
    "TRACE",
    "STATISTICS",
})

KEPT_TAGS: frozenset = frozenset({
    "ERROR",
    # EMPIRICAL #4: "DATA USAGE::" lines (tag captured as "USAGE" per
    # TAG_PATTERN) are the ONLY signal for the "subscribed symbol has no
    # data" silent-failure mode — they show "Failed data requests N > 0"
    # when LEAN couldn't resolve a subscription. The spec's D4 forbids
    # content-based filtering within a category, so keep the whole USAGE
    # tag rather than try to keep only the failure-percentage lines. See
    # findings.md §4.
    "USAGE",
    # Spec-anticipated tags that the pinned LEAN version does NOT emit, but
    # we keep them in case a future bump restores them. Per spec §5
    # EMPIRICAL #1: false-keep > false-drop.
    "DEBUG",
    "Log",
    "Algorithm",
    "WARN",
    "WARNING",
})

# Policy for lines that have a tag we have never seen before in fixtures.
# Per spec §5 EMPIRICAL #1: "Default to keeping anything you're unsure about —
# false-keep is better than false-drop." Honoring that here.
UNKNOWN_TAG_POLICY: str = "keep"  # "keep" | "drop"

# Policy for the first lines of the file, before any tagged line has appeared.
# Such lines have no tag and no predecessor — keep them to preserve startup
# context (banner / version line / etc.).
UNTAGGED_PREFIX_POLICY: str = "keep"  # "keep" | "drop"

# Regex used by log_filter.py to extract the tag from a line. The capture group
# is the tag name without the trailing "::". Anchored to either start-of-line
# or whitespace boundary so timestamps and log-level prefixes don't confuse it.
TAG_PATTERN: re.Pattern = re.compile(r"(?:^|\s)(\w+)::")

# ---------------------------------------------------------------------------
# D5 — determinism stripping regex set. EMPIRICAL #3 finalizes this.
#
# Each entry: (pattern, replacement). Applied in order. Patterns target
# nondeterministic *metadata* only — never the content of error messages.
# Adding a pattern that strips bytes inside an exception's user-visible text
# requires escalation (spec §10).
#
# Initial set covers the categories that are universally nondeterministic in
# any LEAN run: wall-clock timestamps, hex addresses, UUIDs, generated
# timestamp-bearing path components, and ephemeral Docker container IDs.
# ---------------------------------------------------------------------------
# Block-level strippers — applied to the WHOLE raw log BEFORE line-splitting,
# unlike DETERMINISM_STRIPPERS which run per-line. Use this list when a pattern
# spans multiple lines or removes a whole logical block. Each entry is
# (pattern, replacement); patterns can match across lines.
#
# Rationale: the C# build path (compile errors, infra issues) falls through to
# container_stdout.log as the log source, which includes a ~17-line .NET
# runtime welcome banner. The banner content is version-dependent (.NET 10 vs
# .NET 11 etc.) and would silently break determinism the day the LEAN image
# bumps .NET versions. We strip the banner block entirely; the build output
# (Determining/Restored/compile errors/"Build succeeded"/"Time Elapsed") that
# follows the banner is preserved so genuine compile failures still surface.
BLOCK_STRIPPERS: tuple = (
    # .NET runtime welcome banner. Shape (matched structurally so .NET version
    # bumps don't slip through):
    #   Welcome to .NET 10.0!
    #   ---------------------
    #   SDK Version: 10.0.101
    #   <blank>
    #   ----------------
    #   Installed an ASP.NET Core HTTPS development certificate.
    #   ...help URLs...
    #   ----------------
    #   ...more help URLs...
    #   --------------------------------------------------------------------------------------
    # Anchors: opens with "Welcome to .NET <anything>" line; closes with the
    # long-dashes separator (60+ dashes). The non-greedy middle absorbs the
    # intervening help text regardless of which .NET version's wording is used.
    (re.compile(r"Welcome to \.NET[^\n]*\n(?:.*\n)*?-{60,}\n"), ""),
)

DETERMINISM_STRIPPERS: tuple = (
    # ISO-8601 timestamps with optional T/space + fractional + zone:
    #   "2025-01-15 12:34:56.789", "2026-05-22T05:42:55.6356030Z"
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "<TIMESTAMP>"),
    # Packed-date timestamp emitted by the LEAN container's stdout when the
    # engine isn't using its file logger: "20260522 05:42:54.386".
    (re.compile(r"\b\d{8}\s\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"), "<TIMESTAMP>"),
    # Bare time-of-day: "12:34:56.789"
    (re.compile(r"(?<!\d)\d{2}:\d{2}:\d{2}(?:\.\d+)?(?!\d)"), "<TIME>"),
    # Hex memory / object addresses: "0x7f8a1c0042b8"
    (re.compile(r"0x[0-9a-fA-F]{6,}"), "<ADDR>"),
    # UUIDs (canonical 8-4-4-4-12).
    (re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<UUID>"),
    # Backtest output dir names: "2025-01-15_12-34-56" or similar.
    (re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d+)?"), "<RUN_DIR>"),
    # Docker container short hostname (12 hex chars) in 'Host: <hex>' lines.
    (re.compile(r"(?<=Host:\s)[0-9a-f]{12}\b"), "<HOST>"),
    # Compact run-id stamps like "20260522054301047" embedded in filenames
    # or path-like fragments emitted in the log.
    (re.compile(r"\b\d{14,}\b"), "<STAMP>"),
    # Generic run / backtest id (24+ hex chars on their own).
    (re.compile(r"\b[0-9a-f]{24,}\b"), "<HEX_ID>"),
    # Elapsed-time decorations like " (123ms)" added by some loggers; normalize.
    (re.compile(r"\(\d+(?:\.\d+)?\s*ms\)"), "(<MS>ms)"),
)

# ---------------------------------------------------------------------------
# Project directory naming.
# Fresh dir per invocation; deterministic name = hash of code; cleaned up
# after the result is read (D8).
# ---------------------------------------------------------------------------
PROJECT_DIR_PREFIX: str = "lean_run_"
PROJECT_DIR_HASH_LEN: int = 12
