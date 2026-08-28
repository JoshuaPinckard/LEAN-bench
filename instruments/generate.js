'use strict';
// The clean-room generator. Usage:
//   node generate.js <surface:codex|claude> <model> <effort> <prompt-id> <n>
// HARD GATE: refuses to spawn anything unless C:\lbres\CANARY-PASS-<today>.json
// exists (written only by canary.js when every surface passes both
// directions). No flag bypasses this. Prompts come only from
// prompts/variants-v5.json or prompts/T1v0.txt, hash-verified.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawnSync } = require('child_process');

const ROOT = 'C:/lbres';
const stamp = new Date().toISOString().slice(0, 10);
const PASS = path.join(ROOT, `CANARY-PASS-${stamp}.json`);
if (!fs.existsSync(PASS)) {
  console.error(`REFUSING: no same-day canary pass (${PASS} absent). Run canary.js first.`);
  process.exit(2);
}
// Per-surface certification (2026-08-25): the pass file lists the surfaces
// that proved BOTH canary directions today. Generating on any other surface
// is refused - a partially certified room certifies only what it certified.
{
  const passRec = JSON.parse(fs.readFileSync(PASS, 'utf8'));
  const certified = passRec.certified
    || (passRec.pass ? ['codex', 'claude', 'gemini'] : []);   // pre-change pass files
  if (!certified.includes(process.argv[2])) {
    console.error(`REFUSING: surface '${process.argv[2]}' not certified by today's canary (certified: ${certified.join(',') || 'none'}).`);
    process.exit(2);
  }
}

const [SURFACE, MODEL, EFFORT, PROMPT_ID, N_STR] = process.argv.slice(2);
const N = parseInt(N_STR || '10', 10);
const NOASK = process.argv.includes('noask');
// The registered no-ask instruction, verbatim (owner-picked from
// LiveCodeBench code_generation.py L83; see arm/RUN-MANIFEST-2.json).
const NOASK_SUFFIX = 'You will NOT return anything except for the program.';
if (!SURFACE || !MODEL || !EFFORT || !PROMPT_ID) { console.error('usage: generate.js <surface> <model> <effort> <prompt-id> <n> [noask]'); process.exit(2); }

const REPO = path.resolve(__dirname, '..');
let prompt, sha;
if (PROMPT_ID === 'T1v0') {
  prompt = fs.readFileSync(path.join(REPO, 'prompts', 'T1v0.txt'), 'utf8');
  sha = crypto.createHash('sha256').update(prompt, 'utf8').digest('hex');
} else if (/^O1/.test(PROMPT_ID)) {
  // Options arm (owner ruling 2026-08-25): a benchmark surface in a second
  // domain. Variants are hash-verified from arm-options/variants-o1.json under
  // the same FROZEN PROMPT MISMATCH rule as v5; the donor O1v0 is verified
  // against the registry's donor_sha256. Nothing else changes.
  const A = JSON.parse(fs.readFileSync(path.join(REPO, 'arm-options', 'variants-o1.json'), 'utf8'));
  if (PROMPT_ID === 'O1v0') {
    prompt = fs.readFileSync(path.join(REPO, 'arm-options', 'O1v0.txt'), 'utf8');
    sha = crypto.createHash('sha256').update(prompt, 'utf8').digest('hex');
    if (sha !== A.donor_sha256) throw new Error('FROZEN PROMPT MISMATCH O1v0 (donor)');
  } else {
    const v = A.variants.find(x => x.id === PROMPT_ID);
    if (!v) throw new Error('unknown arm prompt ' + PROMPT_ID);
    prompt = fs.readFileSync(path.join(REPO, 'arm-options', v.path), 'utf8');
    sha = crypto.createHash('sha256').update(prompt, 'utf8').digest('hex');
    if (sha !== v.sha256) throw new Error('FROZEN PROMPT MISMATCH ' + PROMPT_ID);
  }
} else {
  const V = JSON.parse(fs.readFileSync(path.join(REPO, 'prompts', 'variants-v5.json'), 'utf8'));
  const v = V.variants.find(x => x.id === PROMPT_ID);
  if (!v) throw new Error('unknown prompt ' + PROMPT_ID);
  sha = crypto.createHash('sha256').update(v.prompt, 'utf8').digest('hex');
  if (sha !== v.sha256) throw new Error('FROZEN PROMPT MISMATCH ' + PROMPT_ID);
  prompt = v.prompt;
}
if (NOASK) {
  prompt = prompt.replace(/\n+$/, '') + '\n\n' + NOASK_SUFFIX + '\n';
  sha = crypto.createHash('sha256').update(prompt, 'utf8').digest('hex');   // combined sha, recorded per draw
}

