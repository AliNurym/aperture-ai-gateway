import sentinelInstructions from '../../../backend/workloads/sentinel_review.json' with { type: 'json' };
import { APERTURE_PROGRAM_ID, GATEWAY_PUBKEY_PIN, TREASURY_PUBKEY_PIN, canonicalJson, canonicalQuoteMessage, sha256Hex, verifyWorkerTarget } from './protocol.js';

export function isLocalGatewayUrl(value) {
  try {
    return ['localhost', '127.0.0.1', '[::1]'].includes(new URL(value).hostname.toLowerCase());
  } catch {
    return false;
  }
}

export function publicOffer(provider) {
  return Object.fromEntries(Object.entries(provider).filter(([key]) =>
    !['available_workers', 'lowest_worker_rate_lamports_sec', 'rate_lamports_sec'].includes(key)));
}

export function isLocalDevelopmentModel(provider) {
  return provider?.development_only === true
    || ['local-model', 'aperture-local-fixture'].includes(provider?.id)
    || /smollm/i.test(provider?.model || '');
}

export function publicInferenceProviders(providers) {
  return Array.isArray(providers) ? providers.filter(provider =>
    !isLocalDevelopmentModel(provider) && provider?.id !== 'aperture-deepseek') : [];
}

export function isSentinelProvider(provider) {
  return ['gemini_generate_content', 'openai_chat_completions'].includes(provider?.protocol);
}

export function sentinelProviders(providers) {
  return Array.isArray(providers) ? providers.filter(provider =>
    !isLocalDevelopmentModel(provider) && isSentinelProvider(provider)) : [];
}

export function activeModelWorkerCount(nodes, providers) {
  const offerIds = new Set(publicInferenceProviders(providers).map(provider => provider.id));
  if (!Array.isArray(nodes) || !offerIds.size) return 0;
  const workers = nodes.filter(node => Array.isArray(node?.inference_offers)
      && node.inference_offers.some(offer => offerIds.has(offer?.id)))
    .map(node => node.node_id || node.worker_pubkey)
    .filter(Boolean);
  return new Set(workers).size;
}

export function hasMatchingInferenceWorker(provider) {
  return Number.isSafeInteger(provider?.available_workers) && provider.available_workers > 0;
}

