import { sha256Hex } from './protocol.js';

export const RESTORED_SOURCE_PLACEHOLDER = '# Saved gateway task restored from this browser tab.\n# Original Python source is not stored in this checkpoint.\n# Inspect its source hash in the verified receipt.\n';

export function sourceIsAvailable(source) {
  return typeof source === 'string' && Boolean(source.trim()) && source !== RESTORED_SOURCE_PLACEHOLDER;
}

export function parseSentinelDraft(serialized) {
  try {
    const draft = JSON.parse(typeof serialized === 'string' ? serialized : 'null');
    return draft && typeof draft.id === 'string' && typeof draft.source === 'string'
      && typeof draft.prompt === 'string' && sourceIsAvailable(draft.source) ? draft : null;
  } catch {
    return null;
  }
}

export async function inspectRestoredSource(source, sourceHash) {
  const text = typeof source === 'string' ? source : '';
  if (!sourceIsAvailable(text)) return 'missing';
  if (typeof sourceHash !== 'string' || !/^[a-f0-9]{64}$/i.test(sourceHash)) return 'unknown';
  return (await sha256Hex(text)) === sourceHash.toLowerCase() ? 'match' : 'different';
}
