// PROFESSOR'S ARM (owner directive 2026-08-19, in-session, verbatim in
// lattice_arm/RUN-MANIFEST.json): the 2x2 lattice square measured across all
// effort levels. Phase 1: gpt-5.6-luna + gpt-5.6-terra (codex lane). Real
// experiment data -> repo lattice_arm/gens/<model>_<effort>.jsonl (one line
// per draw; raw_stdout stripped - event summary lives in response_meta).
// Usage: node lattice-arm-gen.js <model> <effort>
// Resume-safe: stems already present in the JSONL are skipped.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const R = require('path').resolve(__dirname, '..');
const D = require(path.join(__dirname, 'gen_drivers.js'));

const MODEL = process.argv[2];
const EFFORT = process.argv[3];
if (!/^gpt-5\.6-(luna|terra|sol)$|^claude-|^gemini-2\.5-(pro|flash|flash-lite)$|^gemini-cli$/.test(MODEL || '')) throw new Error('bad model ' + MODEL);
if (!['low', 'medium', 'high', 'xhigh', 'max', 'default'].includes(EFFORT)) throw new Error('bad effort ' + EFFORT);
const SURFACE = MODEL === 'gemini-cli' ? 'gemcli' : MODEL.startsWith('claude') ? 'claude' : MODEL.startsWith('gemini') ? 'vertex' : 'codex';
if (SURFACE === 'gemcli' && EFFORT !== 'default') throw new Error('gemini-cli lane is single-tier: effort must be "default" (no thinking control in the CLI)');

// gemini CLI lane (owner-approved fair-harness leg, 2026-08-19): vendor
// instruction layer present (~11k tok), isolated home (creds only), read-only
// approval, JSON output. PINNING IS BROKEN (2.5-flash->3.5-flash,
// 3.5-flash->2.5-pro, verified) - we run the DEFAULT and record the SERVED
// model per draw from stats; analysis stratifies post-hoc.
function genGeminiCli({ prompt }) {
  const { spawnSync } = require('child_process');
  const os = require('os');
  const gemHome = path.join(__dirname, 'gem-home');
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'lb-gemcli-'));
  const env = { surface: 'gemini-cli', model: 'vendor-routed(default)', effort: 'default',
                started_at: new Date().toISOString(), cwd,
                auth_mode: 'gemini CLI OAuth (jpinckard21 subscription plan) in isolated home (creds only, no GEMINI.md/extensions)' };
  const GEMINI_JS = path.join(process.env.APPDATA || '', 'npm', 'node_modules', '@google', 'gemini-cli', 'bundle', 'gemini.js');
  const args = [GEMINI_JS, '-p', prompt, '-o', 'json', '--approval-mode', 'plan', '--skip-trust'];
  env.argv = ['node', GEMINI_JS, '-p', '<prompt>', '-o', 'json', '--approval-mode', 'plan', '--skip-trust'];
  const childEnv = { ...process.env, USERPROFILE: gemHome.replace(/\//g, '\\'), HOME: gemHome };
  delete childEnv.ELECTRON_RUN_AS_NODE;
  const t0 = Date.now();
  // shell:false so the multiline prompt survives as ONE argv element
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', cwd, env: childEnv, shell: false,
    timeout: 10 * 60 * 1000, maxBuffer: 64 * 1024 * 1024 });
  env.wall_ms = Date.now() - t0; env.exit_code = r.status;
  env.spawn_error = r.error ? String(r.error.message) : null;
  env.raw_stderr_head = (r.stderr || '').slice(0, 1500);
  const out = r.stdout || '';
  let j = null;
  const m = out.match(/\{[\s\S]*\}/);
  if (m) { try { j = JSON.parse(m[0]); } catch (e) { env.parse_error = String(e.message).slice(0, 150); } }
  if (!j) { env.status = 'harness-error'; env.raw_stdout_head = out.slice(0, 2000); return env; }
  const modelMap = (j.stats || {}).models || {};
  const models = Object.keys(modelMap);
  const mstats = modelMap[models[0]] || {};
  env.response_meta = { model_served: models, midcall_switch: models.length > 1,
                        per_model_stats: Object.fromEntries(models.map(k => [k, { tokens: (modelMap[k] || {}).tokens, api: (modelMap[k] || {}).api }])),
                        session_id: j.session_id,
                        thoughts_tokens: (mstats.tokens || {}).thoughts, prompt_tokens: (mstats.tokens || {}).prompt,
                        api_errors: (mstats.api || {}).totalErrors };
  env.raw_text = j.response ?? null;
  const ex = D.extractProgram(env.raw_text);
  env.program = ex.program; env.extract_rule = ex.rule;
  env.status = env.program ? 'program' : 'no-program';
  return env;
}

