export function receiptPaymentField(receipt) {
  if (receipt?.settlement_type === 'OFF_CHAIN') return ['Payment status', 'No on-chain payment'];
  const amount = receipt?.charged_lamports;
  return ['Actual charge', Number.isSafeInteger(amount) ? amount.toLocaleString('en-US') + ' lamports' : 'Unavailable'];
}
