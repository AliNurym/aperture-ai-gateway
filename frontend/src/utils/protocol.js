import { PublicKey } from '@solana/web3.js';

export const DEFAULT_APERTURE_PROGRAM_ID = 'A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ';
export const APERTURE_PROGRAM_ID = (import.meta.env.VITE_APERTURE_PROGRAM_ID || '').trim() || DEFAULT_APERTURE_PROGRAM_ID;
export const GATEWAY_PUBKEY_PIN = (import.meta.env.VITE_APERTURE_GATEWAY_PUBKEY || '').trim();
export const TREASURY_PUBKEY_PIN = (import.meta.env.VITE_APERTURE_TREASURY_PUBKEY || '').trim();

export const QUOTE_MESSAGE_KEYS = ['quote_id', 'wallet', 'agent_pubkey', 'code_sha256', 'rate_lamports', 'max_cost_lamports', 'max_runtime_seconds', 'expires_at', 'passport_version', 'program_id', 'network', 'gateway_pubkey', 'treasury'];

export function canonicalJson(value) {
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
  }
  return JSON.stringify(value);
}

export async function sha256Hex(value) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
  return Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('');
}

export function canonicalQuoteMessage(quote) {
  if (QUOTE_MESSAGE_KEYS.some(key => !Object.hasOwn(quote, key))) throw new Error('The gateway returned an incomplete authorization quote.');
  const bound = Object.fromEntries(QUOTE_MESSAGE_KEYS.map(key => [key, quote[key]]));
  return 'Aperture execution authorization v2\naudience:aperture-gateway\naction:execute\n' + canonicalJson(bound);
}

export async function anchorDiscriminator(name) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode('global:' + name)));
  return digest.slice(0, 8);
}

export async function agentInstructionData(action, passport) {
  const name = { register: 'register_agent', update: 'update_agent', revoke: 'revoke_agent' }[action];
  if (!name) throw new Error('Unknown agent instruction.');
  const discriminator = await anchorDiscriminator(name);
  if (action === 'revoke') return discriminator;
  if (!/^[a-f0-9]{64}$/i.test(passport.metadata_hash || '')) throw new Error('The passport metadata hash is invalid.');
  const bytes = new Uint8Array(8 + 32 + 8 + 4 + 8 + 8);
  bytes.set(discriminator, 0);
  bytes.set(Uint8Array.from(passport.metadata_hash.match(/.{2}/g), pair => parseInt(pair, 16)), 8);
  const write = (offset, value, width) => {
    let remaining = BigInt(value);
    if (remaining < 0n) throw new Error('The passport contains a negative instruction value.');
    for (let index = 0; index < width; index += 1) {
      bytes[offset + index] = Number(remaining & 0xffn);
      remaining >>= 8n;
    }
    if (remaining !== 0n) throw new Error('The passport instruction value is out of range.');
  };
  write(40, passport.max_cost_lamports, 8);
  write(48, passport.max_runtime_seconds, 4);
  write(52, passport.expires_at, 8);
  write(60, passport.total_budget_lamports, 8);
  return bytes;
}

function decodeBase58(value) {
  const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  if (typeof value !== 'string' || !value) return new Uint8Array();
  let number = 0n;
  for (const char of value) {
    const digit = alphabet.indexOf(char);
    if (digit < 0) throw new Error('Invalid base58 signature.');
    number = number * 58n + BigInt(digit);
  }
  const decoded = [];
  while (number > 0n) {
    decoded.unshift(Number(number & 0xffn));
    number >>= 8n;
  }
  let leadingZeroes = 0;
  while (leadingZeroes < value.length && value[leadingZeroes] === '1') leadingZeroes += 1;
  return Uint8Array.from([...Array(leadingZeroes).fill(0), ...decoded]);
}

async function verifyEd25519(publicKey, signature, message) {
  if (!(signature instanceof Uint8Array) || signature.length !== 64) return false;
  const key = await crypto.subtle.importKey('raw', new PublicKey(publicKey).toBytes(), { name: 'Ed25519' }, false, ['verify']);
  return crypto.subtle.verify({ name: 'Ed25519' }, key, signature, new TextEncoder().encode(message));
}

