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
  return Object.fromEntries(Object.entries(provider).filter(([key]) => key !== 'available_workers'));
}

export function isLocalDevelopmentModel(provider) {
  return provider?.development_only === true
    || ['local-model', 'aperture-local-fixture'].includes(provider?.id)
    || /smollm/i.test(provider?.model || '');
}

export function publicInferenceProviders(providers) {
  return Array.isArray(providers) ? providers.filter(provider => !isLocalDevelopmentModel(provider)) : [];
}

export function sentinelGeminiProviders(providers) {
  return publicInferenceProviders(providers).filter(provider => provider?.protocol === 'gemini_generate_content');
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

export function parseSentinelReport(raw) {
  try {
    const report = JSON.parse(inferenceText(raw).trim());
    if (!report || typeof report !== 'object' || Array.isArray(report)) return null;
    const security = String(report.security || '').toUpperCase();
    if (!['SAFE', 'DANGEROUS', 'REVIEW'].includes(security)) return null;
    const score = value => Number.isInteger(value) && value >= 0 && value <= 100 ? value : null;
    const findings = Array.isArray(report.findings) ? report.findings.slice(0, 20).flatMap(item => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return [];
      const severity = ['critical', 'high', 'medium', 'low', 'info'].includes(String(item.severity || '').toLowerCase())
        ? String(item.severity).toLowerCase() : 'info';
      return [{ severity, line: Number.isSafeInteger(item.line) && item.line > 0 ? item.line : null,
        issue: typeof item.issue === 'string' ? item.issue.slice(0, 500) : 'Unspecified finding',
        evidence: typeof item.evidence === 'string' ? item.evidence.slice(0, 1000) : '' }];
    }) : [];
    return {
      security,
      predicted_sec: Number.isSafeInteger(report.predicted_sec) && report.predicted_sec >= 0 ? report.predicted_sec : null,
      cpu: score(report.cpu), ram: score(report.ram), network: score(report.network),
      reason: typeof report.reason === 'string' ? report.reason.slice(0, 2000) : '', findings,
    };
  } catch { return null; }
}

export async function inferenceSource(parameters) {
  return '# Aperture inference request v1\n# sha256:' + await sha256Hex(canonicalJson(parameters)) + '\npass\n';
}

export async function verifyInferenceQuote(quote, { wallet, provider, messages, maxTokens, budget, runtime, health }) {
  verifyWorkerTarget(quote, null);
  const parameters = { inference: { provider_id: provider.id, messages, max_tokens: maxTokens }, offer: publicOffer(provider) };
  const code = await inferenceSource(parameters);
  const manifest = { version: 1, runtime: 'inference.chat', source_sha256: await sha256Hex(code), inputs: [], parameters };
  const expectedNetwork = health.demo_mode ? 'off_chain' : 'devnet';
  if (quote.wallet !== wallet || quote.agent_pubkey !== wallet || quote.network !== expectedNetwork
      || quote.program_id !== APERTURE_PROGRAM_ID || quote.gateway_pubkey !== health.gateway_pubkey
      || quote.code_sha256 !== manifest.source_sha256 || quote.max_cost_lamports !== budget
      || !Number.isSafeInteger(quote.passport_version) || quote.passport_version !== 0
      || quote.max_runtime_seconds !== runtime || quote.rate_lamports !== provider.rate_lamports_sec
      || !Number.isSafeInteger(quote.rate_lamports) || quote.rate_lamports < 1 || budget < quote.rate_lamports
      || quote.effective_runtime_seconds !== Math.min(runtime, Math.floor(budget / quote.rate_lamports))
      || !Number.isSafeInteger(quote.expires_at) || quote.expires_at * 1000 <= Date.now()
      || quote.expires_at * 1000 > Date.now() + 120000
      || canonicalJson(quote.workload) !== canonicalJson(manifest)
      || quote.workload_sha256 !== await sha256Hex(canonicalJson(manifest))
      || quote.workload_canonical !== canonicalJson(manifest)
      || canonicalJson(quote.execution_request) !== canonicalJson({ code, job_version: 1, inputs: [], parameters })
      || quote.message !== canonicalQuoteMessage(quote)) throw new Error('The inference quote differs from your selected provider, prompt or limits.');
  if (GATEWAY_PUBKEY_PIN && quote.gateway_pubkey !== GATEWAY_PUBKEY_PIN) throw new Error('The quote signer differs from the pinned gateway.');
  if (expectedNetwork === 'off_chain' && quote.treasury !== null) throw new Error('The off-chain quote unexpectedly names a treasury.');
  if (expectedNetwork === 'devnet' && (quote.gateway_pubkey !== GATEWAY_PUBKEY_PIN || quote.treasury !== TREASURY_PUBKEY_PIN)) {
    throw new Error('Configure matching gateway and treasury pins before signing a Devnet inference task.');
  }
  return quote;
}
