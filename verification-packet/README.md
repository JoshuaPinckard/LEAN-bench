
# Verification packet - read me first

20 draws, sampled with seed 20260823 across the whole study (12 coded,
4 asks-clarifying, 4 other statuses), from the arm AND the benchmark.

Each draw folder holds:
  1-PROMPT.txt ............ the exact text the model saw, with its sha256
  2-MODEL-RESPONSE.txt .... what came back, raw
  3-EXTRACTED-PROGRAM.py .. what the pipeline pulled out to execute
  4-WHAT-THE-PIPELINE-CLAIMED.json ... the status/code on record
  5-CHECK-IT-YOURSELF.txt . one command that re-grades that draw alone

How to use it (about an hour):
  - For coded draws: run the command in file 5 and compare to file 4.
  - For asks draws: read file 2 and judge - did the model ask for the
    missing value, or did it just fail/refuse? Compare to file 4.
  - Write what you find in your own words in FINDINGS-BY-OWNER.md.

IMPORTANT: run these when the study graders are idle. The LEAN engine is
a single shared resource; under load a good program can report exit=1.
The tool now refuses to run during contention rather than mislead you.

Second packet: classifier-check/QUESTIONS.md - 36 model responses with
the decision blanked. Mark ASK or NOT-ASK for each, then open
ANSWERS.json. That measures the ask-classifier against your judgment,
which is the only thing that can validate it.

Note (fixed 2026-08-23, from your catch): the first build of this packet
padded the not-ask side with draws whose program RAN AND FAILED - those
involve no classifier decision at all, which is why full programs were
showing up in an ask/not-ask check. The packet now contains only draws
where no program was extracted, which is the classifier's actual job.
Items tagged [TRUNCATED CODE] are outputs cut off mid-program - skim
them; the ~15 untagged items are the real judgment calls.
