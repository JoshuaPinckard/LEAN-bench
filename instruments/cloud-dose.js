'use strict';
// THE DOSE-RESPONSE LADDER AT THE AGENTIC HARNESS.
//
// July's cleanest experiment: the same E1 task at four information doses —
//   A  hidden        the prompt as written                  (haiku 1/10)
//   B  WHAT-pinned   + one sentence of behavior             (haiku 6/10)
//   C  HOW-disclosed + the platform mechanic named          (haiku 9/10)
//   G  guard-deleted A minus the header's guard sentence    (haiku 7/10)
// A clean monotone dose-response: difficulty IS the information gap, and
// the prompt's own header was co-authoring the failures.
//
// The question here: does AGENCY substitute for the missing sentence? A
// cloud agent has tools and can explore the platform. If arm A rises toward
// B/C levels at this harness, agency partially closes information gaps -
// and the semantic edge is a property of one-shot generation, not of models.
//
// PROVENANCE: the B and C sentences are the RECONSTRUCTED texts from
// semantic_edge_spike/prompts_reconstructed (headers say so; reconstructed
// 2026-07-16 from SEMANTIC_EDGE_AXIS.md 2.1, C corroborated by comment
// echoes in the July generations). Internal A/B/C/G comparison at this
// harness is exact; comparison to July's numbers is approximate for B/C
// and must be reported that way.
//
//   node cloud-dose.js <env-id> <repo> <branch> <n-per-arm> [conc]
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const CODEX_JS = process.env.LB_CODEX_JS || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\bin\\codex.js';
const JULY = 'C:\\Users\\joshp\\Desktop\\7.1 Research\\LLMDataAcquisition';
const [ENV_ID, REPO, BRANCH, N_STR, CONC_STR] = process.argv.slice(2);
const N = parseInt(N_STR || '20', 10);
const CONC = parseInt(CONC_STR || '6', 10);
if (!ENV_ID || !REPO || !BRANCH) { console.error('usage: cloud-dose.js <env-id> <repo> <branch> <n> [conc]'); process.exit(2); }

const specs = JSON.parse(fs.readFileSync(path.join(JULY, 'leanbench_prompts', 'dist', 'specs.json'), 'utf8'));
const items = Array.isArray(specs) ? specs : (specs.specs || Object.values(specs));
const E1 = items.find(s => s.id === 'E1v0');
if (!E1) throw new Error('E1v0 not found in the frozen spec package');

function sentenceOf(file) {
  const raw = fs.readFileSync(path.join(JULY, 'semantic_edge_spike', 'prompts_reconstructed', file), 'utf8');
  // drop the provenance header lines, keep the sentence itself
  return raw.split('\n').filter(l => l.trim() && !/^RECONSTRUCTED/i.test(l)).join(' ').trim();
}
const B_SENT = sentenceOf('E1_B_sentence.txt');
const C_SENT = sentenceOf('E1_C_sentence.txt');
const GUARD = ' Guard against missing/None bars instead of crashing.';

const ARMS = {
  A: E1.prompt,
  B: E1.prompt.replace(/\n\nOutput ONLY/, `\n\n${B_SENT}\n\nOutput ONLY`),
  C: E1.prompt.replace(/\n\nOutput ONLY/, `\n\n${C_SENT}\n\nOutput ONLY`),
  G: E1.prompt.replace(GUARD, ''),
};
for (const [k, v] of Object.entries(ARMS)) {
  if (k !== 'A' && v === E1.prompt) throw new Error(`arm ${k} edit did not apply - refusing to launch an unvaried ladder`);
}

const OUTDIR = path.join(REPO_ROOT, 'batches', 'cloud');
fs.mkdirSync(OUTDIR, { recursive: true });
const OUT = path.join(OUTDIR, 'cloud_dose_E1.jsonl');
const have = new Set();
if (fs.existsSync(OUT)) for (const l of fs.readFileSync(OUT, 'utf8').split('\n')) if (l.trim()) { const j = JSON.parse(l); if (j.task_id) have.add(j.arm + '#' + j.i); }

function launch(arm, i) {
  return new Promise(resolve => {
    const prompt = ARMS[arm];
    const sha = crypto.createHash('sha256').update(prompt, 'utf8').digest('hex');
    const t0 = Date.now();
    const p = spawn(process.execPath, [CODEX_JS, 'cloud', 'exec', '--env', ENV_ID, '--branch', BRANCH, prompt], { shell: false, windowsHide: true });
    let blob = '';
    p.stdout.on('data', d => { blob += d; });
    p.stderr.on('data', d => { blob += d; });
    const killer = setTimeout(() => { try { p.kill('SIGKILL'); } catch (e) {} }, 8 * 60 * 1000);
    p.on('close', code => {
      clearTimeout(killer);
      const m = blob.match(/task_[A-Za-z0-9_]+/);
      const rec = { leg: 'dose-response-agentic', surface: 'codex-cloud', env: ENV_ID, repo: REPO, branch: BRANCH,
                    spec_id: 'E1v0', arm, arm_meaning: { A: 'hidden', B: 'WHAT-pinned', C: 'HOW-disclosed', G: 'guard-deleted' }[arm],
                    sentence_provenance: (arm === 'B' || arm === 'C') ? 'reconstructed 2026-07-16 (not the original July file)' : 'frozen spec package',
                    prompt_sha256: sha, expected_min_orders: E1.expected_min_orders ?? null, i,
                    task_id: m ? m[0] : null, launch_ok: !!m, exit: code, launched_at: new Date().toISOString(),
                    wall_ms: Date.now() - t0, launch_output: m ? null : blob.slice(0, 250).replace(/\s+/g, ' ') };
      fs.appendFileSync(OUT, JSON.stringify(rec) + '\n');
      console.log(`${arm}#${i} -> ${rec.task_id || 'FAILED'}`);
      resolve(rec.launch_ok);
    });
  });
}

(async () => {
  const jobs = [];
  for (const arm of ['A', 'B', 'C', 'G']) for (let i = 0; i < N; i++) if (!have.has(arm + '#' + i)) jobs.push([arm, i]);
  console.log(`dose ladder at the agentic harness: ${jobs.length} draws (${N}/arm), arms A/B/C/G`);
  let ok = 0, fail = 0;
  for (let s = 0; s < jobs.length; s += CONC) {
    const res = await Promise.all(jobs.slice(s, s + CONC).map(([a, i]) => launch(a, i)));
    ok += res.filter(Boolean).length; fail += res.filter(x => !x).length;
    await new Promise(r => setTimeout(r, 8000));
  }
  console.log(`DOSE LADDER LAUNCHED: ${ok} ok, ${fail} failed`);
})();
