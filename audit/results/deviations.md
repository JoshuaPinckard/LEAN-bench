# Protocol deviations and dispositions (PLAN.md Phase 0 requires logging these)

1. **Task 47 ref2 (sonnet): permanent CLI timeout.** Two runs of 2×900s attempts
   each ended in timeout (2026-07-12). Task 47 was adjudicated on its 2 surviving
   opus references, which had already diverged conclusively (25 vs 2 fills, both
   faithful readings of unpinned ICT/SMC concepts) → INDETERMINATE. A third
   reference could not have changed the verdict.

2. **Task 392: classified on reference-production failure, not tape divergence.**
   Five production attempts failed: ref0 (opus) emitted assumptions but no code;
   ref1 (opus) emitted code truncated mid-method; ref2 (sonnet) timed out 2×900s;
   retry of ref0 hung >2h with empty output and was killed; retry of ref1 never
   started. The spec is a very large multi-timeframe composite (Supertrend + VPT +
   SMA stack across 1D/4H/60m on a single 1h feed per the surviving fragments,
   with 15–20+ declared assumptions in the partial outputs). Disposition:
   **not-determinate (reference-production-failed)** — counted in metric 1's
   denominator, conservative for the headline number. Sensitivity: excluding task
   392 entirely gives metric 1 = 3/19 = 15.8% vs 3/20 = 15.0% — conclusion
   unchanged. It is not counted as INDETERMINATE-by-divergence in the taxonomy.

3. **D4a addendum** (canonical environment defaults; reference models opus×2 +
   sonnet×1) was recorded in PLAN.md after Phase 1 but before any Phase 2
   reference was generated, as noted in the addendum itself.

4. **Judge model** (PLAN.md D8, disclosed there): Sonnet-family via claude CLI —
   their README's endorsed judge family — instead of the gpt-5.4 pinned in their
   run script (unavailable without an API key under the CLI-only constraint).
   CLI cannot pin temperature (their config: 0.0 judge / 0.1 generator).
   Mitigation: stability spot-check showed 0/30 verdict flips.

5. **metrics.py difficulty breakdown**: all three determinate tasks are labeled
   "medium" in the benchmark's own data; earlier interim reports (v3 table)
   mislabeled 249/388 as easy from adjudication-note prose. Final numbers use
   sample_20_final.json labels: determinacy by difficulty easy 0/10, medium 3/6,
   hard 0/4.
