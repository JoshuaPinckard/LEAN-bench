#!/usr/bin/env bash
# START the study engine - every long-running job, in the owner's priority
# order, at the owner's ~10-in-flight ceiling. Run ONLY on the owner's word.
#
#   bash instruments/engine-start.sh            # throttled profile (default)
#   bash instruments/engine-start.sh full       # full-speed profile
#
# Throttled: bank 1 worker, sonnet 1 cell, codex 1 cell.   (~5 in flight)
# Full:      bank 1 worker, sonnet 3 cells, codex 1 cell + parity queue armed.
# (LEAN at 2 workers measured no clean gain and doubled machine load - 1.)
#
# Companion: instruments/engine-pause.sh stops everything; all jobs resume.
set -u
PROFILE="${1:-throttled}"
LB="C:/Users/joshp/Desktop/LEAN-Bench"
BANK="C:/Users/joshp/Desktop/Options-AI/bank-staging"
LOG="C:/Users/joshp/AppData/Local/Temp"
export LB_CLAUDE_TIMEOUT_MIN=40

# 0. docker daemon must answer, or the bank build writes junk failure rows
if ! docker info >/dev/null 2>&1; then
  echo "REFUSED: docker daemon not reachable - start Docker Desktop first"; exit 2
fi
# 1. same-day canary (UTC-stamped, like generate.js) or the generator refuses
STAMP=$(date -u +%Y-%m-%d)
if [ ! -f "C:/lbres/CANARY-PASS-$STAMP.json" ]; then
  echo "== running today's canary ($STAMP UTC)"
  (cd "$LB" && node instruments/canary.js) > "$LOG/o1-canary.log" 2>&1
  [ -f "C:/lbres/CANARY-PASS-$STAMP.json" ] || { echo "REFUSED: canary did not certify"; exit 3; }
fi

echo "== profile: $PROFILE  $(date)"
# 2. oracle bank (resume-safe; freeze must verify)
(cd "$BANK" && nohup python runner_o1.py --build --workers 1 > "$LOG/o1-bank-build.log" 2>&1 &)
sleep 3
# 3. sonnet lane
SONNET_CONC=1; [ "$PROFILE" = "full" ] && SONNET_CONC=3
(cd "$LB" && nohup node instruments/arm-o1-resume.js claude claude-sonnet-5 max $SONNET_CONC > "$LOG/o1-sonnet-resume.log" 2>&1 &)
sleep 3
# 4. codex core top-offs, serial; parity queue waits behind them (full only)
(cd "$LB" && nohup bash -c 'node instruments/arm-o1-resume.js codex gpt-5.6-luna low 1 && node instruments/arm-o1-resume.js codex gpt-5.6-terra low 1 && node instruments/arm-o1-resume.js codex gpt-5.6-luna medium 1' > "$LOG/o1-codex-topoff.log" 2>&1 &)
if [ "$PROFILE" = "full" ]; then
  sleep 3
  (cd "$LB" && nohup bash instruments/arm-o1-parity-queue.sh > "$LOG/o1-parity-queue.log" 2>&1 &)
fi
sleep 5
echo "== started. status: python instruments/arm-o1-status.py ; ledger: $BANK/bank_o1_results/runs.jsonl"
