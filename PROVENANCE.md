# Provenance

Every artifact in this repository was imported on 2026-08-21 from the
prior working trees and RE-VERIFIED at import:

- **bank/** (4,086 oracle manifests + spec + runner + data freeze):
  verify_bank.py run fresh at import - 4086/4086 (source copy ==
  manifest, in-container nonce == source nonce, params == job); output
  committed as bank/VERIFY-2026-08-21.txt. Orphan-manifest archive not
  imported (in the sealed history).
- **prompts/** (donor T1v0 + 21 frozen variants + generator): all 21
  SHA-256 hashes recomputed at import, 21/21 match; T1v0 matches its
  pinned hash (6cf7509f...).
- **instruments/** (four arm scripts + grader + drivers): hashed at
  import into HASHES.txt.
- **arm/** (the exploratory lattice study): recounted at import - 2,554
  generation rows, 2,401 graded rows, 2,143 engine-execution artifacts;
  RESULTS.json regenerated from the imported graded rows (all 26
  previously reported lanes identical; 5 lanes newer than the last
  snapshot). Personal account identifiers in the run manifests were
  redacted for this public copy (disclosed in-file); byte-exact
  originals are preserved in the sealed history bundles.
- **cleanroom/** (environment-isolation evidence): calibrated
  channel-forensics results, canary certificates, environment manifest,
  and the 30+30-draw replication of the central finding in the
  instruction-bare room (rates matched the exploratory study exactly).

**Development history** (including a process-heavy period that was
reverted on 2026-08-18 and set aside by owner ruling on 2026-08-21) is
preserved COMPLETE as git bundles, restorable with git clone, in
Desktop/RESEARCH-ARCHIVE-2026-08-21/:

- LEAN-Bench-Research-full-history.bundle
  sha256 5025f79cc5bccac6bb7375ad581546307c7c1ec96c05b3347e73ed1ce0895eda
- LLMDataAcquisition-evidence-tree.bundle
  sha256 e5405fb81b6a3b807a98b57df95af8c31ba7f9361ddb2a549d678cc31914276a

Both bundles were restore-tested at sealing time. The history is not
secret: it is available to any reviewer on request.
