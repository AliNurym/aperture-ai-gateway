import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import process from 'node:process';

// Keep Vite, Rollup and esbuild on the same path if Windows opened the project
// through a directory junction.
process.chdir(realpathSync(fileURLToPath(new URL('../', import.meta.url))));
await import('../node_modules/vite/bin/vite.js');
