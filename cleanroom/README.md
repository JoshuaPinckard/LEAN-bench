# The clean-room evidence (2026-08-21)

The contamination question ("did machine-local agent-instruction files
shape the findings?") was settled two-sided on 2026-08-21:

1. Channel forensics with calibrated detectors (isolation-*.json): each
   CLI reads instruction files from exactly its home directory and the
   working directory - planted markers FIRE there (calibration) - and
   from nowhere else: no ancestor-directory walk, no environment
   variables. The historical lanes had both read-locations empty or
   redirected, recorded per-draw.
2. Behavioral replication (luna_high.jsonl, sonnet_high.jsonl): the
   central asymmetry replicated exactly in a certified instruction-bare
   room (ENV-MANIFEST + CANARY certificates): luna/high asked 15/30
   (0.50, original 0.50); sonnet/high asked 0/30 (0.00, original 0.00).

Rule going forward: no generation without a same-day calibrated canary
pass; certificates ship beside every batch.
