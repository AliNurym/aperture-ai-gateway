import axios from 'axios';
import { PublicKey } from '@solana/web3.js';
import { APERTURE_PROGRAM_ID, GATEWAY_PUBKEY_PIN, canonicalJson } from './protocol';
import { validateObject } from './jobs';

const MAX_STORAGE_BYTES = 256 * 1024 * 1024;
const MAX_STORAGE_OBJECTS = 512;
const STATES = new Set(['authorized', 'uploading', 'ready', 'deleting']);
const REFERENCE_KEYS = ['object_id', 'name', 'sha256', 'size_bytes'];

export function storageContext(apiUrl, health) {
  if (!apiUrl || typeof health?.demo_mode !== 'boolean' || !health.gateway_pubkey || !health.program_id) throw new Error('Connect a configured gateway before opening private storage.');
  if (health.program_id !== APERTURE_PROGRAM_ID) throw new Error('The gateway program differs from this console deployment.');
  if (GATEWAY_PUBKEY_PIN && health.gateway_pubkey !== GATEWAY_PUBKEY_PIN) throw new Error('The gateway signer differs from this console deployment.');
  if (!health.demo_mode && !GATEWAY_PUBKEY_PIN) throw new Error('Configure the gateway signing key in this console before accessing Devnet storage.');
  try { new PublicKey(health.gateway_pubkey); }
  catch { throw new Error('The gateway has an invalid signing identity.'); }
  return {
    apiUrl: apiUrl.replace(/\/$/, ''), program_id: health.program_id,
    gateway_pubkey: health.gateway_pubkey, network: health.demo_mode ? 'off_chain' : 'devnet',
  };
}

export function objectReference(item) {
  return validateObject(Object.fromEntries(REFERENCE_KEYS.map(key => [key, item?.[key]])));
}

export function validateStorageUsage(usage) {
  if (!usage || !Array.isArray(usage.objects) || !Number.isSafeInteger(usage.object_count)
      || usage.object_count !== usage.objects.length || usage.object_count < 0
      || usage.object_count > MAX_STORAGE_OBJECTS || usage.max_object_count !== MAX_STORAGE_OBJECTS
      || usage.max_size_bytes !== MAX_STORAGE_BYTES || !Number.isSafeInteger(usage.size_bytes)
      || usage.size_bytes < 0 || usage.size_bytes > MAX_STORAGE_BYTES) throw new Error('The gateway returned invalid storage capacity.');
  const ids = new Set();
  const objects = usage.objects.map(item => {
    const reference = objectReference(item);
    if (!STATES.has(item.state) || ids.has(reference.object_id)
        || item.task_id !== null && (typeof item.task_id !== 'string' || !/^task-[0-9a-f]{32}$/.test(item.task_id))) throw new Error('The gateway returned an invalid retained file list.');
    ids.add(reference.object_id);
    return { ...reference, state: item.state, task_id: item.task_id };
  });
  if (objects.reduce((sum, item) => sum + item.size_bytes, 0) !== usage.size_bytes) throw new Error('The retained file sizes differ from the reported storage usage.');
  return {
    objects, size_bytes: usage.size_bytes, object_count: usage.object_count,
    max_size_bytes: usage.max_size_bytes, max_object_count: usage.max_object_count,
  };
}

async function signedRequest({ context, owner, signMessage, action, reference, signal, ensureCurrent = () => {} }) {
  const check = () => {
    if (signal?.aborted) throw new DOMException('Private storage request was cancelled.', 'AbortError');
    ensureCurrent();
  };
  check();
  if (typeof signMessage !== 'function') throw new Error('Choose a wallet that supports message signing.');
  const issued_at = Math.floor(Date.now() / 1000);
  const nonce = crypto.randomUUID().replaceAll('-', '');
  const message = 'Aperture agent task access v1\naudience:aperture-gateway\n' + canonicalJson({
    action, owner, agent_pubkey: owner, issued_at, nonce,
    task_id: reference?.object_id ?? null, limit: reference?.size_bytes ?? null,
    cursor: reference ? reference.name + ':' + reference.sha256 : null,
    program_id: context.program_id, gateway_pubkey: context.gateway_pubkey, network: context.network,
  });
  check();
  const signed = await signMessage(new TextEncoder().encode(message));
  check();
  const signature = Array.from(signed);
  if (signature.length !== 64 || signature.some(byte => !Number.isInteger(byte) || byte < 0 || byte > 255)) throw new Error('The wallet returned an invalid message signature.');
  const { data } = await axios.post(context.apiUrl + (action === 'object-usage' ? '/objects/usage' : '/objects/release'), {
    owner, agent_pubkey: owner, issued_at, nonce, signature, ...(reference || {}),
  }, { signal, timeout: 15000 });
  check();
  return data;
}

export async function requestStorageUsage(options) {
  return validateStorageUsage(await signedRequest({ ...options, action: 'object-usage' }));
}

export async function releaseStorageObject(options) {
  const reference = objectReference(options.reference);
  const result = await signedRequest({ ...options, reference, action: 'release-object' });
  if (!result || canonicalJson(result) !== canonicalJson({ object_id: reference.object_id, status: 'released', size_bytes: reference.size_bytes })) throw new Error('The release response differs from the selected file. Refresh storage to inspect its current state.');
  return result;
}
