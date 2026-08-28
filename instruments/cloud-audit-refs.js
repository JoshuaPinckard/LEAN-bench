'use strict';
// Audit harness-sensitivity probe: does a benchmark's GROUND TRUTH depend on
// the harness that generated it? The audit's reference implementations were
// drafted by three local one-shot surfaces (sonnet, terra, gemini-vertex).
// This lane redraws references for a sample of the SAME census tasks through
// the agentic cloud harness, using the audit's own frozen prompt template
// verbatim. Divergence between cloud and local references on identical tasks
// is the finding; agreement is equally informative.
//
//   node cloud-audit-refs.js <env-id> <repo> <branch> <n-tasks> [conc]
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const CODEX_JS = process.env.LB_CODEX_JS || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\bin\\codex.js';
const [ENV_ID, REPO, BRANCH, NTASK_STR, CONC_STR] = process.argv.slice(2);
const NTASK = parseInt(NTASK_STR || '50', 10);
const CONC = parseInt(CONC_STR || '6', 10);
if (!ENV_ID || !REPO || !BRANCH) { console.error('usage: cloud-audit-refs.js <env-id> <repo> <branch> <n-tasks> [conc]'); process.exit(2); }

// v2 template (owner ruling 2026-08-25): identical task, delivery changed to
// commit-a-file - v1's chat-only answers were unretrievable by the CLI. The
// per-row template_sha256 records which version each task ran under.
const TEMPLATE = fs.readFileSync(path.join(REPO_ROOT, 'audit', 'prompts', 'ref_impl_prompt_v2.txt'), 'utf8');
const TEMPLATE_SHA = crypto.createHash('sha256').update(TEMPLATE, 'utf8').digest('hex');
const tasks = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'audit', 'QuantCode-Bench', 'data', 'benchmark_tasks_multiframe.json'), 'utf8'));
const reqs = {};
for (const r of JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'audit', 'QuantCode-Bench', 'data', 'task_data_requirements.json'), 'utf8'))) reqs[r.task_id] = r;
const manifest = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'audit', 'frozen_cache', 'cache_manifest.json'), 'utf8'));

function safeName(sym) { return String(sym).replace(/=/g, '_').replace(/\^/g, '_'); }

// deterministic sample of the census, seeded so the set is reproducible
const ids = tasks.map(t => t.id).sort((a, b) => a - b);
let seed = 20260823;
const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
const shuffled = ids.slice();
for (let i = shuffled.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]; }
const chosen = shuffled.slice(0, NTASK);

const OUTDIR = path.join(REPO_ROOT, 'batches', 'cloud');
fs.mkdirSync(OUTDIR, { recursive: true });
const OUT = path.join(OUTDIR, 'cloud_auditrefs.jsonl');
const have = new Set();
if (fs.existsSync(OUT)) for (const l of fs.readFileSync(OUT, 'utf8').split('\n')) if (l.trim()) { const j = JSON.parse(l); if (j.task_id) have.add(j.audit_task_id); }

function promptFor(id) {
  const t = tasks.find(x => x.id === id);
  const r = reqs[id];
  if (!t || !r) return null;
  const key = `${safeName(r.yf_symbol)}_${r.timeframe}.pkl`;
  const m = manifest[key];
  if (!m) return null;
  return TEMPLATE
    .replace('{SYMBOL}', r.yf_symbol)
    .replace('{TIMEFRAME}', r.timeframe)
    .replace('{RANGE}', `${m.index_min} to ${m.index_max} (${m.rows} bars)`)
    .replace('{task}', t.reformulated_task);
}

function launch(id) {
  return new Promise(resolve => {
    const prompt = promptFor(id);
    if (!prompt) { console.log(`task ${id}: skipped (no frozen pair)`); return resolve(false); }
    const t0 = Date.now();
    const p = spawn(process.execPath, [CODEX_JS, 'cloud', 'exec', '--env', ENV_ID, '--branch', BRANCH, prompt], { shell: false, windowsHide: true });
    let blob = '';
    p.stdout.on('data', d => { blob += d; });
    p.stderr.on('data', d => { blob += d; });
    const killer = setTimeout(() => { try { p.kill('SIGKILL'); } catch (e) {} }, 8 * 60 * 1000);
    p.on('close', code => {
      clearTimeout(killer);
      const m = blob.match(/task_[A-Za-z0-9_]+/);
      const rec = { leg: 'audit-harness-sensitivity', surface: 'codex-cloud', env: ENV_ID, repo: REPO, branch: BRANCH,
                    audit_task_id: id, template_sha256: TEMPLATE_SHA, prompt_sha256: crypto.createHash('sha256').update(prompt, 'utf8').digest('hex'),
                    task_id: m ? m[0] : null, launch_ok: !!m, exit: code, launched_at: new Date().toISOString(),
                    wall_ms: Date.now() - t0, launch_output: m ? null : blob.slice(0, 250).replace(/\s+/g, ' ') };
      fs.appendFileSync(OUT, JSON.stringify(rec) + '\n');
      console.log(`audit task ${id} -> ${rec.task_id || 'FAILED'}`);
      resolve(rec.launch_ok);
    });
  });
}

(async () => {
  const todo = chosen.filter(id => !have.has(id));
  console.log(`audit harness probe: ${todo.length} tasks, ${CONC} at a time (template sha ${TEMPLATE_SHA.slice(0, 12)})`);
  let ok = 0, fail = 0;
  for (let s = 0; s < todo.length; s += CONC) {
    const res = await Promise.all(todo.slice(s, s + CONC).map(launch));
    ok += res.filter(Boolean).length; fail += res.filter(x => !x).length;
    await new Promise(r => setTimeout(r, 8000));
  }
  console.log(`AUDIT REF PROBE LAUNCHED: ${ok} ok, ${fail} failed`);
})();
