# Cloud draw collection - 2026-08-25

2,162 tasks were launched across the four cloud environments during the
2026-08-23 quota window (commit f20f6db). Collected 2026-08-25, after both
accounts' quotas reset.

## Result

- **2,161 / 2,161 collectable draws collected.** Statuses: ~1,700 program /
  ~460 no-program before grading (exact per-cell counts in the
  `.collected.jsonl` files; the split is model behaviour, not plumbing - the
  fully specified donor T1v0 collects as programs, no-ask cells comply).
- **BL-01c#28** (task_e_6a8b2452363c8321be34d2c0fdb46423): stuck PENDING since
  launch, never finished. Excluded under the fairness rule (draws the model
  never finished do not count); its launch row remains on disk.
- **6 auditref rows** carried no task_id (launch failures during the window) -
  there was never anything to collect.

## Integrity notes (what went wrong and how it was caught)

1. The original cloud-collect.js queried every task under whatever CODEX_HOME
   the shell had. A task queried under the wrong account returns 404, which
   would have been written as a `no-program` envelope - a FALSE REFUSAL graded
   into the paper. Fixed before any harvest: tasks route to their launching
   account via the `env` field in each ledger row.
2. The first fixed harvest was poisoned anyway: the account paths were patched
   in via a shell heredoc that collapsed backslashes, so CODEX_HOME pointed
   nowhere and every status call answered "Not signed in" - and the
   unreachable-guard did not list that signature, so 1,673 envelopes carried
   the error text as data. Caught by a magnitude check (the fully specified
   donor cannot be 100% no-program), 1,583 poisoned envelopes purged by exact
   error-text match, 90 genuine window-era rows kept, guard extended
   (Not signed in / codex login / PATH-alias warnings = unreachable, never
   data), paths rewritten as forward slashes.
3. Three ledgers (dose_E1, efamily, auditrefs) carry their own schemas; the
   generic collector now skips them and cloud-collect-special.js collects them
   with every original row field preserved.
4. Transient http errors during the drain (rate limiting across ~4,000 calls)
   were held as unreachable-stays-queued and drained over 15 passes.

Every envelope in the `.collected.jsonl` files traces to a launch row with its
env, prompt hash, and task id. Verification: zero rows contain the
"Not signed in" signature; per-cell status distributions pass the
magnitude smell test that caught failure (2).
