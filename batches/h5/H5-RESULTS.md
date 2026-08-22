# H5 outcomes (recorded as measured; the pre-stated file is not edited)

Pre-stated prediction: bare-codex ask-rate > 0.3. **REFUTED.**

- bare gpt-5.6-luna, high, BL-01b, n=30 (OpenAI API, served pinned
  30/30): 30 programs, 0 asks. Harnessed comparison (codex CLI, same
  prompt/effort): 0.5 ask-rate (arm 5/10; clean-room 15/30).
- bare gemini-3.6-flash, high, n=30 (Vertex, served pinned 30/30):
  30 programs, 0 asks - matching its harnessed lane (also 0).
- bare claude: pending the CLI freeing (prediction: stays 0).

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
