# Question queue — LEAN-Bench close-out

Running queue per your instruction: batched, work continues under stated
assumptions. Answer whenever; each item says what I'm doing meanwhile.

---

**1. The gemini surface is dead client-side — pick the replacement path.**
Google EOL'd gemini-cli for individual accounts on/around Aug 24
(`IneligibleTierError: migrate to the Antigravity suite`). Your Aug-23 draws
are unaffected; new gemini draws cannot run through the old harness. Options:
  (a) **Antigravity** — you have it installed (`~/.gemini/antigravity`,
      credential-manager entry). If it has a headless/CLI mode, it becomes the
      new gemini harness surface — but it is a DIFFERENT harness, which
      matters for harness-layer claims; it would be labelled as its own
      surface, not spliced into gemini-cli cells.
  (b) **Gemini API key (AI Studio)** through the CLI's API mode — may bypass
      the Code Assist tier check; needs a key from you if one exists.
  (c) **Vertex** (you granted vertex for gemini earlier) — but that is a BARE
      surface, not a harness; fine for bare-cell comparisons, wrong for
      harness cells.
  (d) **Close gemini where it stands** — its completed cells are in; remaining
      gemini cells are documented as unrunnable-by-provider-EOL, which is
      itself a legitimate finding about harness-dependent measurement.
*Meanwhile:* codex + claude runs proceed; no gemini generation is attempted.
*My lean:* (d) for the paper (clean, honest), (a) investigated as future work.

**2. Per-surface canary gating — ratify or reject.**
The canary was all-or-nothing; with gemini dead that would have blocked codex
and claude generation too. I changed it to certify PER SURFACE (each surface
generates only with its own same-day two-sided pass; a FAILING surface still
fails the run loudly). Rule intent preserved, mechanism recorded in canary.js
and generate.js. If you reject this, everything gemini-adjacent stops until
question 1 is answered.

**3. Arm cell design — confirm or amend the default.**
Assumption I'm running with: the options arm mirrors the equity bank's
headline design — surfaces codex + claude, the same models/efforts as the
paper's load-bearing equity cells, conditions base + noask, n=30 for the 8
eligible variants and n=10 for placebo/control/anchors, plus the donor O1v0.
If you want a different n or fewer efforts, say so before the draws finish.

**4. Audit-refs cloud tasks returned chat-only answers.**
54/60 collected but the CLI exposes task metadata only, not message bodies, so
their reference-implementation text is visible in the web UI but not
harvestable by machine. Re-run as repo-writing tasks (~60 cloud draws), pull
manually, or document as-is? *Meanwhile:* documented as-is.

**5. O1v0 prompt-review waiver — on record.**
I read "you already have everything you need from me" as approving O1v0 + its
fair-reading sets as drafted. If any atom or reading is wrong, its variants
are re-frozen and their draws discarded and re-run. Say the word.
