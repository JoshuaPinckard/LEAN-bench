'use strict';
// Run any command with the owner's GitHub PAT injected from the ToolsEnabled
// DPAPI vault as GH_TOKEN. Mirrors Options-AI/instruments/with-databento-key.js.
// The token never appears in argv, logs, or on disk; git pushes use an inline
// credential helper that reads it from the environment.
//
//   node instruments/with-github-pat.js gh api user --jq .login
//   node instruments/with-github-pat.js git push <remote> <branch>
//
// Hidden native boundary (windowsHide:true, shell:false) per STANDING-ORDERS
// LOCAL-WORK rule 3.
const { spawn } = require('child_process');

const TE = 'C:\\Users\\joshp\\Desktop\\toolsenabled-current';
const SECRET = process.env.LB_GITHUB_SECRET_NAME || 'github_pat';
const [cmd, ...rest] = process.argv.slice(2);
if (!cmd) { console.error('usage: with-github-pat.js <command> [args...]'); process.exit(2); }

const g = spawn('powershell.exe',
  ['-NoProfile', '-File', '.\\tools\\secrets.ps1', 'get', SECRET],
  { cwd: TE, shell: false, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });

let out = '', err = '';
g.stdout.on('data', d => { out += d; });
g.stderr.on('data', d => { err += d; });
g.on('error', e => { console.error('vault spawn failed:', e.message); process.exit(3); });
g.on('close', code => {
  const token = out.trim();
  if (code !== 0 || !token) {
    console.error('vault get failed (exit ' + code + '):', err.trim().slice(0, 200));
    process.exit(3);
  }
  console.error(`github token from vault: ${token.length} chars (never printed)`);
  // git: inline credential helper so the token stays out of argv and config.
  const gitArgs = cmd === 'git'
    ? ['-c', 'credential.helper=', '-c',
       'credential.helper=!f() { echo username=x-access-token; echo password=$GH_TOKEN; }; f',
       ...rest]
    : rest;
  const child = spawn(cmd, gitArgs, {
    shell: false, windowsHide: true, stdio: ['ignore', 'inherit', 'inherit'],
    env: Object.assign({}, process.env, { GH_TOKEN: token, GITHUB_TOKEN: token, GIT_TERMINAL_PROMPT: '0' }),
  });
  child.on('error', e => { console.error('command spawn failed:', e.message); process.exit(4); });
  child.on('close', c => process.exit(c));
});
