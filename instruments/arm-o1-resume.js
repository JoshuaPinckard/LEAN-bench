'use strict';
// Resume the options-arm draw lanes: run every cell short of target, stopping
// the moment a provider blocks us.
//
//   node instruments/arm-o1-resume.js codex gpt-5.6-luna medium [concurrency]
//   node instruments/arm-o1-resume.js claude claude-sonnet-5 max 6
//
// Concurrency is per CELL, never within one: each child owns its own lane file
// and its own per-draw temp dir, so two children cannot write the same row.
// Default 1, capped at 10 (the owner's ceiling, 2026-08-27).
//
// BATCH ROLLOVER: generate.js folders batches by the UTC date, which rolls at
// 17:00 local in this timezone - so an afternoon lane resumes into a NEW, empty
// folder and would redraw every cell from index 0. This driver counts what
// EVERY batch folder already holds for a cell and asks generate.js only for the
// shortfall, so the folders pool correctly instead of double-weighting. (The
// canary stamp rolls the same way, and that is left alone: a fresh same-day
// canary is the safety rule, not an inconvenience.)
//
// generate.js exits 3 on a provider block (quota / sign-in / rate limit). That
// STOPS THE LANE rather than skipping the cell: continuing would bank provider
// messages against every remaining cell, which is how 59 claude-sonnet draws
// were poisoned on 2026-08-27.
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const REPO = path.resolve(__dirname, '..');
const [SURFACE, MODEL, EFFORT, CONC_STR] = process.argv.slice(2);
const CONCURRENCY = Math.max(1, Math.min(10, parseInt(CONC_STR || '1', 10)));
if (!SURFACE || !MODEL || !EFFORT) {
  console.error('usage: arm-o1-resume.js <surface> <model> <effort> [concurrency]');
  process.exit(2);
}

const ELIGIBLE = new Set(['O1e1', 'O1e2', 'O1e3', 'O1e4', 'O1e5', 'O1e6', 'O1e7', 'O1e8']);
const ANCHORS = new Set(['O1a1', 'O1a2', 'O1c1']);
const PROMPTS = ['O1v0', 'O1a1', 'O1a2', 'O1c1', 'O1p1',
  'O1e1', 'O1e2', 'O1e3', 'O1e4', 'O1e5', 'O1e6', 'O1e7', 'O1e8'];

function target(pid) {
  // REGISTERED targets (arm-options/MODELS.md): eligible 30 per condition,
  // anchors 20, donor/pins 10. An earlier 60 here made luna_medium overdraw
  // (kept as extra data) and doubled sonnet's apparent remaining work.
  if (ELIGIBLE.has(pid)) return 30;
  if (ANCHORS.has(pid)) return 20;
  return 10;
}

const BATCHES = path.join(REPO, 'batches');
const TODAY = new Date().toISOString().slice(0, 10);
const safeModel = MODEL.replace(/[^\w.-]/g, '');

function cellFile(dir, pid, cond) {
  const suffix = cond === 'noask' ? '_noask' : '';
  return path.join(dir, SURFACE + '_' + safeModel + '_' + EFFORT + '_' + pid + suffix + '.jsonl');
}

function countUsable(file) {
  if (!fs.existsSync(file)) return 0;
  let n = 0;
  for (const l of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!l.trim()) continue;
    let j;
    try { j = JSON.parse(l); } catch (e) { continue; }
    // Only a committed program or a genuine model answer counts.
    // harness-error and provider-blocked carry no observation.
    if (j.status === 'program' || j.status === 'no-program') n++;
  }
  return n;
}

function usableEverywhere(pid, cond) {
  let total = 0, inToday = 0;
  for (const d of fs.readdirSync(BATCHES)) {
    const dir = path.join(BATCHES, d);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) continue;
    if (!fs.statSync(dir).isDirectory()) continue;
    const n = countUsable(cellFile(dir, pid, cond));
    total += n;
    if (d === TODAY) inToday = n;
  }
  return { total: total, inToday: inToday };
}

const todo = [];
for (const pid of PROMPTS) {
  for (const cond of ['base', 'noask']) {
    const seen = usableEverywhere(pid, cond);
    const want = target(pid);
    if (seen.total < want) {
      // N is what TODAY's folder must reach: what it already holds plus the
      // shortfall across all folders. generate.js resumes within its own file.
      todo.push({ pid: pid, cond: cond, have: seen.total, want: want,
                  askFor: seen.inToday + (want - seen.total) });
    }
  }
}

if (!todo.length) {
  console.log(MODEL + '/' + EFFORT + ': every cell already at target - nothing to resume');
  process.exit(0);
}
console.log(MODEL + '/' + EFFORT + ': ' + todo.length + ' cells short, concurrency ' + CONCURRENCY);
for (const t of todo) {
  console.log('  ' + t.pid + ' ' + t.cond + ' ' + t.have + '/' + t.want +
              ' (drawing to ' + t.askFor + " in today's folder)");
}

if (process.argv.includes('--dry-run')) {
  console.log('DRY RUN - no draws launched');
  process.exit(0);
}

let blocked = false, next = 0, active = 0, failures = 0;

function runOne(t, done) {
  const args = ['instruments/generate.js', SURFACE, MODEL, EFFORT, t.pid, String(t.askFor)];
  if (t.cond === 'noask') args.push('noask');   // generate.js: argv.includes('noask')
  console.log('== start ' + t.pid + ' ' + t.cond + ' (' + t.have + '/' + t.want + ')');
  const child = spawn(process.execPath, args, { cwd: REPO, stdio: 'inherit' });
  child.on('close', function (code) {
    if (code === 3) {
      blocked = true;
      console.error('PROVIDER BLOCKED on ' + t.pid + ' ' + t.cond + '. Not starting new cells.');
    } else if (code !== 0) {
      failures++;
      console.error('cell ' + t.pid + ' ' + t.cond + ' exited ' + code);
    } else {
      console.log('== done  ' + t.pid + ' ' + t.cond);
    }
    done();
  });
}

function pump() {
  while (!blocked && active < CONCURRENCY && next < todo.length) {
    const t = todo[next++];
    active++;
    runOne(t, function () { active--; pump(); });
  }
  if (active === 0) {
    if (blocked) {
      console.error('\nSTOPPED: provider blocked. Re-run once it recovers; every '
        + 'cell is resume-safe and blocked rows are never counted.');
      process.exit(3);
    }
    console.log('\nRESUME PASS COMPLETE (' + failures + ' cell(s) exited non-zero)');
  }
}
pump();
