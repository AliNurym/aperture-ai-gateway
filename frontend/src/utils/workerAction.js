const MAX_WORKER_RATE_LAMPORTS_SEC = 1_000_000_000;

export function workerActionState(node, busy = false) {
  const offline = node?.online === false || node?.status === 'offline';
  const draining = node?.accepting_tasks === false;
  const rate = node?.rate_lamports_sec;
  const priced = Number.isSafeInteger(rate) && rate >= 1 && rate <= MAX_WORKER_RATE_LAMPORTS_SEC;

  if (offline) return { label: 'Offline', disabled: true };
  if (draining) return { label: 'Draining', disabled: true };
  if (!priced) return { label: 'Price not set', disabled: true };
  return { label: 'Use this worker', disabled: busy };
}
