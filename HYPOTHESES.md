# Pre-stated hypotheses — committed before the confirmatory draws

Status: DRAFT for owner review. No confirmatory draw runs until the owner
approves this file and its commit precedes the first draw. Exploratory
sources: the arm (arm/) and the 2026-08-21 clean-room replication
(cleanroom/). All generation under the certified clean room (same-day
canary pass; certificate beside every batch).

## A. The variance study scale-up (n >= 30 per named cell)

H1. **Ask rates rise with reasoning effort where no convention exists.**
    Cells: gpt-5.6-luna and gpt-5.6-terra at low/high/max on BL-01b
    (period withheld), n=30 each. Prediction: ask-rate at max > at low
    for both models (exploratory: luna 0.1->0.9, terra 0.9->1.0).
    Test: one-sided exact test per model, alpha .05.
H2. **The claude family does not ask.** Cells: claude-sonnet-5 and
    claude-opus-5 at high and max on BL-01b, n=30 each. Prediction:
    ask-rate = 0 in every cell (exploratory: 0 in all 24 lanes; 0/30
    replication). Report exact binomial upper bounds.
H3. **The no-ask instruction loses force at maximum effort (codex).**
    Cells: terra max baseline vs terra max with the LiveCodeBench line,
    n=30 each. Prediction: instructed ask-rate at max remains >= 0.5
    (exploratory: 0.9).
H4. **The union carries a convention its parts lack (descent failure).**
    Cells: sonnet high on BL-01b and BL-01c, n=30 each. Prediction: the
    period marginal inside BL-01c differs from BL-01b commits with
    TV >= 0.3 (exploratory: 0.28-0.89 across tiers).
Totals: H1 180 + H2 120 + H3 60 + H4 60 = 420 draws, codex + claude.

## B. The benchmark (the 13 remaining prompts), design of record

Design (the arm's shape, owner default pending his word): 13 frozen
prompts (BL-00, BL-02b', BL-02b, BL-02c, BL-03, BL-04, BL-05, BL-07,
BL-08, OM-B, OM-C, ER-01, ER-01c) x {gpt-5.6-luna, gpt-5.6-terra} x
5 efforts x {base, no-ask} x n=10 = 2,600 draws; gpt-5.6-sol after
(+1,300); claude/gemini on later owner word. Grading: instruments/
bench-grade.py through the verified bank; ask rule as stated in that
file's header. Pre-stated expectations (exploratory basis: the arm):
prompts whose blank has a field convention behave like the type cell
(silent convergence); prompts whose blank is a free parameter behave
like the period cell (private defaults or asks, effort-scaled).
This section is descriptive/exploratory; any confirmatory claim from
the benchmark gets its own pre-stated hypothesis added HERE, before
those draws run.

## C. The audit (QuantCode-Bench), phase 2 configuration of record

Drafters: one per family per the owner's ruling - claude-sonnet-5,
gpt-5.6-terra (medium), gemini flash (surface pending the owner's
funding word). k=3 references per task over the 400-task census;
determinacy = 3/3 agreement, 2/3 -> adjudicate the dissenter; the
pilot-20 is redone under this criterion. The audit's frozen drafting
prompt (audit/prompts/ref_impl_prompt.txt) is used verbatim; the only
change on go is the call layer (per-family surfaces through the clean
room) and REF_MODELS per the ruling - wired only on the owner's go.
