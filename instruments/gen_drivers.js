'use strict';
// Generation drivers v2 — PIN-v5 SS7 hygiene (vetting-council round 1).
//   * spawn WITHOUT a shell (resolved native entry points) so argv is exact
//     — the v1 shell:true path word-split the system prompt and dropped the
//     empty --tools "" / --setting-sources "" values (fable-1/2/3 #1)
//   * Claude: NO --bare (it forces API-key auth and would bill the user-scope
//     ANTHROPIC_API_KEY instead of the pinned Max subscription); instead
//     --setting-sources "" --strict-mcp-config --tools "" --disable-slash-commands
//     --system-prompt-file --no-session-persistence --max-turns 1, and the
//     child env has ANTHROPIC_API_KEY REMOVED so OAuth (Max) is the only auth
//   * codex: CODEX_HOME = a fresh dir holding ONLY auth.json (no config.toml,
//     no AGENTS.md, no MCP/plugins), --ignore-user-config --ephemeral,
//     --json events (served model + tool-use are STRUCTURAL), -o last message
//   * Vertex: maxOutputTokens = 65535 (>= any thinkingBudget + answer),
//     generationConfig + finishReason echoed verbatim
//   * ONE program-extraction rule for every surface; every driver records
//     CLI version, exact argv, full raw stdout/stderr, auth mode, isolation
//     record; transport failures return status 'harness-error' (never a
//     model result)
const { spawnSync, execSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const NPM = path.join(process.env.APPDATA || '', 'npm', 'node_modules');
const CLAUDE_EXE = path.join(NPM, '@anthropic-ai', 'claude-code', 'bin', 'claude.exe');
const CODEX_JS = path.join(NPM, '@openai', 'codex', 'bin', 'codex.js');
const NODE = process.execPath;

// The prompt sent is the frozen variant text ONLY (it already carries the
// output instruction). No system sentence on any surface (fable-3 #18).
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];
const VERTEX_BUDGET = {
  'gemini-2.5-pro': { low: 128, medium: 2048, high: 8192, xhigh: 16384, max: 32768 },
  'gemini-2.5-flash': { low: 0, medium: 2048, high: 8192, xhigh: 16384, max: 24576 },
  'gemini-2.5-flash-lite': { low: 0, medium: 2048, high: 8192, xhigh: 16384, max: 24576 },
};
const VERTEX_MAX_OUTPUT = 65535;
const VERTEX_PROJECT = 'project-627ff42f-869d-48b1-919';
const VERTEX_LOCATION = 'us-central1';

const sha256 = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex');

let _versions = null;
function cliVersions() {
  if (_versions) return _versions;
  const v = (cmd, args) => { try { return spawnSync(cmd, args, { encoding: 'utf8', shell: false, timeout: 60000 }).stdout.trim(); } catch (e) { return 'unknown'; } };
  _versions = { claude: v(CLAUDE_EXE, ['--version']), codex: v(NODE, [CODEX_JS, '--version']), node: process.version,
    harness_git: (() => { try { return execSync('git rev-parse --short HEAD', { cwd: path.resolve(__dirname, '..'), encoding: 'utf8' }).trim(); } catch (e) { return 'unknown'; } })() };
  return _versions;
}

// ---------------------------------------------------------------- isolation
const GLOBAL_PROFILE_FILES = ['CLAUDE.md', 'AGENTS.md', 'CODEX.md', 'GEMINI.md',
  path.join('.claude', 'CLAUDE.md'), path.join('.claude', 'settings.json'), path.join('.claude', 'settings.local.json'),
  path.join('.codex', 'AGENTS.md'), path.join('.codex', 'config.toml')];

function freshDir(prefix) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  return d;
}

function isolationRecord(cwd) {
  // (a) every ancestor of cwd, every profile-ish file, with sha (found = recorded, not just boolean)
  const found = [];
  let cur = cwd;
  while (true) {
    for (const f of GLOBAL_PROFILE_FILES) { const p = path.join(cur, f); if (fs.existsSync(p)) found.push({ path: p, sha256: sha256(fs.readFileSync(p, 'utf8')) }); }
    const up = path.dirname(cur); if (up === cur) break; cur = up;
  }
  // (b) the user's global instruction files, wherever cwd is
  const home = os.homedir();
  const globals = [];
  for (const f of GLOBAL_PROFILE_FILES) { const p = path.join(home, f); if (fs.existsSync(p)) globals.push({ path: p, sha256: sha256(fs.readFileSync(p, 'utf8')) }); }
  const cwdEmpty = fs.readdirSync(cwd).length === 0;
  return { cwd, cwd_empty: cwdEmpty, ancestor_profiles: found, global_profiles_present: globals };
}

