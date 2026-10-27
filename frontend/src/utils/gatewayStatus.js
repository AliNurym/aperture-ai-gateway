export function inspectGatewayStatus(telemetry, { programId, signerPin = '' }) {
  const online = telemetry?.state === 'online';
  const health = telemetry?.health;
  let issue = null;

  if (online && health) {
    if (health.program_id !== programId) issue = 'program_mismatch';
    else if (health.demo_mode !== true && signerPin && health.gateway_pubkey !== signerPin) issue = 'signer_mismatch';
  }

  const ready = online && health?.status === 'ready' && !issue;
  const label = issue === 'program_mismatch' ? 'Gateway program mismatch'
    : issue === 'signer_mismatch' ? 'Gateway signer mismatch'
      : ready ? 'Gateway connected'
        : online
          ? health?.status === 'workers_unavailable' ? 'Waiting for a worker' : 'Gateway needs setup'
          : telemetry?.state === 'checking' ? 'Checking gateway' : 'Gateway offline';

  return { ready, issue, label, tone: ready ? 'ready' : online ? 'warning' : 'muted' };
}
