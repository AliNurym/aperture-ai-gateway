export function storageContextErrorMessage(error, demoMode) {
  const message = typeof error === 'string' ? error : error?.message || '';
  if (message === 'The gateway signer differs from this console deployment.') {
    return demoMode === true
      ? 'CSV uploads are blocked because this local gateway signer differs from this console. Start the unified local preview and open 127.0.0.1:3000; it starts the console, gateway and worker with a matching signer.'
      : 'This gateway signer does not match the key pinned in this console. CSV uploads are blocked. Verify the intended Devnet gateway and signer before continuing.';
  }
  return message;
}
