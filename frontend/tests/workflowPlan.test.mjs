import assert from 'node:assert/strict';
import test from 'node:test';
import { createBatchPlan, parseStepCost } from '../src/utils/workflowPlan.js';
import { validateBrowserPlan, workflowContext } from '../src/utils/browserWorkflows.js';
import { createModelPlan } from '../src/utils/modelWorkflowPlan.js';
import { canBuildMixedWorkflow, mixedWorkflowCapacityNotice, mixedWorkflowWorkerCapacity, workflowPlanNeedsModelOffer, workflowPlanNeedsPythonWorker } from '../src/utils/mixedWorkflowStatus.js';
import { jobManifest } from '../src/utils/jobs.js';
import { APERTURE_PROGRAM_ID } from '../src/utils/protocol.js';

const modelParameters = () => ({ inference: { provider_id: 'fixture', messages: [{ role: 'user', content: 'Объясни бюджет.' }], max_tokens: 64 }, offer: { id: 'fixture', max_output_tokens: 128 } });

test('mixed workflow distinguishes loading, missing capacity, and the Sentinel-only DeepSeek role', () => {
  const loading = mixedWorkflowCapacityNotice({ directoryState: 'loading' });
  assert.equal(loading.state, 'loading');
  assert.equal(loading.action, undefined);
  const unavailable = mixedWorkflowCapacityNotice({ directoryState: 'unavailable' });
  assert.equal(unavailable.state, 'unavailable');
  assert.equal(unavailable.action, undefined);
  const empty = mixedWorkflowCapacityNotice({ directoryState: 'ready' });
  assert.equal(empty.title, 'No general model offer yet');
  assert.equal(empty.action, 'Open model setup');
  assert.match(empty.message, /DeepSeek checks Sentinel source safety only/);
  assert.match(empty.message, /not an inference offer or price source/);
  assert.match(empty.message, /priced Python worker/);
  const modelWorkerMissing = mixedWorkflowCapacityNotice({ directoryState: 'ready', providerCount: 1, modelWorkerCount: 0, pythonWorkerCount: 1 });
  assert.equal(modelWorkerMissing.state, 'worker-missing');
  assert.equal(modelWorkerMissing.action, 'Open capacity setup');
  const staleModelWorker = mixedWorkflowCapacityNotice({ directoryState: 'ready', providerCount: 1, modelWorkerCount: 0, pythonWorkerCount: 1, modelStaleCount: 1 });
  assert.equal(staleModelWorker.state, 'stale');
  assert.equal(staleModelWorker.action, undefined);
  assert.match(staleModelWorker.message, /Refresh capacity before changing the worker setup/);
  const pythonWorkerMissing = mixedWorkflowCapacityNotice({ directoryState: 'ready', providerCount: 1, modelWorkerCount: 1, pythonWorkerCount: 0 });
  assert.equal(pythonWorkerMissing.state, 'python-missing');
  assert.equal(pythonWorkerMissing.action, 'Open capacity setup');
  assert.equal(mixedWorkflowCapacityNotice({ directoryState: 'ready', providerCount: 1, modelWorkerCount: 1, pythonWorkerCount: 1 }), null);
});

test('mixed workflow admits only fresh priced workers within the quote rate limit', () => {
  const now = 1000;
  const worker = (id, runtime, rate, overrides = {}) => ({
    node_id: id, worker_pubkey: '11111111111111111111111111111111', online: true,
    accepting_tasks: true, last_seen: now - 1, runtimes: [runtime], rate_lamports_sec: rate, ...overrides,
  });
  const capacity = mixedWorkflowWorkerCapacity([
    worker('at-cap', 'python', 25000), worker('above-cap', 'python', 25001),
    worker('unpriced', 'python', null), worker('stale', 'python', 1000, { last_seen: now - 46 }),
    worker('other-runtime', 'inference.chat', 1000),
  ], 'python', now);
  assert.deepEqual(capacity.eligible.map(item => item.node_id), ['at-cap']);
  assert.deepEqual(capacity.rateLimited.map(item => item.node_id), ['above-cap']);
  assert.equal(capacity.unpricedCount, 1);
  assert.equal(capacity.staleCount, 1);
  assert.equal(canBuildMixedWorkflow({ directoryState: 'ready', providerCount: 1, modelWorkerCount: 1, pythonWorkerCount: 1 }), true);
  assert.equal(canBuildMixedWorkflow({ directoryState: 'ready', providerCount: 1, modelWorkerCount: 0, pythonWorkerCount: 1 }), false);
});