// ---------------------------------------------------------------- program extraction (ONE rule, all surfaces)
function extractProgram(text) {
  if (!text) return { program: null, rule: 'no-text' };
  const fences = [...text.matchAll(/```(?:python|py)?\s*\n([\s\S]*?)```/gi)].map(m => m[1]);
  const withQC = fences.filter(f => /QCAlgorithm/.test(f));
  if (withQC.length) { withQC.sort((a, b) => b.length - a.length); return { program: withQC[0], rule: 'largest-fenced-QCAlgorithm' }; }
  if (fences.length) { fences.sort((a, b) => b.length - a.length); return { program: fences[0], rule: 'largest-fenced' }; }
  if (/class\s+\w+\s*\(\s*QCAlgorithm\s*\)/.test(text)) return { program: text, rule: 'raw-text-QCAlgorithm' };
  return { program: null, rule: 'none' };
}

function baseEnvelope(surface, model, effort, prompt, cwd) {
  return {
    schema: 'lb-envelope-v2', surface, model, effort_rank: effort,
    prompt_sha256: sha256(prompt), prompt_chars: prompt.length,
    started_at: new Date().toISOString(), finished_at: null,
    host: { platform: process.platform, hostname: os.hostname(), date_local: new Date().toLocaleDateString('en-CA') },
    versions: cliVersions(), isolation: isolationRecord(cwd),
    status: null, program: null, extract_rule: null, used_tools: null,
  };
}

// ---------------------------------------------------------------- claude
function genClaude({ model, effort, prompt }) {
  if (!EFFORTS.includes(effort)) throw new Error('bad effort ' + effort);
  const cwd = freshDir('lb-claude-');
  const env = baseEnvelope('claude-cli', model, effort, prompt, cwd);
  // FUNDING FENCE (owner rule: subscription only, never the API). Deleting the
  // two key names is not enough — an inherited ANTHROPIC_BASE_URL or a
  // Bedrock/Vertex switch routes the same call to a METERED endpoint (B8).
  // Strip every routing/credential name and RECORD what was found.
  const childEnv = { ...process.env };
  const BILLING_ENV = [
    'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_MODEL',
    'ANTHROPIC_SMALL_FAST_MODEL', 'ANTHROPIC_CUSTOM_HEADERS', 'ANTHROPIC_API_URL',
    'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_SKIP_BEDROCK_AUTH',
    'CLAUDE_CODE_SKIP_VERTEX_AUTH', 'ANTHROPIC_VERTEX_PROJECT_ID', 'ANTHROPIC_BEDROCK_BASE_URL',
    'ANTHROPIC_VERTEX_BASE_URL', 'AWS_BEARER_TOKEN_BEDROCK', 'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_PROFILE', 'AWS_REGION',
    'GOOGLE_APPLICATION_CREDENTIALS', 'CLOUD_ML_REGION',
  ];
  const stripped = BILLING_ENV.filter((k) => childEnv[k] !== undefined);
  for (const k of BILLING_ENV) delete childEnv[k];
  delete childEnv.ELECTRON_RUN_AS_NODE;
  const args = ['-p', '--setting-sources', '', '--strict-mcp-config', '--tools', '', '--disable-slash-commands',
    '--model', model, '--effort', effort, '--output-format', 'json', '--no-session-persistence', '--max-turns', '1'];
  env.argv = [CLAUDE_EXE, ...args];
  // an OBSERVATION of what was stripped, not an assertion of a mode
  env.billing_env_stripped = stripped;
  env.auth_mode = stripped.length
    ? `subscription-intended; stripped: ${stripped.join(',')}`
    : 'subscription-intended; no metered-routing vars present';
  const t0 = Date.now();
  const r = spawnSync(CLAUDE_EXE, args, { input: prompt, encoding: 'utf8', cwd, env: childEnv, shell: false,
    timeout: 20 * 60 * 1000, maxBuffer: 256 * 1024 * 1024, killSignal: 'SIGKILL' });
  env.wall_ms = Date.now() - t0; env.finished_at = new Date().toISOString();
  env.exit_code = r.status; env.spawn_error = r.error ? String(r.error.message) : null;
  env.raw_stdout = r.stdout || ''; env.raw_stderr = r.stderr || '';
  if (r.error || r.status === null) { env.status = 'harness-error'; return env; }
  let j = null;
  try { j = JSON.parse(r.stdout); } catch (e) { env.parse_error = String(e.message).slice(0, 200); }
  if (!j) { env.status = (r.status === 0) ? 'no-program' : 'harness-error'; env.raw_text = r.stdout || null; return env; }
  env.response_meta = { is_error: j.is_error, num_turns: j.num_turns, duration_ms: j.duration_ms, duration_api_ms: j.duration_api_ms,
    total_cost_usd: j.total_cost_usd, usage: j.usage || null, modelUsage: j.modelUsage || null, session_id: j.session_id,
    model_served: j.modelUsage ? Object.keys(j.modelUsage) : null, permission_denials: j.permission_denials || null };
  if (j.is_error) { env.status = 'harness-error'; env.raw_text = j.result || null; return env; }
  env.raw_text = j.result ?? null;
  const ex = extractProgram(env.raw_text);
  env.program = ex.program; env.extract_rule = ex.rule;
  env.used_tools = (j.num_turns || 1) > 1;   // tools are disabled; >1 turn would be anomalous and is recorded
  env.status = env.program ? 'program' : 'no-program';
  return env;
}

