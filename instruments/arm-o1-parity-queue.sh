#!/usr/bin/env bash
# Parity-lane queue (owner expansion 2026-08-28). Waits for the core top-off
# chain to finish, then runs the 8 parity codex lanes serially, then the two
# bare cells. Cloud ladder is NOT auto-launched (routing traps; manual last).
set -u
cd "C:/Users/joshp/Desktop/LEAN-Bench"
export LB_CLAUDE_TIMEOUT_MIN=40

# wait until no codex resume driver is running (the core top-offs)
while powershell -NoProfile -Command \
  "exit [int]((Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { \$_.CommandLine -match 'arm-o1-resume.js codex' } | Measure-Object).Count -eq 0)"; do
  sleep 120
done
echo "core top-offs done; starting parity lanes $(date)"

for lane in "terra medium" "luna high" "terra high" "luna xhigh" "terra max" "luna max" "sol low" "sol medium"; do
  set -- $lane
  echo "== parity lane gpt-5.6-$1 $2 $(date)"
  node instruments/arm-o1-resume.js codex "gpt-5.6-$1" "$2" 1
  rc=$?
  if [ $rc -eq 3 ]; then echo "PROVIDER BLOCKED - stopping queue; rerun to resume"; exit 3; fi
done

echo "== bare cells $(date)"
for pid in O1v0 O1a1 O1a2 O1c1 O1p1 O1e1 O1e2 O1e3 O1e4 O1e5 O1e6 O1e7 O1e8; do
  case $pid in O1e*) n=30;; *) n=10;; esac
  node instruments/bare-cell.js openai gpt-5.6-luna high $n $pid || echo "bare openai $pid rc=$?"
done
for pid in O1v0 O1a1 O1a2 O1c1 O1p1 O1e1 O1e2 O1e3 O1e4 O1e5 O1e6 O1e7 O1e8; do
  case $pid in O1e*) n=30;; *) n=10;; esac
  node instruments/bare-cell.js claude claude-sonnet-5 high $n $pid || echo "bare claude $pid rc=$?"
done
echo "PARITY QUEUE COMPLETE $(date); cloud ladder remains (manual)"