const HOMES = path.join(ROOT, 'homes'), TMP = path.join(ROOT, 'tmp');
const GEMINI_JS = process.env.LB_GEMINI_JS || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@google\\gemini-cli\\bundle\\gemini.js';
const CLAUDE_EXE = process.env.LB_CLAUDE_EXE || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe';
const CODEX_JS = process.env.LB_CODEX_JS || 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@openai\\codex\\bin\\codex.js';
function cleanEnv(extra) {
  return Object.assign({
    SystemRoot: 'C:\\Windows', windir: 'C:\\Windows',
    PATH: 'C:\\Windows\\System32;' + path.dirname(process.execPath),
    TEMP: TMP, TMP: TMP,
    USERPROFILE: path.join(HOMES, 'blank'), HOME: path.join(HOMES, 'blank'),
    APPDATA: path.join(HOMES, 'appdata'), LOCALAPPDATA: path.join(HOMES, 'localappdata'),
    PROGRAMDATA: 'C:\\ProgramData', COMSPEC: 'C:\\Windows\\System32\\cmd.exe',
    // MEASURED 2026-08-28: the CLI's default 32,000-token output cap truncated
    // 15 of 113 claude draws on the OPTIONS prompts (0 of 23 on the shorter
    // equity ones), and each truncation was banked as 'no-program' - read at
    // grading as a refusal or an ask. A ceiling inside the response
    // distribution makes the harness the measurement, exactly like the 20-min
    // timeout did. Raised well clear of the observed distribution.
    CLAUDE_CODE_MAX_OUTPUT_TOKENS: process.env.LB_MAX_OUTPUT_TOKENS || '64000',
  }, extra);
}
function extractProgram(text) {
  if (!text) return null;
  const fences = [...text.matchAll(/```(?:python)?\s*\n([\s\S]*?)```/g)].map(m => m[1]);
  const withQC = fences.filter(f => /QCAlgorithm/.test(f));
  const pick = (withQC.length ? withQC : fences).sort((a, b) => b.length - a.length)[0];
  if (pick) return pick;
  return /class\s+\w+\s*\(\s*QCAlgorithm\s*\)/.test(text) ? text : null;
}

