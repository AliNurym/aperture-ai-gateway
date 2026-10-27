import assert from 'node:assert/strict';
import test from 'node:test';
import { generateKeyPairSync, sign } from 'node:crypto';
import { PublicKey } from '@solana/web3.js';
import { APERTURE_PROGRAM_ID, canonicalJson, canonicalQuoteMessage, sha256Hex } from '../src/utils/protocol.js';
import { buildSentinelPrompt, inferenceSource } from '../src/utils/inference.js';
import { readSourceReview, readStudioSource, recoverSourceReview, saveSourceReview, saveStudioSource, sourceReviewStatus, sourceReviewBundle, sourceLineRange } from '../src/utils/sourceReview.js';

function key() {
  const pair = generateKeyPairSync('ed25519');
  return { publicKey: new PublicKey(pair.publicKey.export({ type: 'spki', format: 'der' }).subarray(-32)).toBase58(),
    sign: message => sign(null, Buffer.from(message), pair.privateKey) };
}
function base58(bytes) {
  const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  let number = BigInt('0x' + bytes.toString('hex')), encoded = '';
  while (number) { encoded = alphabet[Number(number % 58n)] + encoded; number /= 58n; }
  for (const byte of bytes) { if (byte) break; encoded = '1' + encoded; }
  return encoded;
}
async function fixture(protocol = 'gemini_generate_content') {
  const gateway = key(), worker = key(), source = 'print(42)\n';
  const wallet = '11111111111111111111111111111111';
  const taskId = 'task-' + 'a'.repeat(32);
  const output = JSON.stringify({ security: 'SAFE', reason: 'Controlled test advisory', findings: [] });
  const providerId = protocol === 'gemini_generate_content' ? 'gemini' : 'deepseek';
  const parameters = { inference: { provider_id: providerId, messages: [{ role: 'user', content: buildSentinelPrompt(source) }], max_tokens: 128 },
    offer: { id: providerId, protocol, model: 'test-protocol', rate_lamports_sec: 1000 } };
  const codeHash = await sha256Hex(await inferenceSource(parameters));
  const workload = { version: 1, runtime: 'inference.chat', source_sha256: codeHash, inputs: [], parameters };
  const manifestHash = await sha256Hex(canonicalJson(workload));
  const quote = { quote_id: 'quote-source-review-recovery', wallet, agent_pubkey: wallet, passport_version: 0,
    code_sha256: codeHash, workload, workload_canonical: canonicalJson(workload), workload_sha256: manifestHash,
    rate_lamports: 1000, max_cost_lamports: 10000, max_runtime_seconds: 10, effective_runtime_seconds: 10,
    expires_at: Math.floor(Date.now() / 1000) - 3600, program_id: APERTURE_PROGRAM_ID,
    network: 'off_chain', gateway_pubkey: gateway.publicKey, treasury: null };
  quote.message = canonicalQuoteMessage(quote);
  const workerReceipt = { domain: 'aperture.worker.result.v1', task_id: taskId, lease_id: 'review-lease',
    source_hash: codeHash, output_hash: await sha256Hex(output), quote_id: quote.quote_id,
    agent_pubkey: wallet, worker_id: 'review-worker', worker_pubkey: worker.publicKey,
    exit_code: 0, execution_mode: 'inference_proxy', execution_time_ms: 100, workload_sha256: manifestHash, artifacts: [] };
  const fields = { receipt_version: 1, task_id: taskId, task_hash: await sha256Hex(taskId), quote_id: quote.quote_id,
    owner_wallet: wallet, agent_pubkey: wallet, passport_version: 0, code_sha256: codeHash, output_sha256: await sha256Hex(output),
    rate_lamports: 1000, max_cost_lamports: 10000, max_runtime_seconds: 10, worker_id: 'review-worker', worker_pubkey: worker.publicKey,
    lease_id: 'review-lease', execution_status: 'completed', exit_code: 0, execution_time: .1, execution_backend: 'inference_proxy',
    charged_lamports: null, settlement_type: 'OFF_CHAIN', workload_sha256: manifestHash, artifacts: [],
    worker_receipt: workerReceipt, worker_signature: base58(worker.sign(canonicalJson(workerReceipt))) };
  const message = 'Aperture compute receipt v1\n' + canonicalJson(fields);
  const receipt = { ...fields, gateway_pubkey: gateway.publicKey, signed_message: message,
    receipt_sha256: await sha256Hex(message), gateway_signature: [...gateway.sign(message)] };
  return { record: { version: 1, source, evidence: { quote, receipt, output } },
    health: { gateway_pubkey: gateway.publicKey, program_id: APERTURE_PROGRAM_ID, demo_mode: true } };
}

