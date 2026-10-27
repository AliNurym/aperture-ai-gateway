import { APERTURE_PROGRAM_ID, GATEWAY_PUBKEY_PIN, QUOTE_MESSAGE_KEYS, canonicalJson, canonicalQuoteMessage, sha256Hex, verifyGatewayReceipt, verifyDevnetSettlement } from './protocol.js';
import { jobManifest } from './jobs.js';
import { buildSentinelPrompt, inferenceSource, isSentinelProvider, parseSentinelReport } from './inference.js';

const reviewKey = apiUrl => 'aperture-source-review-v1:' + apiUrl.replace(/\/$/, '');
const sourceKey = apiUrl => 'aperture-studio-source-v1:' + apiUrl.replace(/\/$/, '');
const validSource = source => typeof source === 'string' && new TextEncoder().encode(source).length <= 32000;

export function sourceReviewBundle(review) {
  if (!validSource(review?.source) || !review.evidence) throw new Error('A signed review is required before export.');
  const { quote, receipt, output } = review.evidence;
  const publicQuote = Object.fromEntries([...QUOTE_MESSAGE_KEYS, 'effective_runtime_seconds', 'workload', 'workload_sha256',
    'workload_canonical', 'worker_target', 'workflow', 'message'].filter(key => Object.hasOwn(quote, key)).map(key => [key, quote[key]]));
  // Export signed public evidence only, never the task capability or wallet key.
  const bundle = { version: 1, source: review.source, evidence: { quote: publicQuote, receipt, output } };
  if (new TextEncoder().encode(JSON.stringify(bundle)).length > 2_000_000) throw new Error('This review exceeds the 2 MB export limit.');
  return bundle;
}

export function sourceLineRange(source, line) {
  if (typeof source !== 'string' || !Number.isSafeInteger(line) || line < 1) return null;
  let start = 0;
  for (let index = 1; index < line; index += 1) {
    const newline = source.indexOf('\n', start);
    if (newline < 0) return null;
    start = newline + 1;
  }
  let end = source.indexOf('\n', start);
  if (end < 0) end = source.length;
  if (source[end - 1] === '\r') end -= 1;
  return { start, end };
}

export function readStudioSource(apiUrl, storage) {
  try {
    const record = JSON.parse((storage ?? globalThis.sessionStorage).getItem(sourceKey(apiUrl)));
    return record?.version === 1 && validSource(record.source) ? record.source : null;
  } catch { return null; }
}

export function saveStudioSource(apiUrl, source, storage) {
  try {
    if (!validSource(source)) return false;
    (storage ?? globalThis.sessionStorage).setItem(sourceKey(apiUrl), JSON.stringify({ version: 1, source }));
    return true;
  } catch { return false; }
}

export function readSourceReview(apiUrl, storage) {
  try {
    const raw = (storage ?? globalThis.sessionStorage).getItem(reviewKey(apiUrl));
    if (!raw || raw.length > 2_000_000) return null;
    const record = JSON.parse(raw);
    return record?.version === 1 && validSource(record.source) && record.evidence ? record : null;
  } catch { return null; }
}

export function saveSourceReview(apiUrl, review, storage) {
  try {
    if (!validSource(review?.source) || !review.evidence) return false;
    // Save signed evidence, not a trusted verdict, task token or wallet key.
    const raw = JSON.stringify(sourceReviewBundle(review));
    if (raw.length > 2_000_000) return false;
    (storage ?? globalThis.sessionStorage).setItem(reviewKey(apiUrl), raw);
    return true;
  } catch { return false; }
}

export async function recoverSourceReview(record, health, connection, signerPin = GATEWAY_PUBKEY_PIN) {
  const evidence = record?.evidence;
  const { quote, receipt, output } = evidence || {};
  const workload = quote?.workload;
  if (record?.version !== 1 || !validSource(record.source) || typeof output !== 'string'
      || new TextEncoder().encode(output).length > 1_000_000 || !/^task-[0-9a-f]{32}$/.test(receipt?.task_id)
      || receipt.execution_status !== 'completed' || workload?.runtime !== 'inference.chat'
      || !isSentinelProvider(workload.parameters?.offer)
      || quote.program_id !== APERTURE_PROGRAM_ID || quote.program_id !== health?.program_id
      || quote.gateway_pubkey !== health?.gateway_pubkey
      || health?.demo_mode !== true && signerPin && quote.gateway_pubkey !== signerPin
      || typeof health?.demo_mode !== 'boolean' || quote.network !== (health.demo_mode ? 'off_chain' : 'devnet')) {
    throw new Error('Saved source review does not match this gateway and completed model task.');
  }
  const messages = workload.parameters.inference?.messages;
  const sourceHash = await sha256Hex(await inferenceSource(workload.parameters));
  if (!Array.isArray(messages) || messages.length !== 1 || messages[0].role !== 'user'
      || messages[0].content !== buildSentinelPrompt(record.source)
      || workload.source_sha256 !== sourceHash || quote.code_sha256 !== sourceHash
      || canonicalJson(workload) !== quote.workload_canonical
      || await sha256Hex(canonicalJson(workload)) !== quote.workload_sha256
      || quote.message !== canonicalQuoteMessage(quote)) {
    throw new Error('Saved review source or manifest differs from its signed task.');
  }
  const verified = await verifyGatewayReceipt(receipt, quote, receipt.task_id, output);
  if (!verified.verified) throw new Error(verified.reason);
  if (receipt.settlement_type === 'DEVNET') {
    const settled = await verifyDevnetSettlement(connection, receipt, quote, receipt.task_id);
    if (!settled.verified) throw new Error(settled.reason);
  }
  return { source: record.source, report: parseSentinelReport(output, record.source), taskId: receipt.task_id,
    owner: quote.wallet, gatewayPubkey: quote.gateway_pubkey, receiptSha256: receipt.receipt_sha256, evidence };
}

export function sourceReviewStatus(review, source, owner, gatewayPubkey) {
  if (review.source !== source) return 'Source changed since review';
  if (!owner) return 'Reconnect the reviewing wallet';
  if (review.owner !== owner) return 'Different signing identity';
  if (review.gatewayPubkey !== gatewayPubkey) return 'Different gateway';
  return review.report ? 'Matches current source' : 'Manual review required';
}

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