const RECEIPT_WRAPPER_KEYS = new Set(['gateway_pubkey', 'gateway_signature', 'signed_message', 'receipt_sha256', 'explorer_url', 'status']);
function equalJsonValue(left, right) {
  if (left === right) return true;
  if (Array.isArray(left) || Array.isArray(right)) return Array.isArray(left) && Array.isArray(right)
    && left.length === right.length && left.every((value, index) => equalJsonValue(value, right[index]));
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  return leftKeys.length === rightKeys.length && leftKeys.every((key, index) => key === rightKeys[index] && equalJsonValue(left[key], right[key]));
}

export async function verifyGatewayReceipt(receipt, quote, taskId, fullLog) {
  const fail = reason => ({ verified: false, reason });
  try {
    if (!receipt || !quote) return fail('The approved quote is unavailable.');
    if (quote.network === 'devnet' && (quote.gateway_pubkey !== GATEWAY_PUBKEY_PIN
        || quote.program_id !== APERTURE_PROGRAM_ID || quote.treasury !== TREASURY_PUBKEY_PIN)) {
      return fail('The live quote does not match the frontend deployment pins.');
    }
    const evidence = Object.fromEntries(Object.entries(receipt).filter(([key]) => !RECEIPT_WRAPPER_KEYS.has(key)));
    const prefix = 'Aperture compute receipt v1\n';
    const message = receipt.signed_message;
    if (typeof message !== 'string' || !message.startsWith(prefix)) return fail('Receipt has no valid signed message.');
    let signedEvidence;
    try { signedEvidence = JSON.parse(message.slice(prefix.length)); }
    catch { return fail('Gateway-signed receipt evidence is not valid JSON.'); }
    if (!equalJsonValue(signedEvidence, evidence) || receipt.receipt_sha256 !== await sha256Hex(message)) return fail('Receipt fields or digest differ from the gateway-signed evidence.');
    if (receipt.gateway_pubkey !== quote.gateway_pubkey) return fail('Receipt signer differs from the approved quote.');
    const gatewaySignature = Array.isArray(receipt.gateway_signature) && receipt.gateway_signature.length === 64
      && receipt.gateway_signature.every(byte => Number.isInteger(byte) && byte >= 0 && byte <= 255)
      ? Uint8Array.from(receipt.gateway_signature) : null;
    if (!await verifyEd25519(quote.gateway_pubkey, gatewaySignature, message)) return fail('Gateway signature verification failed or is unsupported by this browser.');

    const outputHash = await sha256Hex(fullLog);
    const taskHash = await sha256Hex(taskId);
    const expected = {
      receipt_version: 1, task_id: taskId, task_hash: taskHash, quote_id: quote.quote_id,
      owner_wallet: quote.wallet, agent_pubkey: quote.agent_pubkey, passport_version: quote.passport_version,
      code_sha256: quote.code_sha256, output_sha256: outputHash, rate_lamports: quote.rate_lamports,
      max_cost_lamports: quote.max_cost_lamports, max_runtime_seconds: quote.max_runtime_seconds,
    };
    if (Object.entries(expected).some(([key, value]) => receipt[key] !== value)) return fail('Receipt identity, authorization, or raw-output hash differs from the approved task.');
    if (typeof receipt.execution_time !== 'number' || !Number.isFinite(receipt.execution_time)
        || receipt.execution_time < 0 || receipt.execution_time > quote.max_runtime_seconds) return fail('Receipt runtime exceeds the approved limit.');
    if (receipt.charged_lamports !== null && (!Number.isSafeInteger(receipt.charged_lamports)
        || receipt.charged_lamports < 0 || receipt.charged_lamports > quote.max_cost_lamports)) return fail('Receipt charge exceeds the approved maximum.');
    if (receipt.settlement_type === 'DEVNET' && (quote.network !== 'devnet'
        || receipt.charged_lamports === null || typeof receipt.settlement_signature !== 'string' || !receipt.settlement_signature)) {
      return fail('The reported Devnet settlement is incomplete.');
    }

    const worker = receipt.worker_receipt;
    if (worker) {
      const workerSignature = decodeBase58(receipt.worker_signature || '');
      if (worker.domain !== 'aperture.worker.result.v1'
          || !await verifyEd25519(worker.worker_pubkey, workerSignature, canonicalJson(worker))) return fail('Worker signature verification failed.');
      const workerExpected = {
        task_id: taskId, lease_id: receipt.lease_id, source_hash: quote.code_sha256,
        output_hash: outputHash, quote_id: quote.quote_id, agent_pubkey: quote.agent_pubkey,
        worker_id: receipt.worker_id, exit_code: receipt.exit_code,
      };
      if (Object.entries(workerExpected).some(([key, value]) => worker[key] !== value)
          || worker.execution_mode !== receipt.execution_backend
          || !Number.isSafeInteger(worker.execution_time_ms) || worker.execution_time_ms < 0
          || worker.execution_time_ms > quote.max_runtime_seconds * 1000 + 1000) return fail('Worker attestation differs from the gateway receipt or approved bounds.');
    } else if (receipt.execution_status === 'completed') return fail('A successful task has no signed worker receipt.');

    return { verified: true, reason: worker
      ? 'Gateway and worker signatures match the approved quote and raw output.'
      : 'Gateway signature matches the approved quote. Execution has no worker result.' };
  } catch (error) {
    return fail(error?.message || 'Receipt verification is unavailable.');
  }
}

