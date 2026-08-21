# LEAN-Bench

Measuring what language models do with trading-strategy specifications:
complexity does not break them; missing information does; and when the
missing piece is a convention, this repository measures what fills it.

One paper, three parts:
1. **Structural complexity saturates** — escalating requirement ladders
   (to 26 requirements, 73-node cascades, depth-3 grammars) do not break
   frontier models (July 2026 corpus, 148 runs).
2. **Information gaps do** — a short prompt whose difficulty is an
   unstated platform fact produces failure, and pass rates climb
   monotonically as the missing information is restored one sentence at
   a time (the semantic edge; dose-response 1/10 → 6/10 → 9/10).
3. **Conventions and the void** — deleting single specification atoms
   and executing what models write against a precomputed oracle bank:
   where the field has a convention (a bare "moving average"), every
   model family resolves it identically and silently; where it has none
   (the period), models either hold stable private defaults or refuse to
   guess, increasingly with reasoning effort.

## How this repository works
- **Small instruments.** Generation, extraction, engine grading, and
  tabulation are a handful of short scripts (`instruments/`). Read them.
- **Deterministic grading.** Every generated program is executed in a
  pinned LEAN engine image and compared to a precomputed, hash-verified
  oracle bank (`bank/`). No language model grades anything.
- **Frozen prompts.** Every prompt is byte-frozen with a SHA-256
  (`prompts/`, `HASHES.txt`).
- **Instruction-bare generation.** All model generation runs in a
  measured clean room: an environment manifest (no instruction files
  reachable, allowlisted variables) plus a calibrated planted-marker
  canary that must pass the same day, before and after each batch. The
  generator refuses to run without it. Certificates ship beside the data.
- **Provenance.** `PROVENANCE.md` records where every imported artifact
  came from, how it was re-verified on import, and the checksums of the
  sealed development-history bundles (preserved, available on request).