test('reloading a saved review verifies its signed bytes and rebuilds the advisory even after quote expiry', async () => {
  const { record, health } = await fixture();
  record.report = { security: 'DANGEROUS' };
  const restored = await recoverSourceReview(record, health);
  assert.equal(restored.report.security, 'SAFE');
  assert.equal(restored.source, record.source);
  assert.equal(restored.receiptSha256, record.evidence.receipt.receipt_sha256);
  assert.equal(sourceReviewStatus(restored, restored.source, null, health.gateway_pubkey), 'Reconnect the reviewing wallet');
  assert.equal(sourceReviewStatus(restored, restored.source, 'another-wallet', health.gateway_pubkey), 'Different signing identity');
});

test('reloading a signed DeepSeek compatible review keeps its provenance checks', async () => {
  const { record, health } = await fixture('openai_chat_completions');
  const restored = await recoverSourceReview(record, health);
  assert.equal(restored.report.security, 'SAFE');
});

test('off-chain review recovery is bound to the current gateway, not a stale Devnet pin', async () => {
  const { record, health } = await fixture();
  const restored = await recoverSourceReview(record, health, undefined, 'configured-devnet-gateway');
  assert.equal(restored.gatewayPubkey, health.gateway_pubkey);
  await assert.rejects(recoverSourceReview(record, { ...health, demo_mode: false }, undefined, 'configured-devnet-gateway'));
});

test('portable review exports preserve verifiable evidence and omit task capabilities and wallet keys', async () => {
  const { record, health } = await fixture();
  const review = await recoverSourceReview(record, health);
  review.token = 'private-task-capability';
  review.privateKey = 'private-wallet-key';
  review.evidence.quote.task_access_token = 'private-task-capability';
  const bundle = sourceReviewBundle(review);
  const raw = JSON.stringify(bundle);
  assert.ok(!raw.includes('private-task-capability'));
  assert.ok(!raw.includes('private-wallet-key'));
  const imported = await recoverSourceReview(JSON.parse(raw), health);
  assert.equal(imported.source, record.source);
  assert.equal(imported.receiptSha256, review.receiptSha256);
});

test('finding navigation selects the exact UTF-16 source line with Unicode and CRLF', () => {
  const source = '# 😀 Қазақстан\r\nprint(42)\r\n';
  const range = sourceLineRange(source, 2);
  assert.equal(source.slice(range.start, range.end), 'print(42)');
  assert.deepEqual(sourceLineRange(source, 3), { start: source.length, end: source.length });
  for (const line of [0, -1, 2.5, 4, '2', Number.MAX_SAFE_INTEGER + 1]) assert.equal(sourceLineRange(source, line), null);
});

test('review recovery refuses changed source, output, manifest, signature and gateway', async () => {
  const { record, health } = await fixture();
  for (const mutate of [r => { r.source = 'print(43)'; }, r => { r.evidence.output += 'forged'; },
    r => { r.evidence.quote.workload.parameters.inference.messages[0].content += 'changed'; },
    r => { r.evidence.quote.workload.parameters.offer.protocol = 'unsupported'; },
    r => { r.evidence.receipt.gateway_signature[0] ^= 1; }, r => { r.evidence.receipt.execution_status = 'failed'; }]) {
    const changed = structuredClone(record); mutate(changed);
    await assert.rejects(recoverSourceReview(changed, health));
  }
  await assert.rejects(recoverSourceReview(record, { ...health, gateway_pubkey: key().publicKey }));
  await assert.rejects(recoverSourceReview(record, { ...health, demo_mode: false }));
});

test('private tab drafts preserve exact source, isolate gateways and tolerate blocked storage', async () => {
  const values = new Map();
  const storage = { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v) };
  assert.equal(saveStudioSource('http://one/', '', storage), true);
  assert.equal(readStudioSource('http://one', storage), '');
  assert.equal(readStudioSource('http://two', storage), null);
  const { record } = await fixture();
  assert.equal(saveSourceReview('http://one', { ...record, privateKey: 'must-not-persist' }, storage), true);
  assert.deepEqual(readSourceReview('http://one', storage), record);
  assert.equal(readSourceReview('http://two', storage), null);
  assert.ok([...values.values()].every(value => !value.includes('must-not-persist')));
  const blocked = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  assert.equal(readSourceReview('http://one', blocked), null);
  assert.equal(saveStudioSource('http://one', 'print(42)', blocked), false);
});
