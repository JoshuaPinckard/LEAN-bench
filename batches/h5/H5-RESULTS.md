# H5 outcomes (recorded as measured; the pre-stated file is not edited)

Pre-stated prediction: bare-codex ask-rate > 0.3. **REFUTED.**

- bare gpt-5.6-luna, high, BL-01b, n=30 (OpenAI API, served pinned
  30/30): 30 programs, 0 asks. Harnessed comparison (codex CLI, same
  prompt/effort): 0.5 ask-rate (arm 5/10; clean-room 15/30).
- bare gemini-3.6-flash, high, n=30 (Vertex, served pinned 30/30):
  30 programs, 0 asks - matching its harnessed lane (also 0).
- bare claude (near-bare via --system-prompt), high, n=30: 30 programs,
  0 asks - prediction CONFIRMED. MA defaults from its same 20/50 menu
  (50-leaning in this cell by source-read).

COMPLETE TRIPTYCH (BL-01b, high, n=30/family, one identical system line):
every bare model writes 30/30 programs with zero asks. The entire ask
phenomenon localizes to the codex CLI's agentic layer (0.5 harnessed vs
0.0 bare for the same model, prompt, and effort).

The decomposition this establishes:
- WHAT fills the void is the MODEL: bare-luna silently picks its same
  private default (MA period 200-dominant: 18 of 27 clear reads; 20 x7,
  50 x1) that harnessed luna picks when it commits.
- WHETHER uncertainty surfaces as a question is the HARNESS: the codex
  CLI agentic layer elicits asking (scaling with reasoning effort);
  the bare model, and every other family bare or harnessed, never asks.

Field framing: the interface-design effects of SWE-agent (NeurIPS 2024)
and Terminal-Bench, extended from task performance to epistemic
behavior - the harness decides whether missing information becomes a
question or a silent convention.
