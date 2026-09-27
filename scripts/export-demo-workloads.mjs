import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { WORKLOADS } from '../frontend/src/utils/workloads.js';

const directory = new URL('../.aperture/demo/approved/', import.meta.url);
await mkdir(directory, { recursive: true });
for (const sample of WORKLOADS.filter(item => item.id !== 'policy')) {
  await writeFile(new URL(sample.id + '.py', directory), sample.code, 'utf8');
}
console.log('Exported the three Studio examples to ' + fileURLToPath(directory));
console.log('Review these files before starting a trusted local worker. Restart it after reviewing source changes.');