// NOASK condition (RUN-MANIFEST-2): the LiveCodeBench line, verbatim, appended
// identically to every prompt. Owner-picked 2026-08-19; cited in the manifest.
const NOASK = process.argv.includes('noask');
const SUFFIX = 'You will NOT return anything except for the program.';

const OUTDIR = path.join(R, 'arm', NOASK ? 'gens_noask' : 'gens');
fs.mkdirSync(OUTDIR, { recursive: true });
const OUT = path.join(OUTDIR, `${MODEL.replace(/[^\w.-]/g, '')}_${EFFORT}.jsonl`);

// interior-first (default for resume runs): the period/union cells carry the
// scientific weight; if quota dies mid-lane, corners are already covered
const VARIANTS = process.argv[4] === 'corner-first'
  ? ['T1v0', 'BL-01a', 'BL-01b', 'BL-01c']
  : ['BL-01b', 'BL-01c', 'T1v0', 'BL-01a'];
const N = 10;

const vfile = JSON.parse(fs.readFileSync(path.join(R, 'prompts', 'variants-v5.json'), 'utf8'));
const byId = {};
for (const v of vfile.variants) byId[v.id] = v;
const t1 = fs.readFileSync(path.join(R, 'prompts', 'T1v0.txt'), 'utf8');
byId['T1v0'] = { id: 'T1v0', prompt: t1, sha256: crypto.createHash('sha256').update(t1, 'utf8').digest('hex') };
for (const id of VARIANTS) {
  const v = byId[id];
  const got = crypto.createHash('sha256').update(v.prompt, 'utf8').digest('hex');
  if (got !== v.sha256) throw new Error(`FROZEN PROMPT MISMATCH ${id}`);
}
if (NOASK) {
  const man2 = JSON.parse(fs.readFileSync(path.join(R, 'arm', 'RUN-MANIFEST-2.json'), 'utf8'));
  for (const id of ['T1v0', 'BL-01a', 'BL-01b', 'BL-01c']) {
    const txt = byId[id].prompt.replace(/\n+$/, '') + '\n\n' + SUFFIX + '\n';
    const got = crypto.createHash('sha256').update(txt, 'utf8').digest('hex');
    if (got !== man2.prompt_sha256[id].combined_sha256) throw new Error(`COMBINED PROMPT MISMATCH ${id}: ${got}`);
    byId[id] = { id, prompt: txt, sha256: got };
  }
  console.log('NOASK condition: combined prompts verified against RUN-MANIFEST-2');
}

// FAIRNESS RULE (owner, 2026-08-19): draws where the model never finished
// (harness-error, or no-program with an EMPTY response) do not count and are
// retried - only genuinely finished draws occupy a (variant, replicate) slot.
const have = new Set();
if (fs.existsSync(OUT)) {
  for (const line of fs.readFileSync(OUT, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try {
      const j = JSON.parse(line);
      const unfinished = j.status === 'harness-error' || (j.status === 'no-program' && !(j.raw_text || '').trim());
      if (!unfinished) have.add(`${j.variant}|${j.replicate}`);
    } catch (e) { /* ignore */ }
  }
}

const gen = SURFACE === 'gemcli' ? genGeminiCli : SURFACE === 'claude' ? D.genClaude : SURFACE === 'vertex' ? D.genVertex : D.genCodex;
(async () => {
  let done = have.size, fail = 0;
  for (const id of VARIANTS) {
    for (let i = 0; i < N; i++) {
      if (have.has(`${id}|${i}`)) continue;
      const t0 = Date.now();
      let env;
      try {
        env = gen({ model: MODEL, effort: EFFORT, prompt: byId[id].prompt });
        if (env && typeof env.then === 'function') env = await env;   // genVertex is async
      } catch (e) {
        env = { status: 'harness-error', spawn_error: String(e && e.message) };
      }
      env.arm = NOASK ? 'LATTICE-PROF-NOASK' : 'LATTICE-PROF'; env.variant = id; env.replicate = i;
      env.prompt_sha256 = byId[id].sha256;
      delete env.raw_stdout;   // replay telemetry; the event summary is in response_meta
      fs.appendFileSync(OUT, JSON.stringify(env) + '\n', 'utf8');
      done++;
      if (env.status !== 'program') fail++;
      console.log(`[${done}/40] ${MODEL}/${EFFORT} ${id}#${i} status=${env.status} wall=${Math.round((Date.now() - t0) / 1000)}s`);
    }
  }
  console.log(`LANE DONE ${MODEL}/${EFFORT} total=${done} non-program-this-session=${fail}`);
})();
