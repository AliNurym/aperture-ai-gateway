import { PublicKey } from '@solana/web3.js';

const viteEnv = import.meta.env || {};
export const DEFAULT_APERTURE_PROGRAM_ID = 'A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ';
export const APERTURE_PROGRAM_ID = (viteEnv.VITE_APERTURE_PROGRAM_ID || '').trim() || DEFAULT_APERTURE_PROGRAM_ID;
export const GATEWAY_PUBKEY_PIN = (viteEnv.VITE_APERTURE_GATEWAY_PUBKEY || '').trim();
export const TREASURY_PUBKEY_PIN = (viteEnv.VITE_APERTURE_TREASURY_PUBKEY || '').trim();

export const QUOTE_MESSAGE_KEYS = ['quote_id', 'wallet', 'agent_pubkey', 'code_sha256', 'rate_lamports', 'max_cost_lamports', 'max_runtime_seconds', 'expires_at', 'passport_version', 'program_id', 'network', 'gateway_pubkey', 'treasury'];

export function isPortableFilename(name) {
  return typeof name === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(name)
    && !/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name) && !name.endsWith('.');
}

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
  const version = Object.hasOwn(quote, 'workload') ? 3 : 2;
  if (version === 3) {
    if (!/^[0-9a-f]{64}$/.test(quote.workload_sha256)) throw new Error('Data job has no valid manifest digest.');
    bound.workload_sha256 = quote.workload_sha256;
  } else if (Object.hasOwn(quote, 'workload_sha256')) throw new Error('A job digest requires its manifest.');
  return 'Aperture execution authorization v' + version + '\naudience:aperture-gateway\naction:execute\n' + canonicalJson(bound);
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

