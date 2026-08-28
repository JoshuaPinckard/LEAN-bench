'use strict';
// Collect the three cloud ledgers whose drivers never had a collector:
// cloud_dose_E1.jsonl (spec_id/arm/i), cloud_efamily.jsonl (family/spec_id/i),
// cloud_auditrefs.jsonl (audit_task_id). The generic cloud-collect.js skips
// them - its envelopes would label their rows prompt_id: undefined.
//
// Envelope = the ENTIRE launch row preserved verbatim, plus collection fields.
// Preserving the row instead of remapping it means each study's own analysis
// keys (spec_id, arm, family, audit_task_id) survive untouched.
//
// Same safety contract as the patched cloud-collect.js: every task is routed
// to the account that launched it via the env recorded in its row, and any
// cannot-see-the-task response (404/auth/rate limit/network) is UNREACHABLE:
// skipped, retried next run, never written as an envelope. A 404 written as
// data would grade as a false refusal.
//   node cloud-collect-special.js
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const CODEX_JS = process.env.LB_CODEX_JS || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\bin\\codex.js';
const DIR = path.join(REPO_ROOT, 'batches', 'cloud');
const FILES = ['cloud_dose_E1.jsonl', 'cloud_efamily.jsonl', 'cloud_auditrefs.jsonl'];

const ENV_HOME = {
  '6a8b227882848191a9c3c07b03bac026': 'C:\\Users\\joshp\\AppData\\Roaming\\ToolsEnabled\\capability\\codex-homes\\cloud-a',
  '6a8b2d070c9481918ec92aaef133bc9d': 'C:\\Users\\joshp\\AppData\\Roaming\\ToolsEnabled\\capability\\codex-homes\\cloud-a',
  '6a8b1cfcff788191902ea36cc5738f5e': 'C:\\Users\\joshp\\AppData\\Roaming\\ToolsEnabled\\capability\\codex-homes\\cloud-b',
  '6a8b2ca0f0bc81918132b16266cc192e': 'C:\\Users\\joshp\\AppData\\Roaming\\ToolsEnabled\\capability\\codex-homes\\cloud-b',
};
const unreachable = t => /404 Not Found|Not signed in|codex login|401|403|usage limit|rate.?limit|429|http error|ECONNRESET|ETIMEDOUT|could not create PATH aliases/i.test(t || '') || !(t || '').trim();

function codex(args, home) {
  const env = Object.assign({}, process.env, { CODEX_HOME: home });
  const r = spawnSync(process.execPath, [CODEX_JS, ...args], { encoding: 'utf8', shell: false, timeout: 5 * 60 * 1000, maxBuffer: 64 * 1024 * 1024, env });
  return (r.stdout || '') + (r.stderr || '');
}

function extractProgram(text) {
  if (!text) return null;
  const added = text.split('\n').filter(l => /^\+/.test(l) && !/^\+\+\+/.test(l)).map(l => l.slice(1)).join('\n');
  const body = /QCAlgorithm/.test(added) ? added : text;
  const fences = [...body.matchAll(/```(?:python)?\s*\n([\s\S]*?)```/g)].map(m => m[1]);
  const withQC = fences.filter(x => /QCAlgorithm/.test(x));
  const pick = (withQC.length ? withQC : fences).sort((a, b) => b.length - a.length)[0];
  if (pick) return pick;
  return /class\s+\w+\s*\(\s*QCAlgorithm\s*\)/.test(body) ? body : null;
}

let harvested = 0, unreach = 0, running = 0;
for (const f of FILES) {
  const src = path.join(DIR, f);
  if (!fs.existsSync(src)) { console.log(`${f}: missing`); continue; }
  const outPath = path.join(DIR, f.replace('.jsonl', '.collected.jsonl'));
  const done = new Set();
  if (fs.existsSync(outPath)) for (const l of fs.readFileSync(outPath, 'utf8').split('\n')) if (l.trim()) done.add(JSON.parse(l).task_id);

  const rows = fs.readFileSync(src, 'utf8').split('\n').filter(x => x.trim()).map(JSON.parse);
  console.log(`=== ${f}: ${rows.length} rows, ${done.size} already collected`);
  for (const L of rows) {
    if (!L.task_id || done.has(L.task_id)) continue;
    const home = ENV_HOME[L.env];
    if (!home) { console.log(`  ${L.task_id}: NO ROUTE for env ${L.env}`); continue; }
    const status = codex(['cloud', 'status', L.task_id], home);
    if (unreachable(status)) { unreach++; continue; }
    if (/PENDING|RUNNING|IN_PROGRESS/i.test(status)) { running++; continue; }
    const rawDiff = codex(['cloud', 'diff', L.task_id], home);
    const diff = (/No diff available/i.test(rawDiff) || unreachable(rawDiff)) ? '' : rawDiff;
    const program = extractProgram(diff);
    const env = Object.assign({}, L, {
      collect_status: program ? 'program' : ((diff.trim() || status.trim()) ? 'no-program' : 'harness-error'),
      raw_text: diff.trim() ? diff : status,
      program,
      collected_at: new Date().toISOString(),
    });
    fs.appendFileSync(outPath, JSON.stringify(env) + '\n');
    harvested++;
    if (harvested % 25 === 0) console.log(`  ${harvested} harvested | ${unreach} unreachable | ${running} running`);
  }
}
console.log(`SPECIAL COLLECT: ${harvested} harvested, ${unreach} unreachable (stay queued), ${running} still running`);
