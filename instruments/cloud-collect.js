'use strict';
// Collect finished Codex Cloud draws (run later, costs no quota window).
//   node cloud-collect.js
// For every launched task: read its status, pull its diff (the program the
// agent wrote) or its final message (an ask / refusal), and write an envelope
// in the SAME shape the local lanes produce, so bench-grade.py can grade it
// with no special-casing.
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const CODEX_JS = process.env.LB_CODEX_JS || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\bin\\codex.js';
const DIR = path.join(REPO_ROOT, 'batches', 'cloud');

// A cloud task is visible ONLY to the account that launched it. Querying with
// the wrong account returns "404 Not Found" - and the old code would have
// written that error text into an envelope as status 'no-program', i.e. a
// FALSE refusal graded into the paper. Route every task to its launching
// account via the env recorded in its ledger row, and treat any
// cannot-see-the-task response as UNREACHABLE: skipped, never an envelope.
// NOTE 2026-08-25: these paths were once patched in via a shell heredoc that
// collapsed the backslashes; JS string escapes then ate the single ones, so
// CODEX_HOME pointed nowhere, every status call answered "Not signed in", and
// 1,673 envelopes were written with that error text as data - because the
// unreachable() guard below did not list that signature either. Both fixed;
// paths are forward-slash (Windows accepts them and they cannot be eaten).
const ENV_HOME = {
  '6a8b227882848191a9c3c07b03bac026': 'C:/Users/joshp/AppData/Roaming/ToolsEnabled/capability/codex-homes/cloud-a',
  '6a8b2d070c9481918ec92aaef133bc9d': 'C:/Users/joshp/AppData/Roaming/ToolsEnabled/capability/codex-homes/cloud-a',
  '6a8b1cfcff788191902ea36cc5738f5e': 'C:/Users/joshp/AppData/Roaming/ToolsEnabled/capability/codex-homes/cloud-b',
  '6a8b2ca0f0bc81918132b16266cc192e': 'C:/Users/joshp/AppData/Roaming/ToolsEnabled/capability/codex-homes/cloud-b',
};
const unreachable = t => /404 Not Found|Not signed in|codex login|401|403|usage limit|rate.?limit|429|http error|ECONNRESET|ETIMEDOUT|could not create PATH aliases/i.test(t || '') || !(t || '').trim();

function codex(args, home) {
  const env = Object.assign({}, process.env);
  if (home) env.CODEX_HOME = home;
  const r = spawnSync(process.execPath, [CODEX_JS, ...args], { encoding: 'utf8', shell: false, timeout: 5 * 60 * 1000, maxBuffer: 64 * 1024 * 1024, env });
  return (r.stdout || '') + (r.stderr || '');
}

function extractProgram(text) {
  if (!text) return null;
  // a repo agent writes files: take python from the diff's added lines
  const added = text.split('\n').filter(l => /^\+/.test(l) && !/^\+\+\+/.test(l)).map(l => l.slice(1)).join('\n');
  const body = /QCAlgorithm/.test(added) ? added : text;
  const fences = [...body.matchAll(/```(?:python)?\s*\n([\s\S]*?)```/g)].map(m => m[1]);
  const withQC = fences.filter(f => /QCAlgorithm/.test(f));
  const pick = (withQC.length ? withQC : fences).sort((a, b) => b.length - a.length)[0];
  if (pick) return pick;
  return /class\s+\w+\s*\(\s*QCAlgorithm\s*\)/.test(body) ? body : null;
}

for (const f of fs.readdirSync(DIR).filter(x => x.startsWith('cloud_') && x.endsWith('.jsonl') && !x.includes('collected'))) {
  const src = path.join(DIR, f);
  const outPath = path.join(DIR, f.replace('.jsonl', '.collected.jsonl'));
  const done = new Set();
  if (fs.existsSync(outPath)) for (const l of fs.readFileSync(outPath, 'utf8').split('\n')) if (l.trim()) done.add(JSON.parse(l).i);
  const launches = fs.readFileSync(src, 'utf8').split('\n').filter(x => x.trim()).map(JSON.parse);
  // Ledgers from the dose/efamily/auditref drivers carry their own schemas
  // (spec_id/arm, family, audit_task_id) - collecting them here would write
  // envelopes labelled prompt_id: undefined. They belong to
  // cloud-collect-special.js, which preserves their fields.
  if (launches.length && !('prompt_id' in launches[0])) { console.log(`${f}: foreign schema - left to cloud-collect-special.js`); continue; }
  for (const L of launches) {
    if (done.has(L.i) || !L.task_id) continue;
    const home = ENV_HOME[L.env];
    if (!home) { console.log(`${L.prompt_id}#${L.i}: NO ROUTE for env ${L.env} - skipped`); continue; }
    const status = codex(['cloud', 'status', L.task_id], home);
    if (unreachable(status)) { console.log(`${L.prompt_id}#${L.i}: UNREACHABLE (${(status||'').trim().slice(0,60)}) - stays queued`); continue; }
    if (/PENDING|RUNNING|IN_PROGRESS/i.test(status)) { console.log(`${L.prompt_id}#${L.i}: still running`); continue; }
    const rawDiff = codex(['cloud', 'diff', L.task_id], home);
    const diff = /No diff available/i.test(rawDiff) ? '' : (unreachable(rawDiff) ? '' : rawDiff);
    const program = extractProgram(diff);
    const env = { surface: 'codex-cloud', model: 'cloud-default', effort: `attempts${L.attempts}`,
                  prompt_id: L.prompt_id, condition: 'base', prompt_sha256: L.prompt_sha256, i: L.i,
                  status: program ? 'program' : (diff.trim() || status.trim() ? 'no-program' : 'harness-error'),
                  raw_text: (diff && diff.trim()) ? diff : status, program,
                  task_id: L.task_id, collected_at: new Date().toISOString() };
    fs.appendFileSync(outPath, JSON.stringify(env) + '\n');
    console.log(`${L.prompt_id}#${L.i}: ${env.status}`);
  }
}
console.log('COLLECTION PASS DONE');