export async function verifyAgentPassport(agent, expectedOwner, verifyAllowance = true) {
  const fail = reason => ({ verified: false, reason });
  try {
    if (!agent || typeof agent !== 'object' || agent.owner !== expectedOwner
        || !['devnet', 'off_chain'].includes(agent.network)
        || agent.attestation !== (agent.network === 'devnet' ? 'SOLANA_DEVNET' : 'OWNER_SIGNED_OFF_CHAIN')) {
      return fail('Passport owner, network or attestation does not match.');
    }
    const passportKeys = [
      'owner', 'agent_pubkey', 'name', 'max_cost_lamports', 'max_runtime_seconds',
      'total_budget_lamports', 'expires_at', 'capabilities', 'program_id', 'network',
      'version', 'metadata_hash',
    ];
    const passport = Object.fromEntries(passportKeys.map(key => [key, agent[key]]));
    if (typeof passport.agent_pubkey !== 'string' || new PublicKey(passport.agent_pubkey).toBase58() !== passport.agent_pubkey
        || typeof passport.name !== 'string' || passport.name.length < 1 || passport.name.length > 80 || !passport.name.trim()
        || !Number.isSafeInteger(passport.max_cost_lamports) || passport.max_cost_lamports <= 0 || passport.max_cost_lamports > 1_000_000_000
        || !Number.isSafeInteger(passport.max_runtime_seconds) || passport.max_runtime_seconds < 1 || passport.max_runtime_seconds > 180
        || !Number.isSafeInteger(passport.total_budget_lamports) || passport.total_budget_lamports < passport.max_cost_lamports || passport.total_budget_lamports > 100_000_000_000
        || !Number.isSafeInteger(passport.expires_at) || passport.expires_at <= 0
        || !Number.isSafeInteger(passport.version) || passport.version < 1
        || !Array.isArray(passport.capabilities) || passport.capabilities.length !== 1 || passport.capabilities[0] !== 'python.execute'
        || passport.program_id !== APERTURE_PROGRAM_ID || !/^[0-9a-f]{64}$/.test(passport.metadata_hash)) {
      return fail('Passport policy fields are invalid.');
    }
    const prefix = 'Aperture agent delegation v1\naudience:aperture-gateway\n';
    const message = agent.owner_signed_message;
    if (typeof message !== 'string' || !message.startsWith(prefix)) return fail('Passport has no owner-signed message.');
    const payloadText = message.slice(prefix.length);
    let signed;
    try { signed = JSON.parse(payloadText); }
    catch { return fail('Owner-signed passport message is not valid JSON.'); }
    if (canonicalJson(signed) !== payloadText
        || !equalJsonValue(Object.keys(signed).sort(), ['action', 'challenge_expires_at', 'nonce', 'passport'])
        || !['register', 'update', 'revoke'].includes(signed.action)
        || typeof signed.nonce !== 'string' || signed.nonce.length < 16 || signed.nonce.length > 128
        || !Number.isSafeInteger(signed.challenge_expires_at) || signed.challenge_expires_at <= 0
        || !equalJsonValue(signed.passport, passport)
        || agent.revoked !== (signed.action === 'revoke')) {
      return fail('Returned passport differs from the owner-signed policy.');
    }
    const { metadata_hash: metadataHash, ...metadata } = passport;
    if (await sha256Hex(canonicalJson(metadata)) !== metadataHash) return fail('Passport metadata hash is invalid.');
    const ownerSignature = Array.isArray(agent.owner_signature) && agent.owner_signature.length === 64
      && agent.owner_signature.every(byte => Number.isInteger(byte) && byte >= 0 && byte <= 255)
      ? Uint8Array.from(agent.owner_signature) : null;
    if (!await verifyEd25519(expectedOwner, ownerSignature, message)) return fail('Owner signature verification failed.');

    if (verifyAllowance) {
      const source = agent.network === 'devnet' ? 'solana_devnet' : 'gateway_ledger';
      if (agent.allowance_source !== source) return fail('Allowance source does not match passport network.');
      if (agent.allowance_status === 'available') {
        const { spent_lamports: spent, reserved_lamports: reserved, remaining_lamports: remaining } = agent;
        if (![spent, reserved, remaining].every(value => Number.isSafeInteger(value) && value >= 0)
            || remaining !== Math.max(0, passport.total_budget_lamports - spent - reserved)) {
          return fail('Allowance counters are invalid or inconsistent.');
        }
      } else if (agent.allowance_status !== 'unavailable'
          || agent.spent_lamports !== null || agent.reserved_lamports !== null || agent.remaining_lamports !== null) {
        return fail('Allowance status is invalid.');
      }
    }
    return { verified: true };
  } catch (error) {
    return fail(error?.message || 'Passport verification is unavailable.');
  }
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
    if (!Number.isSafeInteger(quote.rate_lamports) || quote.rate_lamports <= 0
        || !Number.isSafeInteger(quote.max_cost_lamports) || quote.max_cost_lamports < quote.rate_lamports
        || !Number.isSafeInteger(quote.max_runtime_seconds) || quote.max_runtime_seconds <= 0) {
      return fail('The approved quote has invalid runtime bounds.');
    }
    const effectiveRuntime = Math.min(quote.max_runtime_seconds, Math.floor(quote.max_cost_lamports / quote.rate_lamports));
    // Older tab records omit this derived value; the signed bounds still define it.
    if (Object.hasOwn(quote, 'effective_runtime_seconds') && quote.effective_runtime_seconds !== effectiveRuntime) return fail('The approved quote effective runtime differs from its budget and rate.');
    const expected = {
      receipt_version: 1, task_id: taskId, task_hash: taskHash, quote_id: quote.quote_id,
      owner_wallet: quote.wallet, agent_pubkey: quote.agent_pubkey, passport_version: quote.passport_version,
      code_sha256: quote.code_sha256, output_sha256: outputHash, rate_lamports: quote.rate_lamports,
      max_cost_lamports: quote.max_cost_lamports, max_runtime_seconds: quote.max_runtime_seconds,
    };
    if (Object.entries(expected).some(([key, value]) => receipt[key] !== value)) return fail('Receipt identity, authorization, or raw-output hash differs from the approved task.');
    if (quote.workload_sha256) {
      if (receipt.workload_sha256 !== quote.workload_sha256 || !Array.isArray(receipt.artifacts)
          || receipt.artifacts.length > 16) return fail('Result files are not bound to the approved data job.');
      const names = new Set();
      let total = 0;
      for (const item of receipt.artifacts) {
        if (!item || Object.keys(item).sort().join(',') !== 'name,object_id,sha256,size_bytes'
            || !isPortableFilename(item.name)
            || !/^obj-[0-9a-f]{32}$/.test(item.object_id) || !/^[0-9a-f]{64}$/.test(item.sha256)
            || !Number.isSafeInteger(item.size_bytes) || item.size_bytes < 1 || item.size_bytes > 8 * 1024 * 1024
            || names.has(item.name.toLowerCase())) return fail('Result file manifest is invalid.');
        total += item.size_bytes;
        names.add(item.name.toLowerCase());
      }
      if (total > 16 * 1024 * 1024) return fail('Result files exceed the approved output bounds.');
    } else if (Object.hasOwn(receipt, 'workload_sha256') || Object.hasOwn(receipt, 'artifacts')) return fail('Unexpected data job evidence for a source-only task.');
    if (typeof receipt.execution_time !== 'number' || !Number.isFinite(receipt.execution_time)
        || receipt.execution_time < 0 || receipt.execution_time > effectiveRuntime) return fail('Receipt runtime exceeds the budgeted execution limit.');
    if (receipt.charged_lamports !== null && (!Number.isSafeInteger(receipt.charged_lamports)
        || receipt.charged_lamports < 0 || receipt.charged_lamports > quote.max_cost_lamports)) return fail('Receipt charge exceeds the approved maximum.');
    const allowedSettlementTypes = quote.network === 'devnet'
      ? ['DEVNET', 'NOT_STARTED']
      : quote.network === 'off_chain' ? ['OFF_CHAIN', 'NOT_STARTED'] : [];
    if (!allowedSettlementTypes.includes(receipt.settlement_type)) return fail('Receipt settlement type does not match the approved network.');
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
      if (quote.workload_sha256) {
        workerExpected.workload_sha256 = quote.workload_sha256;
        if (!equalJsonValue(worker.artifacts, receipt.artifacts)) return fail('Worker result files differ from the gateway receipt.');
      }
      if (Object.entries(workerExpected).some(([key, value]) => worker[key] !== value)
          || worker.execution_mode !== receipt.execution_backend
          || !Number.isSafeInteger(worker.execution_time_ms) || worker.execution_time_ms < 0
          || worker.execution_time_ms > effectiveRuntime * 1000) return fail('Worker attestation differs from the gateway receipt or budgeted execution bounds.');
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
  if (!Number.isSafeInteger(quote.rate_lamports) || quote.rate_lamports <= 0
      || !Number.isSafeInteger(quote.max_cost_lamports) || quote.max_cost_lamports < quote.rate_lamports
      || !Number.isSafeInteger(quote.max_runtime_seconds) || quote.max_runtime_seconds <= 0) {
    throw new Error('The approved quote has invalid runtime bounds.');
  }
  const effectiveRuntime = Math.min(quote.max_runtime_seconds, Math.floor(quote.max_cost_lamports / quote.rate_lamports));
  if (Object.hasOwn(quote, 'effective_runtime_seconds') && quote.effective_runtime_seconds !== effectiveRuntime) {
    throw new Error('The approved quote effective runtime differs from its budget and rate.');
  }
  const taskHash = await sha256Hex(taskId);
  if (receipt.task_hash !== taskHash) throw new Error('The settlement task identifier differs.');
  const hashBytes = Uint8Array.from(taskHash.match(/.{2}/g), pair => parseInt(pair, 16));
  const program = new PublicKey(quote.program_id);
  const [address] = PublicKey.findProgramAddressSync([new TextEncoder().encode('task'), hashBytes], program);
  const [account, statuses, receiptHistory] = await Promise.all([
    connection.getAccountInfo(address, 'confirmed'),
    connection.getSignatureStatuses([receipt.settlement_signature], { searchTransactionHistory: true }),
    connection.getSignaturesForAddress(address, { limit: 20 }, 'confirmed'),
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
  const startedAt = view.getBigInt64(152, true);
  const deadline = view.getBigInt64(160, true);
  if (startedAt <= 0n || deadline <= startedAt || deadline > startedAt + BigInt(effectiveRuntime)) {
    throw new Error('The on-chain task runtime exceeds the approved quote limit.');
  }
  const status = statuses.value[0];
  if (!status || status.err !== null || !['confirmed', 'finalized'].includes(status.confirmationStatus)) {
    throw new Error('The settlement transaction has not confirmed successfully.');
  }
  if (!receiptHistory.some(item => item.signature === receipt.settlement_signature && item.err === null)) {
    throw new Error('The settlement transaction is not associated with this task receipt account.');
  }
  return { verified: true, chainReceipt: address.toBase58(),
    reason: 'The on-chain task receipt and confirmed Devnet transaction match the approved task.' };
}
