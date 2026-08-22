'use strict';
// H1-H4 confirmatory cells (HYPOTHESES.md SS A): frozen prompts, clean-room
// lanes, n=30. Usage: node h-cells.js <surface> <model> <effort> <prompt-id> [noask]
// Thin wrapper: reuses generate.js with n=30 into batches/hcells/.
const { spawnSync } = require('child_process');
const path = require('path');
const args = process.argv.slice(2);
const r = spawnSync(process.execPath, [path.join(__dirname, 'generate.js'), args[0], args[1], args[2], args[3], '30', ...(args.includes('noask') ? ['noask'] : [])], { stdio: 'inherit', timeout: 6 * 60 * 60 * 1000 });
process.exit(r.status || 0);
