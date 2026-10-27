import assert from 'node:assert/strict';
import test from 'node:test';
import { inspectGatewayStatus } from '../src/utils/gatewayStatus.js';

const pins = { programId: 'program-v1', signerPin: 'gateway-v1' };
const health = { status: 'ready', program_id: 'program-v1', gateway_pubkey: 'gateway-v1' };

test('a ready gateway is connected when its program and configured signer match', () => {
  assert.deepEqual(inspectGatewayStatus({ state: 'online', health }, pins), {
    ready: true, issue: null, label: 'Gateway connected', tone: 'ready',
  });
});

test('a signer mismatch is visible even when the gateway reports ready', () => {
  const status = inspectGatewayStatus({ state: 'online', health: { ...health, gateway_pubkey: 'other-gateway' } }, pins);
  assert.equal(status.ready, false);
  assert.equal(status.issue, 'signer_mismatch');
  assert.equal(status.label, 'Gateway signer mismatch');
  assert.equal(status.tone, 'warning');
});

test('an off-chain gateway uses its current identity even when a Devnet signer is pinned', () => {
  const status = inspectGatewayStatus({ state: 'online', health: { ...health, demo_mode: true, gateway_pubkey: 'local-off-chain-gateway' } }, pins);
  assert.equal(status.ready, true);
  assert.equal(status.issue, null);
  assert.equal(status.label, 'Gateway connected');
});

test('a Devnet gateway still rejects a signer that differs from its deployment pin', () => {
  const status = inspectGatewayStatus({ state: 'online', health: { ...health, demo_mode: false, gateway_pubkey: 'other-gateway' } }, pins);
  assert.equal(status.ready, false);
  assert.equal(status.issue, 'signer_mismatch');
});

test('a program mismatch takes precedence over signer mismatch', () => {
  const status = inspectGatewayStatus({ state: 'online', health: { ...health, program_id: 'other-program', gateway_pubkey: 'other-gateway' } }, pins);
  assert.equal(status.issue, 'program_mismatch');
  assert.equal(status.label, 'Gateway program mismatch');
  assert.equal(status.tone, 'warning');
});

test('an unpinned off-chain signer does not create a false mismatch', () => {
  const status = inspectGatewayStatus({ state: 'online', health }, { programId: 'program-v1' });
  assert.equal(status.ready, true);
  assert.equal(status.issue, null);
});

test('offline and worker-unavailable labels keep their own states', () => {
  assert.equal(inspectGatewayStatus({ state: 'offline', health }, pins).label, 'Gateway offline');
  assert.equal(inspectGatewayStatus({ state: 'online', health: { ...health, status: 'workers_unavailable' } }, pins).label, 'Waiting for a worker');
});