test('imported Python plans do not require or report model-offer capacity', () => {
  const pythonPlan = { steps: [{ source: 'print(42)' }] };
  const modelPlan = { steps: [{ source: '# Aperture inference request v1\npass\n' }] };
  assert.equal(workflowPlanNeedsModelOffer(pythonPlan), false);
  assert.equal(workflowPlanNeedsPythonWorker(pythonPlan), true);
  assert.equal(workflowPlanNeedsModelOffer(modelPlan), true);
  assert.equal(workflowPlanNeedsPythonWorker(modelPlan), false);
  assert.equal(workflowPlanNeedsModelOffer(null), false);
  const missingPython = mixedWorkflowCapacityNotice({ directoryState: 'ready', needsModel: false, needsPython: true, providerCount: 0, pythonWorkerCount: 0 });
  assert.equal(missingPython.state, 'python-missing');
  assert.equal(mixedWorkflowCapacityNotice({ directoryState: 'ready', needsModel: false, needsPython: false, providerCount: 0, pythonWorkerCount: 0 }), null);
});

test('mixed workflow explains a missing worker price or a rate above the supported limit', () => {
  const unpriced = mixedWorkflowCapacityNotice({ directoryState: 'ready', providerCount: 1, modelWorkerCount: 1, pythonWorkerCount: 0, pythonUnpricedCount: 1 });
  assert.equal(unpriced.state, 'worker-unpriced');
  assert.match(unpriced.message, /budget cannot set that price/);
  const overLimit = mixedWorkflowCapacityNotice({ directoryState: 'ready', providerCount: 1, modelWorkerCount: 0, pythonWorkerCount: 1, modelRateLimitedCount: 1 });
  assert.equal(overLimit.state, 'rate-limited');
  assert.match(overLimit.message, /25,000 lamports per second/);
});

test('off-chain workflows bind to the live signer while Devnet requires matching deployment pins', () => {
  const owner = '11111111111111111111111111111111';
  const health = { program_id: APERTURE_PROGRAM_ID, gateway_pubkey: owner, demo_mode: true };
  const context = workflowContext('http://127.0.0.1:61344', owner, health,
    { gatewayPin: 'configured-devnet-gateway', treasuryPin: 'configured-devnet-treasury' });
  assert.equal(context.gateway_pubkey, owner);
  assert.equal(context.gateway_pin, owner);
  assert.equal(context.treasury_pin, null);
  assert.throws(() => workflowContext('http://127.0.0.1:61344', owner, { ...health, demo_mode: false },
    { gatewayPin: 'configured-devnet-gateway', treasuryPin: 'configured-devnet-treasury' }), /signer differs/);
});

test('mixed plans connect model files, Python results and explicit message dependencies', async () => {
  const target = { node_id: 'fixture-worker', worker_pubkey: '11111111111111111111111111111111' };
  const plan = await createModelPlan(modelParameters(), 100000, 30, { model: target });
  const validated = await validateBrowserPlan(plan);
  assert.equal(validated.max_cost_lamports, 300000);
  assert.deepEqual(validated.steps.map(step => step.depends_on), [[], ['generate'], ['analyze']]);
  assert.deepEqual(validated.steps[2].worker_target, target);
  assert.equal((await jobManifest(plan.steps[0].source, [], JSON.stringify(plan.steps[0].parameters))).runtime, 'inference.chat');
});

test('mixed plans reject a changed inference source, context cycles and excess token limits', async () => {
  let plan = await createModelPlan(modelParameters(), 100000, 30);
  plan.steps[0].source += '# changed';
  await assert.rejects(validateBrowserPlan(plan));
  plan = await createModelPlan(modelParameters(), 100000, 30);
  plan.steps[2].message_inputs[0].from_step = 'interpret';
  await assert.rejects(validateBrowserPlan(plan));
  const parameters = modelParameters(); parameters.inference.max_tokens = 129;
  await assert.rejects(createModelPlan(parameters, 100000, 30));
});

test('model context is explicit, cannot be attached to Python or duplicated', async () => {
  let plan = await createModelPlan(modelParameters(), 100000, 30);
  plan.steps[1].message_inputs = plan.steps[2].message_inputs;
  await assert.rejects(validateBrowserPlan(plan));
  plan = await createModelPlan(modelParameters(), 100000, 30);
  plan.steps[2].message_inputs.push(plan.steps[2].message_inputs[0]);
  await assert.rejects(validateBrowserPlan(plan));
});

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
