'use strict';
// The semantic-edge (E-family) prompts at the AGENTIC harness.
//
// July's finding: these prompts fail not on complexity but on UNSTATED
// PLATFORM FACTS - a bar-presence guard silently skips every split event,
// a relative custom-data path resolves nowhere, futures chains never appear
// inside scheduled events. Failure was "data-path starvation": code that
// compiles, runs, reads correctly, and quietly disconnects itself from the
// data it needs. Adding one sentence of the missing fact moved E1 from
// 1/10 to 9/10.
//
// The open question this lane answers: does AGENCY substitute for that
// sentence? A cloud agent has tools and can explore - so it might discover
// the platform fact the one-shot model could not know. Same frozen prompts,
// different harness.
//
//   node cloud-efamily.js <env-id> <repo> <branch> <n-per-spec> [conc] [ids]
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const CODEX_JS = process.env.LB_CODEX_JS || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\bin\\codex.js';
const SPECS = 'C:\\Users\\joshp\\Desktop\\7.1 Research\\LLMDataAcquisition\\leanbench_prompts\\dist\\specs.json';
const [ENV_ID, REPO, BRANCH, N_STR, CONC_STR, IDS] = process.argv.slice(2);
const N = parseInt(N_STR || '10', 10);
const CONC = parseInt(CONC_STR || '6', 10);
if (!ENV_ID || !REPO || !BRANCH) { console.error('usage: cloud-efamily.js <env-id> <repo> <branch> <n> [conc] [id,id,...]'); process.exit(2); }

const raw = JSON.parse(fs.readFileSync(SPECS, 'utf8'));
const all = Array.isArray(raw) ? raw : (raw.specs || Object.values(raw));
// the starvation-bearing specs first: splits, dividends, the dual-event
// state machine, custom data, futures - the ones July showed models fail
const PRIORITY = ['E1v0', 'E8v0', 'E2v0', 'E16v0', 'E15v1', 'E13v0', 'E17v0', 'E14v0'];
const wanted = IDS ? IDS.split(',') : PRIORITY;
const specs = wanted.map(id => all.find(s => s.id === id)).filter(Boolean);

const OUTDIR = path.join(REPO_ROOT, 'batches', 'cloud');
fs.mkdirSync(OUTDIR, { recursive: true });
const OUT = path.join(OUTDIR, 'cloud_efamily.jsonl');
const have = new Set();
if (fs.existsSync(OUT)) for (const l of fs.readFileSync(OUT, 'utf8').split('\n')) if (l.trim()) { const j = JSON.parse(l); if (j.task_id) have.add(j.spec_id + '#' + j.i); }

function launch(spec, i) {
  return new Promise(resolve => {
    const sha = crypto.createHash('sha256').update(spec.prompt, 'utf8').digest('hex');
    const t0 = Date.now();
    const p = spawn(process.execPath, [CODEX_JS, 'cloud', 'exec', '--env', ENV_ID, '--branch', BRANCH, spec.prompt], { shell: false, windowsHide: true });
    let blob = '';
    p.stdout.on('data', d => { blob += d; });
    p.stderr.on('data', d => { blob += d; });
    const killer = setTimeout(() => { try { p.kill('SIGKILL'); } catch (e) {} }, 8 * 60 * 1000);
    p.on('close', code => {
      clearTimeout(killer);
      const m = blob.match(/task_[A-Za-z0-9_]+/);
      const rec = { leg: 'E-family-agentic', surface: 'codex-cloud', env: ENV_ID, repo: REPO, branch: BRANCH,
                    spec_id: spec.id, family: spec.family || null, expected_min_orders: spec.expected_min_orders ?? null,
                    prompt_sha256: sha, i, task_id: m ? m[0] : null, launch_ok: !!m, exit: code,
                    launched_at: new Date().toISOString(), wall_ms: Date.now() - t0,
                    launch_output: m ? null : blob.slice(0, 250).replace(/\s+/g, ' ') };
      fs.appendFileSync(OUT, JSON.stringify(rec) + '\n');
      console.log(`${spec.id}#${i} -> ${rec.task_id || 'FAILED'}`);
      resolve(rec.launch_ok);
    });
  });
}

(async () => {
  const jobs = [];
  for (const s of specs) for (let i = 0; i < N; i++) if (!have.has(s.id + '#' + i)) jobs.push([s, i]);
  console.log(`E-family agentic lane: ${jobs.length} draws over ${specs.length} specs (${specs.map(s => s.id).join(',')})`);
  let ok = 0, fail = 0;
  for (let s = 0; s < jobs.length; s += CONC) {
    const res = await Promise.all(jobs.slice(s, s + CONC).map(([sp, i]) => launch(sp, i)));
    ok += res.filter(Boolean).length; fail += res.filter(x => !x).length;
    await new Promise(r => setTimeout(r, 8000));
  }
  console.log(`E-FAMILY LANE LAUNCHED: ${ok} ok, ${fail} failed`);
})();
