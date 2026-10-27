import assert from 'node:assert/strict';
import test from 'node:test';
import { studioProgressStep, studioStepComplete } from '../src/utils/studioProgress.js';

test('Studio rail advances from a matching Sentinel review to price without regressing', () => {
  assert.equal(studioProgressStep({ status: 'idle', sentinelPanelOpen: false }), 0);
  assert.equal(studioProgressStep({ status: 'idle', sentinelPanelOpen: true }), 1);
  assert.equal(studioProgressStep({ status: 'idle', sentinelMatchesSource: true }), 2);
  assert.equal(studioProgressStep({ status: 'idle', sentinelPanelOpen: true, sentinelMatchesSource: true }), 2);
  assert.equal(studioProgressStep({ status: 'reviewing', sentinelPanelOpen: true }), 2);
});

test('Studio rail assigns source staging, worker execution, and receipts to their real phases', () => {
  assert.equal(studioProgressStep({ status: 'uploading' }), 0);
  for (const status of ['reviewing', 'quoted', 'signing', 'submitting', 'uncertain', 'retryable', 'blocked']) {
    assert.equal(studioProgressStep({ status }), 2, `${status} belongs to price review`);
  }
  for (const status of ['queued', 'running', 'settlement_pending', 'stopping']) {
    assert.equal(studioProgressStep({ status }), 3, `${status} belongs to worker execution`);
  }
  for (const status of ['verifying', 'completed', 'unverified']) {
    assert.equal(studioProgressStep({ status }), 4, `${status} belongs to receipt review`);
  }
  assert.equal(studioProgressStep({ status: 'failed', hasReceipt: false }), 2);
  assert.equal(studioProgressStep({ status: 'failed', hasReceipt: true }), 4);
  assert.equal(studioProgressStep({ status: 'blocked', hasReceipt: true }), 4);
  assert.equal(studioProgressStep({ status: 'cancelled', hasReceipt: false }), 3);
  assert.equal(studioProgressStep({ status: 'cancelled', hasReceipt: true }), 4);
  assert.equal(studioProgressStep({ status: 'future-state' }), 0);
});

test('Studio rail shows checks only for completed phases and a matching optional Sentinel review', () => {
  assert.equal(studioStepComplete(0, { progressStep: 4, status: 'completed' }), true);
  assert.equal(studioStepComplete(1, { progressStep: 4, status: 'completed' }), false);
  assert.equal(studioStepComplete(1, { progressStep: 2, sentinelMatchesSource: true }), true);
  assert.equal(studioStepComplete(2, { progressStep: 2, status: 'quoted' }), false);
  assert.equal(studioStepComplete(4, { progressStep: 4, status: 'completed' }), true);
  assert.equal(studioStepComplete(4, { progressStep: 4, status: 'unverified' }), false);
});
