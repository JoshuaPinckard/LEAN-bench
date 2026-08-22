# Methods sources: how the field accesses each vendor (verified 2026-08-21/22)

Verbatim output of the primary-source verification pass (live repos/docs,
fetch date 2026-08-21; pin commit hashes before citing file paths in the
paper). Key corrections it made to our draft understanding:
- LiveCodeBench does NOT use one uniform system prompt across vendors -
  it ships per-family system messages (incl. a Gemini-specific one) and
  its gemini runner uses Vertex AI. Per-family adaptation, disclosed, is
  therefore an accepted practice; our Leg B keeps the stricter
  one-identical-line design (the BigCodeBench / Inspect / HELM pattern).
- SWE-bench Verified has NO vendor-CLI entries; the scaffold+model-as-
  unit convention holds via research scaffolds and commercial agents,
  and its bash-only split is the fixed-scaffold inverse.
- Terminal-Bench benchmarks the vendor CLIs as installed but defaults to
  version "latest"; we pin and record versions per draw, which is
  stricter than the precedent.
- Direct precedent for H5 (same model, bare vs harness): SWE-agent
  (NeurIPS 2024; GPT-4 Turbo 2.67% RAG -> 18.0% full scaffold) and the
  Terminal-Bench paper (same model moving 17 points between harnesses).

---

