export function executionBoundaryLabel(mode) {
  if (mode === 'trusted_local') return 'Runs on the host; no container isolation';
  if (mode === 'docker') return 'Worker reports a Docker task container';
  if (mode === 'inference_proxy') return 'Configured provider; serving hardware is unverified';
  return 'Not reported';
}
