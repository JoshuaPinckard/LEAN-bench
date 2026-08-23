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

function codex(args) {
  const r = spawnSync(process.execPath, [CODEX_JS, ...args], { encoding: 'utf8', shell: false, timeout: 5 * 60 * 1000, maxBuffer: 64 * 1024 * 1024 });
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
  for (const L of launches) {
    if (done.has(L.i) || !L.task_id) continue;
    const status = codex(['cloud', 'status', L.task_id]);
    if (/PENDING|RUNNING|IN_PROGRESS/i.test(status)) { console.log(`${L.prompt_id}#${L.i}: still running`); continue; }
    const diff = codex(['cloud', 'diff', L.task_id]);
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
