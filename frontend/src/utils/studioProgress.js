const PRICE_STATUSES = new Set(['reviewing', 'quoted', 'signing', 'submitting', 'uncertain', 'retryable']);
const WORKER_STATUSES = new Set(['queued', 'running', 'settlement_pending', 'stopping']);

export function studioProgressStep({
  status,
  sentinelPanelOpen = false,
  sentinelMatchesSource = false,
  hasReceipt = false,
} = {}) {
  if (PRICE_STATUSES.has(status)) return 2;
  if (WORKER_STATUSES.has(status)) return 3;
  if (['verifying', 'completed', 'unverified'].includes(status)) return 4;
  if (status === 'failed' || status === 'blocked') return hasReceipt ? 4 : 2;
  if (status === 'cancelled') return hasReceipt ? 4 : 3;

  if (status === 'idle') {
    if (sentinelMatchesSource) return 2;
    if (sentinelPanelOpen) return 1;
    return 0;
  }

  // Source editing and file staging happen before price review; unknown states
  // must never make the rail claim that a receipt already exists.
  return 0;
}

export function studioStepComplete(index, {
  progressStep = 0,
  status,
  sentinelMatchesSource = false,
} = {}) {
  if (index === 1) return Boolean(sentinelMatchesSource);
  return index < progressStep || (status === 'completed' && index === progressStep);
}
