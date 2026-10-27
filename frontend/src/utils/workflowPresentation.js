export function workflowStepDisplayState(step) {
  return step?.state === 'failed' && step.receipt?.execution_status === 'cancelled'
    ? 'cancelled'
    : step?.state;
}
