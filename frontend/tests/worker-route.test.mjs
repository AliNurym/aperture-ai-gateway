import assert from 'node:assert/strict';
import test from 'node:test';
import { generateKeyPairSync, sign } from 'node:crypto';
import { PublicKey } from '@solana/web3.js';
import { canonicalJson, canonicalQuoteMessage, sha256Hex, verifyGatewayReceipt, verifyWorkerTarget } from '../src/utils/protocol.js';

function signingKey() {
  const key = generateKeyPairSync('ed25519');
  return { publicKey: new PublicKey(key.publicKey.export({ type: 'spki', format: 'der' }).subarray(-32)).toBase58(),
    sign: message => sign(null, Buffer.from(message), key.privateKey) };
}
function base58(bytes) {
  const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  let number = BigInt('0x' + bytes.toString('hex'));
  let encoded = '';
  while (number) { encoded = alphabet[Number(number % 58n)] + encoded; number /= 58n; }
  for (const byte of bytes) { if (byte) break; encoded = '1' + encoded; }
  return encoded;
}

async function fixture() {
  const gateway = signingKey(), worker = signingKey();
  const wallet = '11111111111111111111111111111111';
  const quote = { quote_id: 'quote-worker-12345678', wallet, agent_pubkey: wallet, code_sha256: await sha256Hex('print(42)'),
    rate_lamports: 1000, max_cost_lamports: 10000, max_runtime_seconds: 10, effective_runtime_seconds: 10,
    expires_at: Math.floor(Date.now() / 1000) + 90, passport_version: 0, program_id: wallet,
    network: 'off_chain', gateway_pubkey: gateway.publicKey, treasury: null,
    worker_target: { node_id: 'chosen-worker', worker_pubkey: worker.publicKey } };
  quote.message = canonicalQuoteMessage(quote);
  const taskId = 'task-worker-route', fullLog = '42\n';
  const workerReceipt = { domain: 'aperture.worker.result.v1', task_id: taskId, lease_id: 'lease-test',
    source_hash: quote.code_sha256, output_hash: await sha256Hex(fullLog), quote_id: quote.quote_id,
    agent_pubkey: wallet, worker_id: 'chosen-worker', worker_pubkey: worker.publicKey,
    exit_code: 0, execution_mode: 'docker', execution_time_ms: 100 };
  const evidence = { receipt_version: 1, task_id: taskId, task_hash: await sha256Hex(taskId), quote_id: quote.quote_id,
    owner_wallet: wallet, agent_pubkey: wallet, passport_version: 0, code_sha256: quote.code_sha256,
    output_sha256: await sha256Hex(fullLog), rate_lamports: 1000, max_cost_lamports: 10000,
    max_runtime_seconds: 10, worker_id: 'chosen-worker', worker_pubkey: worker.publicKey,
    worker_target: quote.worker_target, lease_id: 'lease-test', execution_status: 'completed', exit_code: 0,
    execution_time: .1, execution_backend: 'docker', charged_lamports: null, settlement_type: 'OFF_CHAIN',
    worker_receipt: workerReceipt, worker_signature: base58(worker.sign(canonicalJson(workerReceipt))) };
  const receipt = async change => {
    const updated = { ...evidence, ...change };
    const message = 'Aperture compute receipt v1\n' + canonicalJson(updated);
    return { ...updated, gateway_pubkey: gateway.publicKey, signed_message: message,
      receipt_sha256: await sha256Hex(message), gateway_signature: [...gateway.sign(message)] };
  };
  return { quote, taskId, fullLog, receipt };
}

test('worker route is bound to authorization v5 and cannot be silently replaced', async () => {
  const { quote } = await fixture();
  assert.ok(quote.message.startsWith('Aperture execution authorization v5\n'));
  assert.deepEqual(JSON.parse(quote.message.split('\n').at(-1)).worker_target, quote.worker_target);
  verifyWorkerTarget(quote, quote.worker_target);
  assert.throws(() => verifyWorkerTarget(quote, null), /changed the selected worker/);
  assert.throws(() => verifyWorkerTarget(quote, { ...quote.worker_target, node_id: 'other-worker' }), /changed the selected worker/);
  assert.throws(() => canonicalQuoteMessage({ ...quote, worker_target: { ...quote.worker_target, route: 'fallback' } }), /Invalid selected worker/);
  const legacy = { ...quote }; delete legacy.worker_target;
  assert.ok(canonicalQuoteMessage(legacy).startsWith('Aperture execution authorization v2\n'));
});

test('receipt verification accepts the chosen worker and rejects a gateway-signed substituted executor', async () => {
  const { quote, taskId, fullLog, receipt } = await fixture();
  assert.equal((await verifyGatewayReceipt(await receipt(), quote, taskId, fullLog)).verified, true);
  const wrongWorker = await receipt({ worker_id: 'substituted-worker' });
  const rejected = await verifyGatewayReceipt(wrongWorker, quote, taskId, fullLog);
  assert.equal(rejected.verified, false);
  assert.match(rejected.reason, /different worker/);
  const missingRoute = await receipt({ worker_target: null });
  assert.match((await verifyGatewayReceipt(missingRoute, quote, taskId, fullLog)).reason, /selected worker route/);
});
