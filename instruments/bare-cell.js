'use strict';
// H5 bare-model cells (HYPOTHESES.md SS A2): the frozen BL-01b prompt, one
// identical minimal system line, pinned models, no vendor harness.
//   node bare-cell.js openai gpt-5.6-luna high 30
//   node bare-cell.js vertex gemini-3.6-flash high 30
// claude's near-bare cell runs via the CLI --system-prompt path separately.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execSync } = require('child_process');

const REPO = path.resolve(__dirname, '..');
const [SURFACE, MODEL, EFFORT, N_STR] = process.argv.slice(2);
const N = parseInt(N_STR || '30', 10);
const SYSTEM_LINE = 'Complete the task.';

const V = JSON.parse(fs.readFileSync(path.join(REPO, 'prompts', 'variants-v5.json'), 'utf8'));
const v = V.variants.find(x => x.id === 'BL-01b');
if (crypto.createHash('sha256').update(v.prompt, 'utf8').digest('hex') !== v.sha256) throw new Error('FROZEN PROMPT MISMATCH');

const OUTDIR = path.join(REPO, 'batches', 'h5');
fs.mkdirSync(OUTDIR, { recursive: true });
const OUT = path.join(OUTDIR, `bare_${SURFACE}_${MODEL.replace(/[^\w.-]/g, '')}_${EFFORT}.jsonl`);
const have = new Set();
if (fs.existsSync(OUT)) for (const l of fs.readFileSync(OUT, 'utf8').split('\n')) if (l.trim()) { const j = JSON.parse(l); if (j.status !== 'harness-error') have.add(j.i); }

const OPENAI_KEY = (fs.readFileSync(path.join(REPO, '.env'), 'utf8').match(/OPENAI_API_KEY\s*=\s*["']?([^\s"']+)/) || [])[1];
const VERTEX = { project: 'project-627ff42f-869d-48b1-919', location: 'us-central1' };
// thinking budgets per the archived roster's ladder (gen_drivers VERTEX_BUDGET shape)
const VERTEX_THINKING = { low: 512, medium: 2048, high: 8192, xhigh: 16384, max: 24576 };

async function drawOpenAI() {
  const r = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST', headers: { Authorization: `Bearer ${OPENAI_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: MODEL, reasoning: { effort: EFFORT }, max_output_tokens: 32768,
      instructions: SYSTEM_LINE, input: v.prompt }),
    signal: AbortSignal.timeout(20 * 60 * 1000) });
  const j = await r.json();
  if (j.error) return { raw_text: null, error: String(j.error.message).slice(0, 200) };
  const txt = (j.output || []).map(o => (o.content || []).map(c => c.text || '').join('')).join('');
  return { raw_text: txt || null, served: j.model, usage: j.usage && { in: j.usage.input_tokens, out: j.usage.output_tokens } };
}

async function drawVertex() {
  const token = execSync('gcloud auth print-access-token', { encoding: 'utf8' }).trim();
  const url = `https://aiplatform.googleapis.com/v1/projects/${VERTEX.project}/locations/${VERTEX.location}/publishers/google/models/${MODEL}:generateContent`;
  const r = await fetch(url, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ systemInstruction: { parts: [{ text: SYSTEM_LINE }] },
      contents: [{ role: 'user', parts: [{ text: v.prompt }] }],
      generationConfig: { maxOutputTokens: 65535, thinkingConfig: { thinkingBudget: VERTEX_THINKING[EFFORT] } } }),
    signal: AbortSignal.timeout(20 * 60 * 1000) });
  const j = await r.json();
  if (j.error) return { raw_text: null, error: String(j.error.message).slice(0, 200) };
  const txt = (j.candidates || []).flatMap(c => (c.content && c.content.parts) || []).map(p => p.text || '').join('');
  return { raw_text: txt || null, served: j.modelVersion, usage: j.usageMetadata };
}

function drawClaudeNearBare() {
  const { spawnSync } = require('child_process');
  const HOMES = 'C:/lbres/homes', TMP = 'C:/lbres/tmp';
  const EXE = 'C:\\Users\\joshp\\AppData\\Roaming\\npm\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe';
  const env = {
    SystemRoot: 'C:\\Windows', windir: 'C:\\Windows',
    PATH: 'C:\\Windows\\System32;' + path.dirname(process.execPath),
    TEMP: TMP, TMP: TMP,
    USERPROFILE: path.join(HOMES, 'blank'), HOME: path.join(HOMES, 'blank'),
    APPDATA: path.join(HOMES, 'appdata'), LOCALAPPDATA: path.join(HOMES, 'localappdata'),
    PROGRAMDATA: 'C:\\ProgramData', COMSPEC: 'C:\\Windows\\System32\\cmd.exe',
    CLAUDE_CONFIG_DIR: path.join(HOMES, 'claude-config'),
  };
  const cwd = fs.mkdtempSync('C:/lbres/runs/h5cl-');
  const r = spawnSync(EXE, ['-p', '--setting-sources', '', '--strict-mcp-config', '--tools', '', '--disable-slash-commands',
    '--system-prompt', SYSTEM_LINE, '--model', MODEL, '--effort', EFFORT, '--output-format', 'json', '--no-session-persistence', '--max-turns', '1'],
    { input: v.prompt, encoding: 'utf8', cwd, env, shell: false, timeout: 20 * 60 * 1000, maxBuffer: 256 * 1024 * 1024 });
  fs.rmSync(cwd, { recursive: true, force: true });
  try { const j = JSON.parse(r.stdout); return { raw_text: j.result ?? null, served: MODEL }; }
  catch (e) { return { raw_text: null, error: (r.stderr || r.stdout || 'no output').slice(0, 200) }; }
}

function extractProgram(text) {
  if (!text) return null;
  const fences = [...text.matchAll(/```(?:python)?\s*\n([\s\S]*?)```/g)].map(m => m[1]);
  const withQC = fences.filter(f => /QCAlgorithm/.test(f));
  const pick = (withQC.length ? withQC : fences).sort((a, b) => b.length - a.length)[0];
  if (pick) return pick;
  return /class\s+\w+\s*\(\s*QCAlgorithm\s*\)/.test(text) ? text : null;
}

(async () => {
  let done = have.size;
  for (let i = 0; i < N; i++) {
    if (have.has(i)) continue;
    const t0 = Date.now();
    let res;
    try { res = SURFACE === 'openai' ? await drawOpenAI() : SURFACE === 'claude' ? drawClaudeNearBare() : await drawVertex(); }
    catch (e) { res = { raw_text: null, error: String(e.message).slice(0, 200) }; }
    const program = extractProgram(res.raw_text || '');
    const env = { leg: 'H5-bare', surface: SURFACE, model: MODEL, effort: EFFORT, prompt_id: 'BL-01b',
      system_line: SYSTEM_LINE, prompt_sha256: v.sha256, i,
      status: res.raw_text === null ? 'harness-error' : (program ? 'program' : 'no-program'),
      raw_text: res.raw_text, program, served: res.served || null, usage: res.usage || null,
      error: res.error || null, wall_ms: Date.now() - t0 };
    fs.appendFileSync(OUT, JSON.stringify(env) + '\n');
    done++;
    console.log(`[${done}/${N}] bare ${MODEL}/${EFFORT} #${i} ${env.status} served=${env.served} ${Math.round(env.wall_ms / 1000)}s`);
  }
  console.log('BARE CELL DONE', SURFACE, MODEL);
})();
