'use strict';
// One benchmark lane = one model x effort x condition across all 13
// prompts (HYPOTHESES.md SS B), n=10 each, sequential. Usage:
//   node bench-lane.js <surface> <model> <effort> [noask]
// Just a loop over generate.js so every draw goes through its canary
// gate, frozen-hash check, and envelope format unchanged.
const { spawnSync } = require('child_process');
const path = require('path');

const PROMPTS = ['BL-03', 'BL-05', 'BL-08', 'BL-07', 'BL-04', 'OM-B', 'OM-C',
                 'ER-01', 'ER-01c', 'BL-00', "BL-02b'", 'BL-02b', 'BL-02c'];
const [SURFACE, MODEL, EFFORT] = process.argv.slice(2);
const NOASK = process.argv.includes('noask');
if (!SURFACE || !MODEL || !EFFORT) { console.error('usage: bench-lane.js <surface> <model> <effort> [noask]'); process.exit(2); }

for (const id of PROMPTS) {
  const args = [path.join(__dirname, 'generate.js'), SURFACE, MODEL, EFFORT, id, '10'];
  if (NOASK) args.push('noask');
  const r = spawnSync(process.execPath, args, { stdio: 'inherit', timeout: 6 * 60 * 60 * 1000 });
  if (r.status !== 0) { console.error(`LANE STOPPED at ${id} (exit ${r.status})`); process.exit(r.status || 1); }
}
console.log(`BENCH LANE DONE ${MODEL}/${EFFORT}${NOASK ? ' noask' : ''}`);
