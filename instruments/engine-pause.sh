#!/usr/bin/env bash
# PAUSE the study engine: stop every study job and LEAN container. Everything
# is resume-safe; engine-start.sh picks up exactly where this left off.
# Kills by COMMAND-LINE MATCH via PowerShell CIM (wmic's wrapped output made
# the earlier taskkill loops miss live processes - measured 2026-08-27, when a
# "stopped" 2-worker build kept writing junk rows for 15 minutes).
set -u
powershell -NoProfile -NonInteractive -Command '
  $pats = "arm-o1-parity-queue|arm-o1-resume|generate\.js|runner_o1|judge_leniency|bare-cell\.js|multiprocessing-fork"
  $procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $pats }
  foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  $left = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $pats }
  if ($left) { "STILL ALIVE: " + (($left | ForEach-Object ProcessId) -join ",") } else { "study processes stopped (" + ($procs | Measure-Object).Count + " killed)" }
'
for c in $(docker ps --filter "name=lean_cli_" -q 2>/dev/null); do docker stop -t 5 "$c" >/dev/null 2>&1 && echo "stopped container $c"; done
echo "paused $(date)"
