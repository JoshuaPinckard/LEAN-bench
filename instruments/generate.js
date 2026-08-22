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

const [SURFACE, MODEL, EFFORT, PROMPT_ID, N_STR] = process.argv.slice(2);
const N = parseInt(N_STR || '10', 10);
if (!SURFACE || !MODEL || !EFFORT || !PROMPT_ID) { console.error('usage: generate.js <surface> <model> <effort> <prompt-id> <n>'); process.exit(2); }

const REPO = path.resolve(__dirname, '..');
let prompt, sha;
if (PROMPT_ID === 'T1v0') {
  prompt = fs.readFileSync(path.join(REPO, 'prompts', 'T1v0.txt'), 'utf8');
  sha = crypto.createHash('sha256').update(prompt, 'utf8').digest('hex');
} else {
  const V = JSON.parse(fs.readFileSync(path.join(REPO, 'prompts', 'variants-v5.json'), 'utf8'));
  const v = V.variants.find(x => x.id === PROMPT_ID);
  if (!v) throw new Error('unknown prompt ' + PROMPT_ID);
  sha = crypto.createHash('sha256').update(v.prompt, 'utf8').digest('hex');
  if (sha !== v.sha256) throw new Error('FROZEN PROMPT MISMATCH ' + PROMPT_ID);
  prompt = v.prompt;
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

const OUTDIR = path.join(REPO, 'batches', stamp);
fs.mkdirSync(OUTDIR, { recursive: true });
const OUT = path.join(OUTDIR, `${SURFACE}_${MODEL.replace(/[^\w.-]/g, '')}_${EFFORT}_${PROMPT_ID.replace(/[^\w.-]/g, '')}.jsonl`);
const have = new Set();
if (fs.existsSync(OUT)) for (const l of fs.readFileSync(OUT, 'utf8').split('\n')) if (l.trim()) { const j = JSON.parse(l); if (j.status !== 'harness-error') have.add(j.i); }
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
  const r = spawnSync(CLAUDE_EXE, ['-p', '--setting-sources', '', '--strict-mcp-config', '--tools', '', '--disable-slash-commands', '--model', MODEL, '--effort', EFFORT, '--output-format', 'json', '--no-session-persistence', '--max-turns', '1'],
    { input: prompt, encoding: 'utf8', cwd, env: cleanEnv({ CLAUDE_CONFIG_DIR: path.join(HOMES, 'claude-config') }), shell: false, timeout: 20 * 60 * 1000, maxBuffer: 256 * 1024 * 1024 });
  try { const j = JSON.parse(r.stdout); return { raw_text: j.result ?? null, exit: r.status, is_error: j.is_error }; }
  catch (e) { return { raw_text: null, exit: r.status }; }
}

(async () => {
  let done = have.size;
  for (let i = 0; i < N; i++) {
    if (have.has(i)) continue;
    const cwd = fs.mkdtempSync(path.join(ROOT, 'runs', 'gen-'));
    const t0 = Date.now();
    const res = draw(cwd);
    const program = extractProgram(res.raw_text || '');
    const env = { surface: SURFACE, model: MODEL, effort: EFFORT, prompt_id: PROMPT_ID, prompt_sha256: sha, i,
                  status: res.raw_text === null ? 'harness-error' : (program ? 'program' : 'no-program'),
                  raw_text: res.raw_text, program, wall_ms: Date.now() - t0, canary: path.basename(PASS) };
    fs.appendFileSync(OUT, JSON.stringify(env) + '\n');
    fs.rmSync(cwd, { recursive: true, force: true });
    done++;
    console.log(`[${done}/${N}] ${MODEL}/${EFFORT} ${PROMPT_ID} #${i} ${env.status} ${Math.round(env.wall_ms / 1000)}s`);
  }
  console.log('LANE DONE');
})();