export async function verifyDevnetSettlement(connection, receipt, quote, taskId) {
  if (quote.network !== 'devnet' || receipt.settlement_type !== 'DEVNET') {
    throw new Error('The receipt does not describe a Devnet settlement.');
  }
  const taskHash = await sha256Hex(taskId);
  if (receipt.task_hash !== taskHash) throw new Error('The settlement task identifier differs.');
  const hashBytes = Uint8Array.from(taskHash.match(/.{2}/g), pair => parseInt(pair, 16));
  const program = new PublicKey(quote.program_id);
  const [address] = PublicKey.findProgramAddressSync([new TextEncoder().encode('task'), hashBytes], program);
  const [account, statuses] = await Promise.all([
    connection.getAccountInfo(address, 'confirmed'),
    connection.getSignatureStatuses([receipt.settlement_signature], { searchTransactionHistory: true }),
  ]);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode('account:TaskReceipt')));
  const bytes = account?.data;
  if (!account || !account.owner.equals(program) || bytes.length !== 186
      || digest.slice(0, 8).some((byte, index) => bytes[index] !== byte) || bytes[184] !== 1) {
    throw new Error('The on-chain task receipt is absent, unsettled or incompatible.');
  }
  const hex = value => Array.from(value, byte => byte.toString(16).padStart(2, '0')).join('');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (new PublicKey(bytes.slice(8, 40)).toBase58() !== quote.wallet
      || new PublicKey(bytes.slice(40, 72)).toBase58() !== quote.agent_pubkey
      || hex(bytes.slice(72, 104)) !== taskHash || hex(bytes.slice(104, 136)) !== quote.code_sha256
      || view.getBigUint64(136, true) !== BigInt(quote.rate_lamports)
      || view.getBigUint64(144, true) !== BigInt(quote.max_cost_lamports)
      || view.getBigUint64(176, true) !== BigInt(receipt.charged_lamports)
      || view.getBigUint64(176, true) > BigInt(quote.max_cost_lamports)) {
    throw new Error('On-chain owner, source, rate or charge differs from the approved task.');
  }
  const status = statuses.value[0];
  if (!status || status.err !== null || !['confirmed', 'finalized'].includes(status.confirmationStatus)) {
    throw new Error('The settlement transaction has not confirmed successfully.');
  }
  return { verified: true, chainReceipt: address.toBase58(),
    reason: 'The on-chain task receipt and confirmed Devnet transaction match the approved task.' };
}
