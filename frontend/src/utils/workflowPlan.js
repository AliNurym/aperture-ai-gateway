import { validateObject } from './jobs';
import { WORKLOADS } from './workloads';

import { MERGE_SOURCE } from './workflowSources';

export function parseStepCost(value) {
  const match = /^(\d+)(?:\.(\d{1,9}))?$/.exec(String(value).trim());
  if (!match) throw new Error('Enter a cost in SOL with up to nine decimal places.');
  const amount = BigInt(match[1]) * 1_000_000_000n + BigInt((match[2] || '').padEnd(9, '0'));
  if (amount < 1n || amount > 1_000_000_000n) throw new Error('Each step needs a cost cap between 0.000000001 and 1 SOL.');
  return Number(amount);
}

export function createBatchPlan(inputs, cost, runtime) {
  if (!Array.isArray(inputs) || inputs.length < 1 || inputs.length > 200) throw new Error('Provide 1–200 uploaded CSV batch references.');
  inputs.forEach(item => validateObject(item));
  if (new Set(inputs.map(item => item.object_id)).size !== inputs.length) throw new Error('A batch appears more than once.');
  if (!Number.isSafeInteger(cost) || cost < 1 || cost > 1_000_000_000 || !Number.isSafeInteger(runtime) || runtime < 1 || runtime > 180) throw new Error('Each step needs a positive cap up to 1 SOL and 1–180 seconds.');
  const steps = inputs.map((item, index) => ({
    id: 'batch_' + index, source: WORKLOADS.find(item => item.id === 'dataset').code,
    inputs: [item], parameters: { input_name: item.name, output_name: 'batch-' + index + '.json', csv_output: false },
    max_cost_lamports: cost, max_runtime_seconds: runtime,
  }));
  let references = steps.map(step => ({ from_step: step.id, artifact: step.parameters.output_name }));
  let level = 0;
  while (references.length > 16) {
    const next = [];
    for (let offset = 0; offset < references.length; offset += 16) {
      const group = references.slice(offset, offset + 16);
      const id = 'merge_' + level + '_' + offset / 16;
      const output = id + '.json';
      steps.push({ id, source: MERGE_SOURCE, inputs: group, parameters: { input_names: group.map(item => item.artifact), output_name: output, final: false }, max_cost_lamports: cost, max_runtime_seconds: runtime });
      next.push({ from_step: id, artifact: output });
    }
    references = next;
    level += 1;
  }
  steps.push({ id: 'report', source: MERGE_SOURCE, inputs: references,
    parameters: { input_names: references.map(item => item.artifact), output_name: 'report.json', final: true },
    max_cost_lamports: cost, max_runtime_seconds: runtime });
  const maximum = steps.length * cost;
  if (maximum > 100_000_000_000) throw new Error('The total workflow cap cannot exceed 100 SOL. Lower the per-step cap.');
  return { version: 1, max_cost_lamports: maximum, steps };
}
