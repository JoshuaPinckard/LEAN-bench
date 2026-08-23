'use strict';
// H6: the CLOUD harness point. Same frozen prompts, same study models as the
// local CLI and bare-API cells - run as Codex Cloud agent tasks (tools, repo,
// autonomy). Completes the gradient: bare API -> one-shot CLI -> full agent.
//
//   node cloud-lane.js <env-id> <repo> <branch> <prompt-id> <n> [attempts] [conc]
//
// One task per draw (independence: one task asked for N programs yields N
// correlated outputs from a single context, not N draws). Launches run
// CONCURRENTLY - the quota window is spent submitting, never waiting - and
// task ids are appended the instant each returns. Outputs are pulled later
// by cloud-collect.js, which costs nothing.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const CODEX_JS = process.env.LB_CODEX_JS || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\bin\\codex.js';
const [ENV_ID, REPO, BRANCH, PROMPT_ID_RAW, N_STR, ATTEMPTS_STR, CONC_STR] = process.argv.slice(2);
// accept the filename form (BL-02bp) as well as the real id (BL-02b')
const PROMPT_ID = PROMPT_ID_RAW === 'BL-02bp' ? "BL-02b'" : PROMPT_ID_RAW;
const N = parseInt(N_STR || '30', 10);
const ATTEMPTS = parseInt(ATTEMPTS_STR || '1', 10);
const CONC = parseInt(CONC_STR || '12', 10);       // simultaneous submissions
const NOASK = process.argv.includes('noask');
const NOASK_SUFFIX = 'You will NOT return anything except for the program.';
if (!ENV_ID || !REPO || !BRANCH || !PROMPT_ID) {
  console.error('usage: cloud-lane.js <env-id> <repo> <branch> <prompt-id> <n> [attempts] [conc]');
  process.exit(2);
}

let prompt, sha;
if (PROMPT_ID === 'T1v0') {
  prompt = fs.readFileSync(path.join(REPO_ROOT, 'prompts', 'T1v0.txt'), 'utf8');
  sha = crypto.createHash('sha256').update(prompt, 'utf8').digest('hex');
} else {
  const V = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'prompts', 'variants-v5.json'), 'utf8'));
  const v = V.variants.find(x => x.id === PROMPT_ID);
  if (!v) throw new Error('unknown prompt ' + PROMPT_ID);
  sha = crypto.createHash('sha256').update(v.prompt, 'utf8').digest('hex');
  if (sha !== v.sha256) throw new Error('FROZEN PROMPT MISMATCH ' + PROMPT_ID);
  prompt = v.prompt;
}

if (NOASK) {
  prompt = prompt.replace(/\n+$/, '') + '\n\n' + NOASK_SUFFIX + '\n';
  sha = crypto.createHash('sha256').update(prompt, 'utf8').digest('hex');
}

const OUTDIR = path.join(REPO_ROOT, 'batches', 'cloud');
fs.mkdirSync(OUTDIR, { recursive: true });
const safeId = PROMPT_ID.replace(/'/g, 'p').replace(/[^\w.-]/g, '');
const OUT = path.join(OUTDIR, `cloud_${safeId}_attempts${ATTEMPTS}${NOASK ? '_noask' : ''}.jsonl`);
const have = new Set();
if (fs.existsSync(OUT)) for (const l of fs.readFileSync(OUT, 'utf8').split('\n')) if (l.trim()) { const j = JSON.parse(l); if (j.task_id) have.add(j.i); }

function launch(i) {
  return new Promise(resolve => {
    const t0 = Date.now();
    const args = [CODEX_JS, 'cloud', 'exec', '--env', ENV_ID, '--branch', BRANCH];
    if (ATTEMPTS > 1) args.push('--attempts', String(ATTEMPTS));
    args.push(prompt);
    const p = spawn(process.execPath, args, { shell: false, windowsHide: true });
    let blob = '';
    p.stdout.on('data', d => { blob += d; });
    p.stderr.on('data', d => { blob += d; });
    const killer = setTimeout(() => { try { p.kill('SIGKILL'); } catch (e) {} }, 8 * 60 * 1000);
    p.on('close', code => {
      clearTimeout(killer);
      const m = blob.match(/task_[A-Za-z0-9_]+/);
      const rec = { leg: 'H6-cloud', surface: 'codex-cloud', env: ENV_ID, repo: REPO, branch: BRANCH,
                    prompt_id: PROMPT_ID, prompt_sha256: sha, attempts: ATTEMPTS, condition: NOASK ? 'noask' : 'base', i,
                    task_id: m ? m[0] : null, launch_ok: !!m, exit: code,
                    launched_at: new Date().toISOString(), wall_ms: Date.now() - t0,
                    launch_output: m ? null : blob.slice(0, 300).replace(/\s+/g, ' ') };
      fs.appendFileSync(OUT, JSON.stringify(rec) + '\n');
      console.log(`#${i} -> ${rec.task_id || 'FAILED'} (${Math.round(rec.wall_ms / 1000)}s)${rec.task_id ? '' : ' | ' + rec.launch_output}`);
      resolve(rec.launch_ok);
    });
  });
}

(async () => {
  const todo = [];
  for (let i = 0; i < N; i++) if (!have.has(i)) todo.push(i);
  console.log(`launching ${todo.length} tasks, ${CONC} at a time (${PROMPT_ID}, attempts=${ATTEMPTS})`);
  let ok = 0, fail = 0;
  for (let s = 0; s < todo.length; s += CONC) {
    const wave = todo.slice(s, s + CONC);
    const res = await Promise.all(wave.map(launch));
    ok += res.filter(Boolean).length;
    fail += res.filter(x => !x).length;
    console.log(`  wave ${Math.floor(s / CONC) + 1}: ${ok} launched, ${fail} failed so far`);
    if (fail >= 6 && ok === 0) { console.error('ABORT: every launch failing - fix before burning the window'); break; }
  }
  console.log(`CLOUD LANE DONE ${PROMPT_ID} attempts=${ATTEMPTS}: ${ok} launched, ${fail} failed`);
})();