export function matchingInferenceWorkers(nodes, provider, now = Date.now() / 1000, { includeStale = false } = {}) {
  if (!Array.isArray(nodes) || !provider) return [];
  const offer = canonicalJson(publicOffer(provider));
  const seen = new Set();
  return nodes.filter(node => {
    const heartbeatFresh = Number.isFinite(node?.last_seen) && now - node.last_seen < 45;
    if (!node?.node_id || !node.worker_pubkey
        || (node.online === false && (!includeStale || heartbeatFresh))
        || node.accepting_tasks === false
        || !Number.isSafeInteger(node.rate_lamports_sec) || node.rate_lamports_sec < 1 || node.rate_lamports_sec > 1_000_000_000
        || (!includeStale && !heartbeatFresh)
        || !Array.isArray(node.runtimes) || !node.runtimes.includes('inference.chat')
        || !Array.isArray(node.inference_offers)
        || !node.inference_offers.some(item => canonicalJson(publicOffer(item)) === offer)) return false;
    const key = node.node_id + ':' + node.worker_pubkey;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function inferenceText(raw) {
  const text = raw.replace(/\r\n/g, '\n');
  const marker = '\n\n[Aperture inference metadata]\n';
  const index = text.lastIndexOf(marker);
  return index < 0 ? text : text.slice(0, index);
}

const SENTINEL_PROMPT_MAX_CHARS = 16000;

export function buildSentinelPrompt(source) {
  if (typeof source !== 'string' || !source.trim()) throw new Error('Add Python source before requesting an AI Sentinel review.');
  if (new TextEncoder().encode(source).length > 32000) throw new Error('AI Sentinel review accepts up to 32 KB of source, matching the gateway source limit.');
  const prompt = sentinelInstructions.prefix + JSON.stringify(source);
  if (prompt.length > SENTINEL_PROMPT_MAX_CHARS) throw new Error('This source is too long to fit the signed AI Sentinel request. Shorten it or review a smaller section.');
  return prompt;
}

export function parseSentinelReport(raw, source) {
  if (typeof source !== 'string' || !source.trim()) return null;
  try {
    const report = JSON.parse(inferenceText(raw).trim());
    if (!report || typeof report !== 'object' || Array.isArray(report)) return null;
    let security = String(report.security || '').toUpperCase();
    if (!['SAFE', 'DANGEROUS', 'REVIEW'].includes(security)) return null;
    if (typeof report.reason !== 'string' || !Array.isArray(report.findings) || report.findings.length > 20) return null;
    const sourceLineCount = source.split(/\r\n|\n|\r/).length;
    const findings = report.findings.map(item => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error('Invalid finding');
      const severity = ['critical', 'high', 'medium', 'low', 'info'].includes(String(item.severity || '').toLowerCase())
        ? String(item.severity).toLowerCase() : null;
      if (!severity || !Number.isSafeInteger(item.line) || item.line < 1 || item.line > sourceLineCount
          || typeof item.issue !== 'string' || !item.issue.trim() || typeof item.evidence !== 'string') {
        throw new Error('Invalid finding');
      }
      return { severity, line: item.line, issue: item.issue.slice(0, 500), evidence: item.evidence.slice(0, 1000) };
    });
    if (security === 'SAFE' && findings.some(item => item.severity !== 'info')) security = 'REVIEW';
    return { security, reason: typeof report.reason === 'string' ? report.reason.slice(0, 2000) : '', findings };
  } catch { return null; }
}

export function sentinelManualReviewMessage(executionStatus, report) {
  if (report) return '';
  if (executionStatus !== 'completed') {
    return 'The model task failed or stopped before producing a complete review. No Sentinel verdict was accepted. Check the recorded output; another review runs only after you start it manually.';
  }
  return 'The model task completed, but its output is not a valid report for this source. No Sentinel verdict was accepted; review the output manually before deciding what to do.';
}

export async function inferenceSource(parameters) {
  return '# Aperture inference request v1\n# sha256:' + await sha256Hex(canonicalJson(parameters)) + '\npass\n';
}

export async function verifyInferenceQuote(quote, { wallet, provider, messages, maxTokens, budget, runtime, health, workerTarget = null, workers = [] }) {
  verifyWorkerTarget(quote, workerTarget);
  const parameters = { inference: { provider_id: provider.id, messages, max_tokens: maxTokens }, offer: publicOffer(provider) };
  const code = await inferenceSource(parameters);
  const manifest = { version: 1, runtime: 'inference.chat', source_sha256: await sha256Hex(code), inputs: [], parameters };
  const expectedNetwork = health.demo_mode ? 'off_chain' : 'devnet';
  const routedWorker = matchingInferenceWorkers(workers, provider).find(node =>
    node.node_id === quote.worker_target?.node_id && node.worker_pubkey === quote.worker_target?.worker_pubkey);
  if (!routedWorker || routedWorker.rate_lamports_sec !== quote.rate_lamports
      || quote.wallet !== wallet || quote.agent_pubkey !== wallet || quote.network !== expectedNetwork
      || quote.program_id !== APERTURE_PROGRAM_ID || quote.gateway_pubkey !== health.gateway_pubkey
      || quote.code_sha256 !== manifest.source_sha256 || quote.max_cost_lamports !== budget
      || !Number.isSafeInteger(quote.passport_version) || quote.passport_version !== 0
      || quote.max_runtime_seconds !== runtime
      || !Number.isSafeInteger(quote.rate_lamports) || quote.rate_lamports < 1 || budget < quote.rate_lamports
      || quote.effective_runtime_seconds !== Math.min(runtime, Math.floor(budget / quote.rate_lamports))
      || !Number.isSafeInteger(quote.expires_at) || quote.expires_at * 1000 <= Date.now()
      || quote.expires_at * 1000 > Date.now() + 120000
      || canonicalJson(quote.workload) !== canonicalJson(manifest)
      || quote.workload_sha256 !== await sha256Hex(canonicalJson(manifest))
      || quote.workload_canonical !== canonicalJson(manifest)
      || canonicalJson(quote.execution_request) !== canonicalJson({ code, job_version: 1, inputs: [], parameters })
      || quote.message !== canonicalQuoteMessage(quote)) throw new Error('The inference quote differs from your selected provider, prompt or limits.');
  if (expectedNetwork === 'off_chain' && quote.treasury !== null) throw new Error('The off-chain quote unexpectedly names a treasury.');
  if (expectedNetwork === 'devnet' && (quote.gateway_pubkey !== GATEWAY_PUBKEY_PIN || quote.treasury !== TREASURY_PUBKEY_PIN)) {
    throw new Error('Configure matching gateway and treasury pins before signing a Devnet inference task.');
  }
  return quote;
}