// Batches are foldered by date, so a lane that spans midnight resumes into
// a NEW folder and redraws prompts already complete in yesterday's (found
// 2026-08-23: luna/xhigh drew 7 prompts on the 22nd, 13 on the 23rd).
// Analysis must therefore select ONE folder per (model, effort, condition)
// rather than pooling across dates - the redundant draws are real, valid
// data but would double-weight those prompts if pooled blindly.
const OUTDIR = path.join(REPO, 'batches', stamp);
fs.mkdirSync(OUTDIR, { recursive: true });
// ' -> 'p' so BL-02b' gets its own file (2026-08-22: bare stripping collided
// it with BL-02b and resume silently skipped the latter)
const SAFE_ID = PROMPT_ID.replace(/'/g, 'p').replace(/[^\w.-]/g, '');
const OUT = path.join(OUTDIR, `${SURFACE}_${MODEL.replace(/[^\w.-]/g, '')}_${EFFORT}_${SAFE_ID}${NOASK ? '_noask' : ''}.jsonl`);
const have = new Set();
// resume matches the PROMPT HASH per row, never just the index - a collided
// or mislabeled file can no longer suppress a different prompt's draws
// provider-blocked rows must NOT satisfy the resume set: they carry no
// observation, so a resume has to redraw them once the provider recovers.
if (fs.existsSync(OUT)) for (const l of fs.readFileSync(OUT, 'utf8').split('\n')) if (l.trim()) { const j = JSON.parse(l); if (j.status !== 'harness-error' && j.status !== 'provider-blocked' && j.prompt_sha256 === sha) have.add(j.i); }
fs.copyFileSync(PASS, path.join(OUTDIR, path.basename(PASS)));   // certificate ships beside the data

function draw(cwd) {
  if (SURFACE === 'codex') {
    const home = path.join(HOMES, 'codex');
    const lastMsg = path.join(cwd, 'last.txt');
    const r = spawnSync(process.execPath, [CODEX_JS, 'exec', '--skip-git-repo-check', '--ephemeral', '-s', 'read-only', '--json', '-o', lastMsg, '-m', MODEL, '-c', `model_reasoning_effort=${EFFORT}`, '-'],
      { input: prompt, encoding: 'utf8', cwd, env: cleanEnv({ CODEX_HOME: home }), shell: false, timeout: 20 * 60 * 1000, maxBuffer: 256 * 1024 * 1024 });
    return { raw_text: fs.existsSync(lastMsg) ? fs.readFileSync(lastMsg, 'utf8') : null, exit: r.status };
  }
  if (SURFACE === 'gemini') {
    const home = path.join(HOMES, 'gemini');
    const r = spawnSync(process.execPath, [GEMINI_JS, '-p', prompt, '-o', 'json', '--approval-mode', 'plan', '--skip-trust'],
      { encoding: 'utf8', cwd, env: cleanEnv({ USERPROFILE: home.replace(/\//g, '\\'), HOME: home }), shell: false, timeout: 20 * 60 * 1000, maxBuffer: 256 * 1024 * 1024 });
    const m = (r.stdout || '').match(/\{[\s\S]*\}/);
    let txt = null, served = null;
    if (m) { try { const j = JSON.parse(m[0]); txt = j.response ?? null; served = j.stats ? Object.keys(j.stats.models || {}) : null; } catch (e) {} }
    return { raw_text: txt, exit: r.status, served };
  }
  // MEASURED 2026-08-27: claude-sonnet-5 at max effort needs 11-17 min per draw
  // even when it SUCCEEDS, so a 20-minute ceiling sits inside the response
  // distribution rather than outside it - 46 of 66 draws died at exactly
  // 1,200,000 ms and were recorded as harness errors. The ceiling must be
  // outside the distribution or the timeout itself becomes the measurement.
  const CLAUDE_TIMEOUT_MS = parseInt(process.env.LB_CLAUDE_TIMEOUT_MIN || '40', 10) * 60 * 1000;
  const r = spawnSync(CLAUDE_EXE, ['-p', '--setting-sources', '', '--strict-mcp-config', '--tools', '', '--disable-slash-commands', '--model', MODEL, '--effort', EFFORT, '--output-format', 'json', '--no-session-persistence', '--max-turns', '1'],
    { input: prompt, encoding: 'utf8', cwd, env: cleanEnv({ CLAUDE_CONFIG_DIR: path.join(HOMES, 'claude-config') }), shell: false, timeout: CLAUDE_TIMEOUT_MS, maxBuffer: 256 * 1024 * 1024 });
  try { const j = JSON.parse(r.stdout); return { raw_text: j.result ?? null, exit: r.status, is_error: j.is_error }; }
  catch (e) { return { raw_text: null, exit: r.status }; }
}

// A PROVIDER message is not a model observation. A quota notice, a sign-in
// notice or a rate-limit notice arrives as ordinary assistant text with no
// program, and the old classifier recorded it as 'no-program' - which grading
// reads as a refusal or an ask. That is exactly how 1,673 cloud envelopes were
// once poisoned by "Not signed in". Measured here: 59 of 62 claude-sonnet draws
// were the single string "You've hit your session limit", banked as
// observations. These are marked 'provider-blocked' so they are never counted
// and are always retried (the resume set already excludes non-program rows).
const PROVIDER_BLOCKED = /limits?|quota|resets?|Not signed in|please (?:sign|log) ?in|credit balance|insufficient_quota|Overloaded|too many requests|429/i;
// STRUCTURAL net, independent of wording. Three literal-phrase patterns have
// now missed a real block in turn ("Not signed in" once, "session limit", then
// "weekly limit ... resets Sep 1" which slipped past a regex expecting a digit
// after "resets"). A genuine answer to these prompts takes MINUTES and runs to
// hundreds of characters; a sub-minute, sub-400-character reply with no program
// is a provider notice whatever it happens to say. Catching it by shape rather
// than by phrase is the only version that survives the next new message.
function looksBlocked(text, wallMs) {
  if (!text) return false;
  const t = String(text).trim();
  // The SHAPE test (short + fast = notice) is calibrated to claude-max, where
  // a real answer takes minutes. On codex LOW a genuine draw finishes in
  // 30-90 s and a genuine no-program answer can be short - measured live
  // 2026-08-28: "I couldn't create the .py file because this workspace is
  // read-only" (a REAL harness observation) was flagged as a provider block
  // and stopped the lane. Shape applies to claude only; codex/gemini rely on
  // wording.
  if (SURFACE === 'claude' && t.length < 400 && wallMs < 60 * 1000) return true;
  return t.length < 600 && PROVIDER_BLOCKED.test(t);          // wording
}

(async () => {
  let done = have.size;
  for (let i = 0; i < N; i++) {
    if (have.has(i)) continue;
    const cwd = fs.mkdtempSync(path.join(ROOT, 'runs', 'gen-'));
    const t0 = Date.now();
    const res = draw(cwd);
    const program = extractProgram(res.raw_text || '');
    // A truncated response is neither an answer nor a refusal - the model was
    // cut off mid-program by a harness ceiling. harness-error, so the resume
    // set redraws it and grading never sees it.
    const truncated = !program && res.raw_text
      && /output token maximum|max_tokens|exceeded the [\d,]+ output/i.test(res.raw_text);
    const blocked = !program && !truncated && looksBlocked(res.raw_text, Date.now() - t0);
    const env = { surface: SURFACE, model: MODEL, effort: EFFORT, prompt_id: PROMPT_ID, condition: NOASK ? 'noask' : 'base', prompt_sha256: sha, i,
                  status: (res.raw_text === null || truncated) ? 'harness-error' : (program ? 'program' : (blocked ? 'provider-blocked' : 'no-program')),
                  raw_text: res.raw_text, program, wall_ms: Date.now() - t0, canary: path.basename(PASS) };
    fs.appendFileSync(OUT, JSON.stringify(env) + '\n');
    if (blocked) {
      console.error(`PROVIDER BLOCKED at draw #${i}: ${String(res.raw_text).trim().slice(0, 120)}`);
      console.error('stopping this cell rather than banking provider messages as observations');
      process.exit(3);
    }
    // Cleanup must never kill the cell. On Windows the just-exited CLI can
    // still hold a handle in this temp dir, and rmdir then throws EBUSY -
    // measured 2026-08-27 with 6 concurrent claude cells, which crashed 25 of
    // 26 of them. The draw row is already durably appended above, so a failed
    // cleanup costs a leftover temp dir and nothing else.
    try { fs.rmSync(cwd, { recursive: true, force: true }); }
    catch (e) { console.error(`cleanup skipped for ${cwd}: ${e.code || e.message}`); }
    done++;
    console.log(`[${done}/${N}] ${MODEL}/${EFFORT} ${PROMPT_ID} #${i} ${env.status} ${Math.round(env.wall_ms / 1000)}s`);
  }
  console.log('LANE DONE');
})();
