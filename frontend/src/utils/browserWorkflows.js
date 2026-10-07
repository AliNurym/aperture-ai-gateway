import { PublicKey } from '@solana/web3.js';
import { APERTURE_PROGRAM_ID, GATEWAY_PUBKEY_PIN, TREASURY_PUBKEY_PIN, canonicalJson,
  canonicalQuoteMessage, isPortableFilename, sha256Hex, verifyGatewayReceipt, verifyDevnetSettlement } from './protocol.js';
import { MAX_INPUT_BYTES, hashBytes, jobManifest, validateObject, verifyJobManifest } from './jobs.js';
import { validateSource } from './workloads.js';

export const WORKFLOW_STORAGE_KEY = 'aperture-browser-workflow:v1';
export const MAX_WORKFLOW_RATE = 25000;
export const TASK_ID = /^task-[0-9a-f]{32}$/;
export const STEP_ID = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
const STEP_FIELDS = new Set(['id', 'source', 'inputs', 'parameters', 'depends_on', 'max_cost_lamports', 'max_runtime_seconds']);

export function check(condition, message) { if (!condition) throw new Error(message); }
export function same(left, right) { return canonicalJson(left) === canonicalJson(right); }
export function clone(value) { return JSON.parse(JSON.stringify(value)); }

function validText(value) {
  if (value.isWellFormed) return value.isWellFormed();
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xD800 && unit <= 0xDBFF) {
      const next = value.charCodeAt(++index);
      if (!(next >= 0xDC00 && next <= 0xDFFF)) return false;
    } else if (unit >= 0xDC00 && unit <= 0xDFFF) return false;
  }
  return true;
}

function validJson(value) {
  const pending = [[value, 0]];
  let count = 0;
  while (pending.length) {
    const [item, depth] = pending.pop();
    check(++count <= 100000 && depth <= 64, 'Parameters exceed the supported nesting or item bound.');
    if (typeof item === 'number') check(Number.isFinite(item) && (!Number.isInteger(item) || Number.isSafeInteger(item)), 'Use finite parameter numbers and strings for large integers.');
    else if (typeof item === 'string') check(validText(item), 'Text contains invalid Unicode.');
    else if (item && typeof item === 'object') {
      check(Array.isArray(item) || Object.getPrototypeOf(item) === Object.prototype || Object.getPrototypeOf(item) === null, 'Parameters must contain plain JSON values.');
      for (const [key, child] of Object.entries(item)) { pending.push([key, depth + 1], [child, depth + 1]); }
    } else check(item === null || typeof item === 'boolean', 'Parameters must contain JSON values.');
  }
}

export async function validateBrowserPlan(value) {
  check(value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === 'max_cost_lamports,steps,version' && value.version === 1, 'Use a version 1 workflow with max_cost_lamports and steps.');
  check(Number.isSafeInteger(value.max_cost_lamports) && value.max_cost_lamports > 0 && value.max_cost_lamports <= 100000000000, 'Invalid workflow maximum cost.');
  check(Array.isArray(value.steps) && value.steps.length > 0 && value.steps.length <= 256, 'Use 1 to 256 workflow steps.');
  const identifiers = new Set();
  const steps = [];
  for (const raw of value.steps) {
    check(raw && typeof raw === 'object' && !Array.isArray(raw) && Object.keys(raw).every(key => STEP_FIELDS.has(key)), 'Unknown workflow step fields.');
    check(typeof raw.id === 'string' && STEP_ID.test(raw.id) && !identifiers.has(raw.id), 'Workflow step IDs must be valid and unique.');
    identifiers.add(raw.id);
    check(typeof raw.source === 'string' && validText(raw.source), 'Source must be valid Unicode text.');
    validateSource(raw.source);
    const cost = raw.max_cost_lamports ?? 100000;
    const runtime = raw.max_runtime_seconds ?? 30;
    check(Number.isSafeInteger(cost) && cost > 0 && cost <= 1000000000 && Number.isSafeInteger(runtime) && runtime > 0 && runtime <= 180, 'Invalid workflow step cost or runtime.');
    const parameters = raw.parameters ?? {};
    check(parameters && typeof parameters === 'object' && !Array.isArray(parameters), 'Step parameters must be a JSON object.');
    validJson(parameters);
    check(new TextEncoder().encode(JSON.stringify(parameters)).length <= 32000, 'Step parameters exceed 32,000 UTF-8 bytes.');
    const inputs = raw.inputs ?? [];
    const depends = raw.depends_on ?? [];
    check(Array.isArray(inputs) && inputs.length <= 16 && Array.isArray(depends) && depends.every(item => typeof item === 'string'), 'Invalid step inputs or dependencies.');
    const dependencies = new Set(depends);
    const names = new Set();
    let total = 0;
    for (const input of inputs) {
      const dependency = input && Object.keys(input).sort().join(',') === 'artifact,from_step';
      if (dependency) {
        check(typeof input.from_step === 'string' && isPortableFilename(input.artifact), 'Invalid dependency artifact name.');
        dependencies.add(input.from_step);
      } else { validateObject(input); total += input.size_bytes; }
      const name = (dependency ? input.artifact : input.name).toLowerCase();
      check(!names.has(name), 'Each step needs input filenames that remain unique regardless of case.');
      names.add(name);
    }
    check(total <= MAX_INPUT_BYTES, 'Direct step inputs exceed 64 MiB.');
    steps.push({ id: raw.id, source: raw.source, inputs: clone(inputs), parameters: clone(parameters),
      depends_on: [...dependencies].sort(), max_cost_lamports: cost, max_runtime_seconds: runtime });
  }
  check(steps.reduce((sum, step) => sum + step.max_cost_lamports, 0) <= value.max_cost_lamports, 'Step spending caps exceed the declared workflow maximum.');
  check(steps.every(step => step.depends_on.every(id => identifiers.has(id) && id !== step.id)), 'Workflow has an unknown or self dependency.');
  const ordered = [], pending = [...steps], done = new Set();
  while (pending.length) {
    const index = pending.findIndex(step => step.depends_on.every(id => done.has(id)));
    check(index >= 0, 'Workflow has a dependency cycle.');
    const [step] = pending.splice(index, 1); ordered.push(step); done.add(step.id);
  }
  return { version: 1, max_cost_lamports: value.max_cost_lamports, steps: ordered };
}

