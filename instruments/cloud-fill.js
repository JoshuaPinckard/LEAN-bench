'use strict';
// Sustained-pace filler for the cloud lane. Cycles every target lane,
// launching only the draws still missing, at a rate that stays under the
// provider's limit (bursts of 20 drew 429s). Runs until every lane is full
// or the deadline passes, whichever comes first.
//   node cloud-fill.js <env-id> <repo> <branch> <minutes> [conc]
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const [ENV_ID, REPO, BRANCH, MIN_STR, CONC_STR] = process.argv.slice(2);
const DEADLINE = Date.now() + parseInt(MIN_STR || '60', 10) * 60 * 1000;
const CONC = CONC_STR || '6';
const REPO_ROOT = path.resolve(__dirname, '..');

// prompt -> target n, ordered by scientific value: the period cell is the
// headline (bare 0.00 vs CLI 0.50), then the harness variant, then the union
// and type cells, then the benchmark's free-parameter prompts.
const TARGETS = (process.env.LB_TARGETS ? JSON.parse(process.env.LB_TARGETS) : [
  ['BL-01b', 40, 1], ['BL-01b', 30, 4], ['BL-01c', 40, 1], ['BL-01a', 30, 1],
  ['T1v0', 30, 1], ['BL-03', 30, 1], ['BL-05', 30, 1], ['BL-08', 30, 1], ['ER-01', 30, 1],
]);

function countLaunched(prompt, attempts, noask) {
  const safe = prompt.replace(/'/g, 'p').replace(/[^\w.-]/g, '');
  const f = path.join(REPO_ROOT, 'batches', 'cloud', `cloud_${safe}_attempts${attempts}${noask ? '_noask' : ''}.jsonl`);
  if (!fs.existsSync(f)) return 0;
  let n = 0;
  for (const l of fs.readFileSync(f, 'utf8').split('\n')) if (l.trim() && JSON.parse(l).task_id) n++;
  return n;
}

function runLane(prompt, n, attempts, noask) {
  return new Promise(resolve => {
    const args = [path.join(__dirname, 'cloud-lane.js'), ENV_ID, REPO, BRANCH, prompt, String(n), String(attempts), CONC];
    if (noask) args.push('noask');
    const p = spawn(process.execPath, args, { shell: false, windowsHide: true });
    let out = '';
    p.stdout.on('data', d => { out += d; });
    p.stderr.on('data', d => { out += d; });
    p.on('close', () => {
      const m = out.match(/(\d+) launched, (\d+) failed/);
      resolve(m ? { ok: +m[1], fail: +m[2] } : { ok: 0, fail: 0 });
    });
  });
}

(async () => {
  let pass = 0;
  while (Date.now() < DEADLINE) {
    pass++;
    let remaining = 0;
    for (const [prompt, target, attempts, mode] of TARGETS) {
      if (Date.now() >= DEADLINE) break;
      const noask = mode === 'noask';
      const have = countLaunched(prompt, attempts, noask);
      if (have >= target) continue;
      remaining += target - have;
      const r = await runLane(prompt, target, attempts, noask);
      const now = countLaunched(prompt, attempts, noask);
      console.log(`pass ${pass} ${prompt} a${attempts}${noask ? ' noask' : ''}: ${now}/${target} launched (+${r.ok}, ${r.fail} refused)`);
      // breathe between lanes so the burst rate stays under the limit
      await new Promise(r2 => setTimeout(r2, 20000));
    }
    if (remaining === 0) { console.log('ALL LANES FULL'); break; }
    console.log(`--- pass ${pass} done; cooling 60s before the next sweep`);
    await new Promise(r => setTimeout(r, 60000));
  }
  console.log('FILL DRIVER FINISHED');
  for (const [prompt, target, attempts, mode] of TARGETS) {
    console.log(`  ${prompt} attempts=${attempts}${mode === 'noask' ? ' noask' : ''}: ${countLaunched(prompt, attempts, mode === 'noask')}/${target}`);
  }
})();
