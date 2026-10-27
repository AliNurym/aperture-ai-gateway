import assert from 'node:assert/strict';
import test from 'node:test';
import { workerActionState } from '../src/utils/workerAction.js';

test('offline workers cannot be selected even when their last published rate is valid', () => {
  assert.deepEqual(workerActionState({ online: false, rate_lamports_sec: 1000 }), { label: 'Offline', disabled: true });
  assert.deepEqual(workerActionState({ status: 'offline', rate_lamports_sec: 1000 }), { label: 'Offline', disabled: true });
});

test('draining and unpriced workers stay unavailable; a priced online worker remains selectable', () => {
  assert.deepEqual(workerActionState({ online: true, accepting_tasks: false, rate_lamports_sec: 1000 }), { label: 'Draining', disabled: true });
  assert.deepEqual(workerActionState({ online: true, rate_lamports_sec: null }), { label: 'Price not set', disabled: true });
  assert.deepEqual(workerActionState({ online: true, rate_lamports_sec: 1000 }), { label: 'Use this worker', disabled: false });
});

test('catalog admission respects the worker-rate bounds and pending workspace state', () => {
  for (const rate of [0, -1, 1_000_000_001, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(workerActionState({ online: true, rate_lamports_sec: rate }).disabled, true);
  }
  assert.deepEqual(workerActionState({ online: true, rate_lamports_sec: 1000 }, true), { label: 'Use this worker', disabled: true });
});
