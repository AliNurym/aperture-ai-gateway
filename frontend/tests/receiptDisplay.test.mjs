import assert from 'node:assert/strict';
import test from 'node:test';
import { receiptPaymentField } from '../src/utils/receiptDisplay.js';

test('off-chain receipt states that no on-chain payment occurred', () => {
  assert.deepEqual(receiptPaymentField({ settlement_type: 'OFF_CHAIN', charged_lamports: null }),
    ['Payment status', 'No on-chain payment']);
});

test('settled receipt displays its actual lamport charge', () => {
  assert.deepEqual(receiptPaymentField({ settlement_type: 'DEVNET', charged_lamports: 1200 }),
    ['Actual charge', '1,200 lamports']);
});

test('missing Devnet charge remains visibly unavailable', () => {
  assert.deepEqual(receiptPaymentField({ settlement_type: 'DEVNET', charged_lamports: null }),
    ['Actual charge', 'Unavailable']);
});