export function normalizedApi(value) {
  const url = new URL(value);
  check(!url.username && !url.password && !url.search && !url.hash
    && (url.protocol === 'https:' || url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)), 'Use the final HTTPS gateway URL, or HTTP on loopback.');
  return url.href.replace(/\/$/, '');
}

export function workflowContext(apiUrl, owner, health) {
  check(health && health.program_id === APERTURE_PROGRAM_ID && typeof health.demo_mode === 'boolean', 'Gateway identity is unavailable or differs from the pinned program.');
  check(new PublicKey(owner).toBase58() === owner && new PublicKey(health.gateway_pubkey).toBase58() === health.gateway_pubkey, 'Invalid workflow signing identity.');
  const network = health.demo_mode ? 'off_chain' : 'devnet';
  check(!GATEWAY_PUBKEY_PIN || health.gateway_pubkey === GATEWAY_PUBKEY_PIN, 'Gateway signer differs from the frontend pin.');
  if (network === 'devnet') check(GATEWAY_PUBKEY_PIN && TREASURY_PUBKEY_PIN, 'Pin the Devnet gateway and treasury before execution.');
  return { api_url: normalizedApi(apiUrl), owner, network, program_id: APERTURE_PROGRAM_ID,
    gateway_pubkey: health.gateway_pubkey, treasury: network === 'devnet' ? TREASURY_PUBKEY_PIN : null,
    gateway_pin: GATEWAY_PUBKEY_PIN, treasury_pin: TREASURY_PUBKEY_PIN, max_rate_lamports: MAX_WORKFLOW_RATE };
}

export async function verifyWorkflowQuote(quote, step, spec, context, allowExpired = false) {
  check(quote && quote.wallet === context.owner && quote.agent_pubkey === context.owner
    && quote.code_sha256 === await sha256Hex(step.source) && quote.max_cost_lamports === step.max_cost_lamports
    && quote.max_runtime_seconds === step.max_runtime_seconds && quote.program_id === context.program_id
    && quote.gateway_pubkey === context.gateway_pubkey && quote.network === context.network
    && quote.treasury === context.treasury, 'Quote changed the approved identity, source, bounds or deployment.');
  check(typeof quote.quote_id === 'string' && quote.quote_id.length >= 16 && quote.quote_id.length <= 128
    && Number.isSafeInteger(quote.rate_lamports) && quote.rate_lamports > 0 && quote.rate_lamports <= MAX_WORKFLOW_RATE
    && quote.rate_lamports <= step.max_cost_lamports && Number.isSafeInteger(quote.passport_version) && quote.passport_version >= 0
    && quote.effective_runtime_seconds === Math.min(step.max_runtime_seconds, Math.floor(step.max_cost_lamports / quote.rate_lamports)), 'Quote rate or execution bounds are invalid.');
  check(Number.isSafeInteger(quote.expires_at) && quote.expires_at > 0
    && (allowExpired || quote.expires_at * 1000 > Date.now() && quote.expires_at * 1000 <= Date.now() + 120000), 'The quote expired; review it again before signing.');
  check(quote.message === canonicalQuoteMessage(quote), 'Quote authorization does not match its displayed values.');
  await verifyJobManifest(quote, spec);
  return quote;
}

export async function verifyUserSignature(owner, signature, message) {
  check(signature instanceof Uint8Array && signature.length === 64, 'Wallet returned an invalid signature.');
  const key = await crypto.subtle.importKey('raw', new PublicKey(owner).toBytes(), { name: 'Ed25519' }, false, ['verify']);
  check(await crypto.subtle.verify({ name: 'Ed25519' }, key, signature, new TextEncoder().encode(message)), 'Wallet signature differs from the approved owner.');
}

