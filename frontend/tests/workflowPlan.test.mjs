import assert from 'node:assert/strict';
import test from 'node:test';
import { createBatchPlan, parseStepCost } from '../src/utils/workflowPlan.js';
import { validateBrowserPlan } from '../src/utils/browserWorkflows.js';

const inputs = count => Array.from({ length: count }, (_, index) => ({
  object_id: 'obj-' + index.toString(16).padStart(32, '0'), name: `data-${index}.csv`,
  sha256: 'ab'.repeat(32), size_bytes: 100,
}));

test('decimal step caps convert to exact integer lamports', () => {
  for (const [value, expected] of [['0.000000001', 1], ['0.0001', 100000], [' 0.123456789 ', 123456789], ['1', 1000000000]]) {
    assert.equal(parseStepCost(value), expected);
  }
  for (const value of ['0', '0.0000000001', '-0.1', '1.000000001', '1e-3', '0,01', '']) {
    assert.throws(() => parseStepCost(value));
  }
});

test('one batch creates a source job and a final report with exact total cap', async () => {
  const references = inputs(1);
  const plan = createBatchPlan(references, 100000, 60);
  assert.equal(plan.steps.length, 2);
  assert.equal(plan.max_cost_lamports, 200000);
  assert.deepEqual(plan.steps[0].inputs, references);
  assert.deepEqual(plan.steps[1].inputs, [{ from_step: 'batch_0', artifact: 'batch-0.json' }]);
  assert.equal(plan.steps[1].parameters.final, true);
  const validated = await validateBrowserPlan(plan);
  assert.deepEqual(validated.steps[1].depends_on, ['batch_0']);
});

for (const [count, stepCount] of [[16, 17], [17, 20], [200, 214]]) {
  test(`${count} batches produce a complete dependency plan with ${stepCount} steps`, async () => {
    const plan = createBatchPlan(inputs(count), 100000, 60);
    assert.equal(plan.steps.length, stepCount);
    assert.equal(plan.max_cost_lamports, stepCount * 100000);
    assert.equal(new Set(plan.steps.map(step => step.id)).size, stepCount);
    const used = plan.steps.flatMap(step => step.inputs).filter(input => input.from_step).map(input => input.from_step);
    for (const batch of plan.steps.slice(0, count)) assert.ok(used.includes(batch.id));
    const complete = new Set();
    for (const step of plan.steps) {
      assert.ok(step.inputs.length <= 16);
      for (const input of step.inputs) if (input.from_step) assert.ok(complete.has(input.from_step));
      complete.add(step.id);
    }
    const validated = await validateBrowserPlan(plan);
    assert.equal(validated.steps.at(-1).id, 'report');
    assert.equal(validated.steps.at(-1).parameters.final, true);
  });
}
