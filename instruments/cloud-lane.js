'use strict';
// H6: the CLOUD harness point. Same frozen prompts, same model as the local
// CLI and bare-API cells - but run as a Codex Cloud agent task (tools, repo,
// autonomy). Completes the gradient: bare API -> one-shot CLI -> full agent.
//
//   node cloud-lane.js <env-id> <repo> <branch> <prompt-id> <n> [attempts]
//
// One task per draw (independence: asking a single task for N programs would
// give N correlated outputs from one context, not N draws). Task ids are
// recorded immediately; the outputs are collected later by cloud-collect.js,
// so the launch window is never spent waiting on completion.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const CODEX_JS = process.env.LB_CODEX_JS || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\bin\\codex.js';
const [ENV_ID, REPO, BRANCH, PROMPT_ID, N_STR, ATTEMPTS_STR] = process.argv.slice(2);
const N = parseInt(N_STR || '30', 10);
const ATTEMPTS = parseInt(ATTEMPTS_STR || '1', 10);
if (!ENV_ID || !REPO || !BRANCH || !PROMPT_ID) {
  console.error('usage: cloud-lane.js <env-id> <repo> <branch> <prompt-id> <n> [attempts]');
  process.exit(2);
}

// frozen prompt, hash-verified exactly as every other surface does
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

const OUTDIR = path.join(REPO_ROOT, 'batches', 'cloud');
fs.mkdirSync(OUTDIR, { recursive: true });
const safeId = PROMPT_ID.replace(/'/g, 'p').replace(/[^\w.-]/g, '');
const OUT = path.join(OUTDIR, `cloud_${safeId}_attempts${ATTEMPTS}.jsonl`);
const have = new Set();
if (fs.existsSync(OUT)) for (const l of fs.readFileSync(OUT, 'utf8').split('\n')) if (l.trim()) have.add(JSON.parse(l).i);

for (let i = 0; i < N; i++) {
  if (have.has(i)) continue;
  const t0 = Date.now();
  const args = [CODEX_JS, 'cloud', 'exec', '--env', ENV_ID, '--branch', BRANCH];
  if (ATTEMPTS > 1) args.push('--attempts', String(ATTEMPTS));
  args.push(prompt);
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', shell: false, timeout: 10 * 60 * 1000, maxBuffer: 64 * 1024 * 1024 });
  const blob = (r.stdout || '') + (r.stderr || '');
  const m = blob.match(/task_[A-Za-z0-9_]+/);
  const rec = { leg: 'H6-cloud', surface: 'codex-cloud', env: ENV_ID, repo: REPO, branch: BRANCH,
                prompt_id: PROMPT_ID, prompt_sha256: sha, attempts: ATTEMPTS, i,
                task_id: m ? m[0] : null, launch_ok: !!m, exit: r.status,
                launched_at: new Date().toISOString(), wall_ms: Date.now() - t0,
                launch_output: m ? null : blob.slice(0, 400) };
  fs.appendFileSync(OUT, JSON.stringify(rec) + '\n');
  console.log(`[${i + 1}/${N}] ${PROMPT_ID} attempts=${ATTEMPTS} -> ${rec.task_id || 'LAUNCH FAILED'} (${Math.round(rec.wall_ms / 1000)}s)`);
  if (!m) console.log('   ', blob.slice(0, 200).replace(/\n/g, ' '));
}
console.log('CLOUD LANE LAUNCHED', PROMPT_ID, 'attempts=' + ATTEMPTS);
