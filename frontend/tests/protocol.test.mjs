import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { PublicKey } from '@solana/web3.js';
import { verifyDevnetSettlement } from '../src/utils/protocol.js';

function sha256(value) {
  return createHash('sha256').update(value).digest();
}

function settlementFixture({ runtimeSeconds = 3 } = {}) {
  const programId = new PublicKey(new Uint8Array(32).fill(9));
  const wallet = new PublicKey(new Uint8Array(32).fill(1));
  const agent = new PublicKey(new Uint8Array(32).fill(2));
  const taskId = 'task-budget-boundary';
  const taskHash = sha256(taskId).toString('hex');
  const sourceHash = 'ab'.repeat(32);
  const startedAt = 1_800_000_000n;
  const data = Buffer.alloc(186);
  sha256('account:TaskReceipt').copy(data, 0, 0, 8);
  wallet.toBuffer().copy(data, 8);
  agent.toBuffer().copy(data, 40);
  Buffer.from(taskHash, 'hex').copy(data, 72);
  Buffer.from(sourceHash, 'hex').copy(data, 104);
  data.writeBigUInt64LE(1_500n, 136);
  data.writeBigUInt64LE(4_500n, 144);
  data.writeBigInt64LE(startedAt, 152);
  data.writeBigInt64LE(startedAt + BigInt(runtimeSeconds), 160);
  data.writeBigInt64LE(startedAt + BigInt(runtimeSeconds), 168);
  data.writeBigUInt64LE(4_500n, 176);
  data[184] = 1;

  const [receiptAddress] = PublicKey.findProgramAddressSync(
    [new TextEncoder().encode('task'), Buffer.from(taskHash, 'hex')], programId,
  );
  const receipt = {
    task_hash: taskHash,
    settlement_type: 'DEVNET',
    settlement_signature: 'confirmed-settlement-signature',
    charged_lamports: 4_500,
  };
  const quote = {
    network: 'devnet',
    program_id: programId.toBase58(),
    wallet: wallet.toBase58(),
    agent_pubkey: agent.toBase58(),
    code_sha256: sourceHash,
    rate_lamports: 1_500,
    max_cost_lamports: 4_500,
    max_runtime_seconds: 10,
    effective_runtime_seconds: 3,
  };
  const connection = {
    getAccountInfo: async () => ({ owner: programId, data }),
    getSignatureStatuses: async () => ({ value: [{ err: null, confirmationStatus: 'confirmed' }] }),
    getSignaturesForAddress: async () => [{ signature: receipt.settlement_signature, err: null }],
  };
  return { connection, programId, quote, receipt, receiptAddress, taskId };
}

test('accepts a confirmed on-chain deadline within the signed runtime budget', async () => {
  const fixture = settlementFixture();
  const result = await verifyDevnetSettlement(
    fixture.connection, fixture.receipt, fixture.quote, fixture.taskId,
  );
  assert.equal(result.verified, true);
  assert.equal(result.chainReceipt, fixture.receiptAddress.toBase58());
});

test('rejects an on-chain deadline longer than the signed runtime budget', async () => {
  const fixture = settlementFixture({ runtimeSeconds: 4 });
  await assert.rejects(
    verifyDevnetSettlement(fixture.connection, fixture.receipt, fixture.quote, fixture.taskId),
    /on-chain task runtime exceeds the approved quote limit/i,
  );
});
