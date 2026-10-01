import axios from 'axios';
import { canonicalJson, isPortableFilename, sha256Hex } from './protocol';

export const MAX_INPUT_BYTES = 64 * 1024 * 1024;

export function validateObject(item, maximum = MAX_INPUT_BYTES) {
  if (!item || Object.keys(item).sort().join(',') !== 'name,object_id,sha256,size_bytes'
      || typeof item.object_id !== 'string' || typeof item.name !== 'string' || typeof item.sha256 !== 'string'
      || !/^obj-[0-9a-f]{32}$/.test(item.object_id) || !isPortableFilename(item.name)
      || !/^[0-9a-f]{64}$/.test(item.sha256) || !Number.isSafeInteger(item.size_bytes)
      || item.size_bytes < 1 || item.size_bytes > maximum) throw new Error('Invalid immutable file reference.');
  return item;
}

export async function hashBytes(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('');
}

export async function jobManifest(source, inputs, text) {
  if (new TextEncoder().encode(text).length > 32000) throw new Error('Parameters must be a JSON object up to 32,000 bytes.');
  const parameters = JSON.parse(text);
  if (!parameters || typeof parameters !== 'object' || Array.isArray(parameters)) throw new Error('Parameters must be a JSON object up to 32,000 bytes.');
  const pending = [parameters];
  while (pending.length) {
    const value = pending.pop();
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) throw new Error('Parameter numbers must be finite. Use a string for values outside the supported numeric range.');
      if (Number.isInteger(value) && !Number.isSafeInteger(value)) throw new Error('Parameters contain an unsafe integer. Use a string for large IDs or exact decimal values.');
    } else if (value && typeof value === 'object') {
      for (const item of Object.values(value)) pending.push(item);
    }
  }
  const files = inputs.map(item => validateObject(item)).sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
  if (files.length > 16 || new Set(files.map(item => item.name.toLowerCase())).size !== files.length
      || files.reduce((sum, item) => sum + item.size_bytes, 0) > MAX_INPUT_BYTES) throw new Error('Use up to 16 uniquely named files, totaling 64 MiB.');
  return { version: 1, runtime: 'python', source_sha256: await sha256Hex(source), inputs: files, parameters };
}

export async function verifyJobManifest(quote, expected) {
  if (!quote.workload || typeof quote.workload_canonical !== 'string'
      || !/^[0-9a-f]{64}$/.test(quote.workload_sha256)
      || await sha256Hex(quote.workload_canonical) !== quote.workload_sha256
      || canonicalJson(JSON.parse(quote.workload_canonical)) !== canonicalJson(quote.workload)
      || canonicalJson(quote.workload) !== canonicalJson(expected)) throw new Error('The quote changed the approved files, parameters or source.');
  // Hash the gateway's exact serialization. Python and JavaScript serialize decimal
  // numbers differently; parsed values are still compared to the caller's plan.
}

export async function uploadInput({ apiUrl, file, owner, signMessage, health, signal, ensureCurrent = () => {} }) {
  const check = () => {
    if (signal?.aborted) throw new DOMException('Input upload was cancelled.', 'AbortError');
    ensureCurrent();
  };
  check();
  if (!isPortableFilename(file.name) || file.size < 1 || file.size > MAX_INPUT_BYTES) throw new Error('Use a portable filename with letters, numbers, dots, dashes or underscores, with no trailing dot; up to 64 MiB.');
  if (!health?.gateway_pubkey || !health?.program_id) throw new Error('Connect a configured gateway before uploading.');
  const bytes = await file.arrayBuffer();
  check();
  const digest = await hashBytes(bytes);
  check();
  const issued_at = Math.floor(Date.now() / 1000);
  const nonce = crypto.randomUUID().replaceAll('-', '');
  const message = 'Aperture agent task access v1\naudience:aperture-gateway\n' + canonicalJson({
    action: 'upload-object', owner, agent_pubkey: owner, issued_at, nonce,
    task_id: digest, limit: file.size, cursor: file.name,
    program_id: health.program_id, gateway_pubkey: health.gateway_pubkey,
    network: health.demo_mode ? 'off_chain' : 'devnet',
  });
  check();
  const signature = await signMessage(new TextEncoder().encode(message));
  check();
  const { data: authorization } = await axios.post(apiUrl + '/objects/authorize', {
    owner, agent_pubkey: owner, name: file.name, sha256: digest, size_bytes: file.size,
    issued_at, nonce, signature: Array.from(signature),
  }, { timeout: 15000, signal });
  check();
  const descriptor = validateObject(Object.fromEntries(['object_id', 'name', 'sha256', 'size_bytes'].map(key => [key, authorization[key]])));
  if (descriptor.sha256 !== digest || descriptor.name !== file.name || descriptor.size_bytes !== file.size
       || typeof authorization.upload_token !== 'string' || authorization.upload_token.length < 32) throw new Error('Input authorization changed the selected file.');
  check();
  const { data } = await axios.put(apiUrl + '/objects/' + descriptor.object_id, bytes, {
    headers: { 'X-Aperture-Upload-Token': authorization.upload_token, 'Content-Type': 'application/octet-stream' }, timeout: 120000, signal,
  });
  check();
  if (canonicalJson(data) !== canonicalJson(descriptor)) throw new Error('Uploaded file differs from its approved hash.');
  return descriptor;
}