// ---------------------------------------------------------------- codex
let _codexHome = null;
function codexHome() {
  // fresh CODEX_HOME containing ONLY auth.json (copied from the real one)
  if (_codexHome && fs.existsSync(path.join(_codexHome, 'auth.json'))) return _codexHome;
  const real = process.env.CODEX_HOME || path.join(os.homedir(), '.codex');
  const auth = path.join(real, 'auth.json');
  if (!fs.existsSync(auth)) throw new Error('codex auth.json not found at ' + auth);
  _codexHome = freshDir('lb-codex-home-');
  fs.copyFileSync(auth, path.join(_codexHome, 'auth.json'));
  return _codexHome;
}

function genCodex({ model, effort, prompt }) {
  if (!EFFORTS.includes(effort) && effort !== 'ultra') throw new Error('bad effort ' + effort);
  const cwd = freshDir('lb-codex-');
  const env = baseEnvelope('codex-exec', model, effort, prompt, cwd);
  const home = codexHome();
  const lastMsg = path.join(cwd, 'last-message.txt');
  const args = [CODEX_JS, 'exec', '--skip-git-repo-check', '--ignore-user-config', '--ephemeral', '-s', 'read-only',
    '--json', '-o', lastMsg, '-m', model, '-c', `model_reasoning_effort=${effort}`, '-'];
  env.argv = [NODE, ...args];
  env.codex_home = { path: home, files: fs.readdirSync(home) };
  env.auth_mode = 'codex auth.json copied into fresh CODEX_HOME (no config/AGENTS/MCP/plugins)';
  const childEnv = { ...process.env, CODEX_HOME: home };
  const t0 = Date.now();
  const r = spawnSync(NODE, args, { input: prompt, encoding: 'utf8', cwd, env: childEnv, shell: false,
    timeout: 20 * 60 * 1000, maxBuffer: 256 * 1024 * 1024, killSignal: 'SIGKILL' });
  env.wall_ms = Date.now() - t0; env.finished_at = new Date().toISOString();
  env.exit_code = r.status; env.spawn_error = r.error ? String(r.error.message) : null;
  env.raw_stdout = r.stdout || ''; env.raw_stderr = r.stderr || '';
  if (r.error || r.status === null) { env.status = 'harness-error'; return env; }
  // structural telemetry from the JSONL event stream
  const events = [];
  for (const line of (r.stdout || '').split('\n')) { const s = line.trim(); if (!s.startsWith('{')) continue; try { events.push(JSON.parse(s)); } catch (e) { /* ignore */ } }
  const types = events.map(e => e.type || e.msg?.type || '').filter(Boolean);
  const toolish = events.filter(e => /exec|command|tool|mcp|patch|web_search/i.test(JSON.stringify(e).slice(0, 400)) && !/agent_message|reasoning|token_count|session_configured|task_started|task_complete|item\.completed/i.test((e.type || '') + (e.msg?.type || '')));
  const cfg = events.find(e => /session_configured|thread\.started/i.test(JSON.stringify(e).slice(0, 200)));
  env.response_meta = { event_types: [...new Set(types)], n_events: events.length,
    session_configured: cfg ? JSON.stringify(cfg).slice(0, 600) : null,
    model_served: (cfg && (cfg.msg?.model || cfg.model || (JSON.stringify(cfg).match(/"model"\s*:\s*"([^"]+)"/) || [])[1])) || null,
    reasoning_effort: (JSON.stringify(cfg || {}).match(/"reasoning_effort"\s*:\s*"([^"]+)"/) || [])[1] || null,
    tool_events: toolish.length };
  env.used_tools = toolish.length > 0;
  env.raw_text = fs.existsSync(lastMsg) ? fs.readFileSync(lastMsg, 'utf8') : null;
  if (r.status !== 0 && !env.raw_text) { env.status = 'harness-error'; return env; }
  const ex = extractProgram(env.raw_text);
  env.program = ex.program; env.extract_rule = ex.rule;
  env.status = env.program ? 'program' : 'no-program';
  return env;
}

// ---------------------------------------------------------------- vertex
async function genVertex({ model, effort, prompt }) {
  if (!EFFORTS.includes(effort)) throw new Error('bad effort ' + effort);
  const cwd = freshDir('lb-vertex-');
  const env = baseEnvelope('vertex-rest', model, effort, prompt, cwd);
  const budget = VERTEX_BUDGET[model][effort];
  const generationConfig = { maxOutputTokens: VERTEX_MAX_OUTPUT, thinkingConfig: { thinkingBudget: budget } };
  env.request = { model, location: VERTEX_LOCATION, generationConfig };
  env.auth_mode = 'gcloud application token';
  let token;
  try { token = execSync('gcloud auth print-access-token', { encoding: 'utf8' }).trim(); }
  catch (e) { env.status = 'harness-error'; env.spawn_error = 'gcloud token: ' + e.message; return env; }
  const url = `https://aiplatform.googleapis.com/v1/projects/${VERTEX_PROJECT}/locations/${VERTEX_LOCATION}/publishers/google/models/${model}:generateContent`;
  const t0 = Date.now();
  let res, body;
  try {
    res = await fetch(url, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ contents: [{ role: 'user', parts: [{ text: prompt }] }], generationConfig }),
      signal: AbortSignal.timeout(20 * 60 * 1000) });
    body = await res.json();
  } catch (e) { env.status = 'harness-error'; env.spawn_error = String(e.message); env.wall_ms = Date.now() - t0; return env; }
  env.wall_ms = Date.now() - t0; env.finished_at = new Date().toISOString();
  env.exit_code = res.status;
  env.raw_stdout = JSON.stringify(body).slice(0, 2_000_000);
  if (!res.ok) { env.status = 'harness-error'; env.error = JSON.stringify(body.error || body).slice(0, 600); return env; }
  const cand = (body.candidates || [])[0] || {};
  const text = cand.content?.parts?.map(p => p.text).join('') || null;
  env.response_meta = { model_served: body.modelVersion || null, usage: body.usageMetadata || null, finish_reason: cand.finishReason || null,
    block_reason: body.promptFeedback?.blockReason || null, truncated: cand.finishReason === 'MAX_TOKENS' };
  // B5: a SAFETY/BLOCK outcome is a harness-side event, never a model result —
  // coding it "no-program" would attribute the provider's filter to the model
  if (!body.candidates?.length || ['SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'RECITATION'].includes(cand.finishReason)) {
    env.status = 'harness-error'; env.error = 'blocked/no-candidates: ' + (body.promptFeedback?.blockReason || cand.finishReason || 'empty'); return env;
  }
  env.raw_text = text;
  const ex = extractProgram(text);
  env.program = ex.program; env.extract_rule = ex.rule; env.used_tools = false;
  // B5: a MAX_TOKENS response is truncated even when a program-shaped fragment
  // is extractable — a cut-off program is not the model's answer
  if (cand.finishReason === 'MAX_TOKENS') { env.status = 'harness-truncation'; return env; }
  env.status = env.program ? 'program' : 'no-program';
  return env;
}

// ---------------------------------------------------------------- self-test (argv fidelity)
function argvSelfTest() {
  // proves the drivers' argv reaches the child EXACTLY (no shell joining)
  const stub = path.join(os.tmpdir(), 'lb-argecho.js');
  fs.writeFileSync(stub, 'process.stdout.write(JSON.stringify(process.argv.slice(2)))');
  const args = ['-p', '--setting-sources', '', '--strict-mcp-config', '--tools', '', '--system-prompt', 'You are a QuantConnect LEAN (Python) author.'];
  const r = spawnSync(NODE, [stub, ...args], { encoding: 'utf8', shell: false });
  const got = JSON.parse(r.stdout);
  const ok = JSON.stringify(got) === JSON.stringify(args);
  return { ok, expected: args, got };
}

module.exports = { genClaude, genCodex, genVertex, EFFORTS, VERTEX_BUDGET, extractProgram, isolationRecord, cliVersions, argvSelfTest, freshDir, CLAUDE_EXE, CODEX_JS };
