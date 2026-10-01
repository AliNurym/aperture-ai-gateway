export function requestErrorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail.filter(item => typeof item?.msg === 'string').map(item => {
      const field = Array.isArray(item.loc) ? item.loc.filter(part => !['body', 'query', 'path'].includes(part)).join('.') : '';
      const message = item.msg.replace(/^Value error, /, '');
      return field ? `${field}: ${message}` : message;
    });
    if (messages.length) return messages.join(' ');
  }
  if (error?.code === 'ERR_NETWORK') return 'Could not reach the gateway. Check its address and connection.';
  if (error?.code === 'ECONNABORTED') return 'The gateway did not respond in time. Try again when the connection is available.';
  return error?.message || 'The request could not be completed.';
}
