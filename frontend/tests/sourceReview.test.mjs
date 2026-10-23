import assert from 'node:assert/strict';
import test from 'node:test';
import { computeJobManifest, matchingSourceReview } from '../src/utils/sourceReview.js';
import { sha256Hex } from '../src/utils/protocol.js';

const source = 'print(42)';
const review = { source, owner: 'owner', gatewayPubkey: 'gateway', taskId: 'task-' + 'a'.repeat(32),
  receiptSha256: 'b'.repeat(64), report: { security: 'REVIEW' } };
const options = { source, owner: 'owner', gatewayPubkey: 'gateway', inputs: [], parametersText: '{}', dataJob: false, review };

test('the exact Gemini review becomes a hash-bound parameter of the compute manifest', async () => {
  const job = await computeJobManifest(options);
  assert.deepEqual(job.parameters.aperture_review, { task_id: review.taskId,
    source_sha256: await sha256Hex(source), receipt_sha256: review.receiptSha256 });
  assert.equal(job.runtime, 'python');
  assert.equal(job.source_sha256, job.parameters.aperture_review.source_sha256);
});

test('source, owner, gateway and incomplete reports cannot silently carry an earlier review', async () => {
  for (const changed of [{ source: 'print(43)' }, { owner: 'other' }, { gatewayPubkey: 'other' },
    { review: { ...review, report: null } }, { review: { ...review, receiptSha256: 'invalid' } }]) {
    assert.equal(await computeJobManifest({ ...options, ...changed }), null);
  }
  assert.equal(matchingSourceReview(null, source, 'owner', 'gateway'), false);
});

test('attaching a review preserves explicit data parameters and refuses conflicting metadata', async () => {
  const job = await computeJobManifest({ ...options, dataJob: true, parametersText: '{"output_name":"report.json"}' });
  assert.equal(job.parameters.output_name, 'report.json');
  await assert.rejects(computeJobManifest({ ...options, dataJob: true, parametersText: '{"aperture_review":{}}' }), /conflicting/);
});