export async function resolveStepManifest(journal, step) {
  const inputs = step.inputs.map(reference => {
    if (!Object.hasOwn(reference, 'from_step')) return reference;
    const previous = journal.steps.find(item => item.id === reference.from_step);
    check(previous?.state === 'completed', 'Dependency has not completed with verified results.');
    const artifact = previous.artifacts.find(item => item.name === reference.artifact);
    check(artifact, 'The required dependency result file is absent.');
    return artifact;
  });
  return jobManifest(step.source, inputs, JSON.stringify(step.parameters));
}

async function readBounded(response, maximum) {
  const declared = response.headers.get('Content-Length');
  if (declared !== null && !(Number(declared) <= maximum)) {
    await response.body?.cancel().catch(() => {});
    throw new Error('Gateway response exceeds the expected size.');
  }
  check(response.body?.getReader, 'This browser cannot read bounded result streams.');
  const reader = response.body.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      check(length <= maximum, 'Gateway response exceeds the expected size.');
      chunks.push(value);
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}

export async function workflowRequest(context, path, { method = 'GET', body, token, signal, bytes = false, maximum = 2500000 } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timeout = setTimeout(abort, bytes ? 30000 : 15000);
  try {
    const response = await fetch(context.api_url + path, { method, credentials: 'omit', redirect: 'error', signal: controller.signal,
      headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { 'X-Aperture-Task-Token': token } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    const content = await readBounded(response, response.ok ? maximum : 64000);
    if (!response.ok) {
      const error = new Error(response.status === 429 ? 'Gateway rate limit reached. Keep this authorization and recover it after the retry interval.' : 'Gateway request failed (HTTP ' + response.status + ').');
      error.status = response.status; error.retryAfter = response.headers.get('Retry-After');
      throw error;
    }
    if (bytes) return content;
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(content)); }
    catch { throw new Error('Gateway returned an invalid JSON response. Keep the current authorization and checkpoint.'); }
  } finally { clearTimeout(timeout); signal?.removeEventListener('abort', abort); }
}

export async function verifyCompletedStep(context, saved, connection, signal) {
  check(saved.quote && saved.quote.wallet === context.owner && saved.quote.agent_pubkey === context.owner
    && saved.quote.network === context.network && saved.quote.program_id === context.program_id
    && saved.quote.gateway_pubkey === context.gateway_pubkey && saved.quote.treasury === context.treasury,
  'Retained task quote differs from the original workflow context.');
  check(TASK_ID.test(saved.task_id) && typeof saved.token === 'string' && /^[A-Za-z0-9_-]{32,128}$/.test(saved.token), 'Task recovery capability is invalid.');
  const bytes = await workflowRequest(context, '/download/' + saved.task_id, { token: saved.token, signal, bytes: true, maximum: 1000000 });
  const fullLog = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const verified = await verifyGatewayReceipt(saved.receipt, saved.quote, saved.task_id, fullLog);
  check(verified.verified, verified.reason || 'Task receipt verification failed.');
  check(['completed', 'failed', 'cancelled'].includes(saved.receipt.execution_status), 'Receipt execution status is invalid.');
  if (saved.receipt.execution_status === 'completed') check(saved.receipt.settlement_type === (context.network === 'devnet' ? 'DEVNET' : 'OFF_CHAIN'), 'A completed task must have the settlement type of its approved network.');
  if (saved.receipt.settlement_type === 'DEVNET') {
    check(connection && await connection.getGenesisHash() === 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG', 'The independent RPC is not Solana Devnet.');
    await verifyDevnetSettlement(connection, saved.receipt, saved.quote, saved.task_id);
  }
  return verified;
}

export async function downloadWorkflowArtifact(context, saved, artifact, connection) {
  await verifyCompletedStep(context, saved, connection);
  const item = validateObject(artifact, 8 * 1024 * 1024);
  check(saved.receipt.artifacts.some(value => same(value, item)), 'File reference is absent from the signed receipt.');
  const bytes = await workflowRequest(context, '/tasks/' + saved.task_id + '/artifacts/' + item.object_id,
    { token: saved.token, bytes: true, maximum: item.size_bytes });
  check(bytes.length === item.size_bytes && await hashBytes(bytes) === item.sha256, 'Downloaded file differs from its signed size or digest.');
  return bytes;
}

export function publicWorkflow(journal) {
  if (!journal) return null;
  return { id: journal.id, owner: journal.context.owner, network: journal.context.network, plan: clone(journal.plan),
    steps: journal.steps.map(({ id, state, task_id, receipt, artifacts, verified }) => ({ id,
      state: ['completed', 'failed'].includes(state) && !verified ? 'verifying' : state, ...(task_id ? { task_id } : {}),
      ...(receipt && verified ? { receipt: clone(receipt) } : {}), artifacts: verified ? clone(artifacts || []) : [] })),
    completed_steps: journal.steps.filter(item => item.state === 'completed' && item.verified).length, total_steps: journal.steps.length,
    stop_requested: journal.stop_requested, started: journal.started };
}
