import { canonicalJson, sha256Hex } from './protocol.js';
import { jobManifest } from './jobs.js';

export function matchingSourceReview(review, source, owner, gatewayPubkey) {
  return Boolean(review && review.source === source && owner && review.owner === owner
    && gatewayPubkey && review.gatewayPubkey === gatewayPubkey && review.report
    && /^task-[0-9a-f]{32}$/.test(review.taskId)
    && /^[0-9a-f]{64}$/.test(review.receiptSha256));
}

export async function computeJobManifest({ source, inputs, parametersText, dataJob, review, owner, gatewayPubkey }) {
  const linked = matchingSourceReview(review, source, owner, gatewayPubkey);
  if (!dataJob && !linked) return null;
  const parameters = dataJob ? JSON.parse(parametersText) : {};
  if (!parameters || typeof parameters !== 'object' || Array.isArray(parameters)) throw new Error('Parameters must be a JSON object.');
  if (linked) {
    const reference = { task_id: review.taskId, source_sha256: await sha256Hex(source), receipt_sha256: review.receiptSha256 };
    if (Object.hasOwn(parameters, 'aperture_review') && canonicalJson(parameters.aperture_review) !== canonicalJson(reference)) {
      throw new Error('Remove the conflicting aperture_review parameter before attaching the verified source review.');
    }
    parameters.aperture_review = reference;
  }
  return jobManifest(source, dataJob ? inputs : [], JSON.stringify(parameters));
}
