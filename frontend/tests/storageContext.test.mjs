import assert from 'node:assert/strict';
import test from 'node:test';
import { APERTURE_PROGRAM_ID } from '../src/utils/protocol.js';
import { storageContext } from '../src/utils/storage.js';
import { storageContextErrorMessage } from '../src/utils/storageContextMessage.js';

test('off-chain storage binds to the current gateway instead of a stale Devnet pin', () => {
  const owner = '11111111111111111111111111111111';
  const context = storageContext('http://127.0.0.1:61344', {
    demo_mode: true, gateway_pubkey: owner, program_id: APERTURE_PROGRAM_ID,
  }, 'configured-devnet-gateway');
  assert.equal(context.network, 'off_chain');
  assert.equal(context.gateway_pubkey, owner);
});

test('Devnet storage rejects mismatched or missing deployment pins', () => {
  const health = { demo_mode: false, gateway_pubkey: '11111111111111111111111111111111', program_id: APERTURE_PROGRAM_ID };
  assert.throws(() => storageContext('https://gateway.example', health, 'configured-devnet-gateway'), /signer differs/);
  assert.throws(() => storageContext('https://gateway.example', health, ''), /Configure the gateway signing key/);
});

test('a Devnet signer mismatch requires checking the expected signer', () => {
  const message = storageContextErrorMessage(new Error('The gateway signer differs from this console deployment.'), false);
  assert.match(message, /intended Devnet gateway and signer/);
  assert.match(message, /CSV uploads are blocked/);
});

test('other storage context errors keep their original message', () => {
  assert.equal(storageContextErrorMessage('The gateway program differs from this console deployment.', true), 'The gateway program differs from this console deployment.');
});
