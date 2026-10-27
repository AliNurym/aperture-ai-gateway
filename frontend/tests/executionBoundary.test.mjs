import test from 'node:test';
import assert from 'node:assert/strict';
import { executionBoundaryLabel } from '../src/utils/executionBoundary.js';

test('execution boundary copy distinguishes host, container and unverified model routes', () => {
  assert.equal(executionBoundaryLabel('trusted_local'), 'Runs on the host; no container isolation');
  assert.equal(executionBoundaryLabel('docker'), 'Worker reports a Docker task container');
  assert.equal(executionBoundaryLabel('inference_proxy'), 'Configured provider; serving hardware is unverified');
  assert.equal(executionBoundaryLabel('unknown'), 'Not reported');
});
