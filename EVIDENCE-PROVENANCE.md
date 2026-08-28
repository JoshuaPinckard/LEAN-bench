# Evidence provenance: what is timestamped, where, and by whom

Written 2026-08-28 after discovering that the public repository
(github.com/JoshuaPinckard/LEAN-bench) had not received a push since
2026-07-16 while the study continued locally. This file states, once and
coldly, which artifacts carry which kind of timestamp, so that no priority
claim in the paper exceeds its evidence and none has to be reconstructed
under pressure. Nothing here is backdated; commit dates are the dates the
commits were made.

## Timestamp classes

| class | held by | forgeable by the author? |
|---|---|---|
| A. Public server-side | GitHub (push receipt), OpenAI (cloud task records) | no |
| B. Local version control | this repository's commit objects | yes (author dates) |
| C. Local file records | mtimes, canary certificates, logs | yes |

Only class A supports a priority claim against a third party. Classes B and
C support internal ordering claims and are disclosed as such in the paper.

## What carries class-A evidence

- **2026-07-16** - github.com/JoshuaPinckard/LEAN-bench, last push before
  the study's 2026-08-21 reset. Whatever that tree contains is publicly
  prior to that date.
- **2026-08-23** - github.com/JoshuaPinckard/lean-bench-cloud-run: inventoried
  2026-08-28 and found to contain ONE file, `.gitkeep`. It was an empty
  scaffold for the cloud environment and **timestamps no study material at
  all**. An earlier in-session claim that this push covered the equity-era
  artifacts was wrong and is retracted here; do not cite it.
- **2026-08-22..26** - roughly 1,750 codex-cloud task records held by the
  provider, each containing the frozen prompt text it was launched with and
  the provider's own creation timestamp. The task-id ledger is in
  batches/cloud/. These are third-party records the author cannot edit.
- **2026-08-28 (this push)** - the study repository's first public push
  since the reset: the frozen options-arm donor and variants, fair-reading
  sets, MODELS.md with its expansion amendment, the answer-bank
  specification and its 1,901-run count table, the codebook hashes with
  dated amendments, the P2 experiment, and every draw collected to date.
  The analyses stated in advance in the paper (P1 census aggregate, P3
  options-arm results, P4 modulus) have verifiably NOT been run as of this
  push, so this timestamp precedes their results by construction.

## What carries only class-B/C evidence (and is disclosed as such)

- Every artifact created between 2026-08-23 and 2026-08-28 - the options
  arm, the corpus repair, the oracle-bank reference fixes, the P2
  experiment - until this push lands.
- The P2 hypothesis text preceded the P2 run by ~19 hours on local
  records only. The paper therefore reports P2 as a completed experiment
  whose hypothesis was stated in advance in the manuscript, not as
  externally registered.
- The clean-room canary certificates (C:\lbres\CANARY-PASS-*.json) are
  self-asserted local JSON; the two-sided evidence in them re-derives, but
  their dates do not bind a third party.

## Claims in the paper that need NO timestamp at all

Every quantitative claim re-derives deterministically from frozen
artifacts in this repository: the audit's 3/12 judge matrix (and its 3/12
-> 5/12 -> 8/12 leniency result), the 1/10-6/10-9/10-7/10 edge ladder, the
15/30-vs-0/30 ask asymmetry, the LP infeasibility t*=0.272 with its
certificate and negative control, and the 0/676 contamination marker. A
skeptic verifies these by recomputation, not by trusting a date. The
leniency quote and fail-open behaviour verify against QuantCode-Bench's
own public code at the pinned commit (audit/QuantCode-Bench-COMMIT.txt).

## The one permanent loss

The as-run intermediate values of the obstruction's decontamination history
(t* = 0.392 -> 0.368 before the final 0.272) were produced on unpushed
intermediate grade sets that no longer exist as frozen artifacts. The
sentence reporting them was removed from the paper; the final value and its
negative control reproduce from the frozen grade set with one command.

## Standing rule going forward

Every commit is pushed the day it is made. A day with local commits and no
push is a provenance defect and is reported as one.
