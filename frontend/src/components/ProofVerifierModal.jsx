import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';
import './ProofVerifierModal.css';

function signatureLabel(value) {
  if (Array.isArray(value)) return value.length + ' bytes';
  return typeof value === 'string' && value.length ? 'Present' : 'Unavailable';
}

function chargeLabel(value) {
  return Number.isSafeInteger(value) ? value.toLocaleString() + ' lamports' : 'Unavailable';
}

export default function ProofVerifierModal({ isOpen, onClose, receipt, taskId, chainReceiptAddress, verified, verificationNote }) {
  const [copied, setCopied] = useState(false);
  const dialogRef = useRef(null);
  const closeButtonRef = useRef(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return undefined;

    const previousFocus = document.activeElement;
    closeButtonRef.current?.focus({ preventScroll: true });

    const handleDialogKeyDown = event => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onCloseRef.current?.();
        return;
      }
      if (event.key !== 'Tab') return;

      const dialog = dialogRef.current;
      const focusable = dialog?.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
      );
      const elements = Array.from(focusable || []).filter(element => !element.hasAttribute('hidden'));
      if (!elements.length) {
        event.preventDefault();
        dialog?.focus();
        return;
      }

      const first = elements[0];
      const last = elements[elements.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog?.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !dialog?.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleDialogKeyDown);
    return () => {
      document.removeEventListener('keydown', handleDialogKeyDown);
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const hasReceipt = Boolean(receipt && typeof receipt === 'object');
  const receiptJson = hasReceipt ? JSON.stringify(receipt, null, 2) : '';
  const actualTaskId = taskId || receipt?.task_id || 'Unavailable';
  const statusLabel = verified === true ? receipt?.settlement_type === 'DEVNET'
    ? 'Receipt, raw output and Devnet settlement verified'
    : receipt?.settlement_type === 'OFF_CHAIN'
      ? 'Receipt and raw output verified · off-chain'
      : 'Receipt and raw output verified'
    : verified === false ? 'Verification failed'
      : 'Not verified in this session';
  const statusClass = verified === true ? 'is-verified' : verified === false ? 'is-failed' : 'is-unverified';
  const statusPill = verified === true ? 'Verified' : verified === false ? 'Failed' : 'Unverified';
  const fields = hasReceipt ? [
    ['Task ID', actualTaskId],
    ['Gateway signer', receipt.gateway_pubkey],
    ['Worker signer', receipt.worker_receipt?.worker_pubkey || receipt.worker_pubkey],
    ['Execution status', receipt.execution_status],
    ['Execution boundary', receipt.execution_backend],
    ['Settlement type', receipt.settlement_type],
    ['Actual charge', chargeLabel(receipt.charged_lamports)],
    ['Runtime', typeof receipt.execution_time === 'number' ? receipt.execution_time + ' seconds' : 'Unavailable'],
    ['Source SHA-256', receipt.code_sha256],
    ['Output SHA-256', receipt.output_sha256],
    ['Receipt SHA-256', receipt.receipt_sha256],
    ['Gateway signature', signatureLabel(receipt.gateway_signature)],
    ['Worker signature', signatureLabel(receipt.worker_signature)],
    ['Settlement signature', receipt.settlement_signature],
    ['On-chain task receipt', chainReceiptAddress || receipt.task_receipt_pda || receipt.settlement_evidence?.receipt_pda],
  ].filter(([, value]) => value !== undefined && value !== null && value !== '') : [];

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(receiptJson);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const handleDownload = () => {
    if (!hasReceipt) return;
    const blob = new Blob([receiptJson], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'aperture-receipt-' + actualTaskId + '.json';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="proof-modal-backdrop" onClick={onClose}>
      <div
        ref={dialogRef}
        className="proof-modal"
        onClick={event => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="proof-modal-title"
        aria-describedby="proof-modal-description"
        tabIndex={-1}
      >
        <header className="proof-modal-header">
          <div className="proof-modal-title-wrap">
            <span className="proof-shield-badge"><Icon name="shield" size={18} /></span>
            <div>
              <h2 id="proof-modal-title">Receipt evidence</h2>
              <p id="proof-modal-description">{hasReceipt ? 'The signed receipt returned for this Studio task.' : 'How Aperture checks a real task receipt.'}</p>
            </div>
          </div>
          <button ref={closeButtonRef} className="proof-modal-close" onClick={onClose} aria-label="Close modal"><Icon name="close" size={18} /></button>
        </header>

        {hasReceipt ? (
          <>
            <div className="proof-modal-body">
              <div className={'proof-status-banner ' + statusClass} role="status">
                <span className="proof-status-indicator" />
                <strong>{statusLabel}</strong>
                <span className="proof-pill-valid">{statusPill}</span>
              </div>
              {verificationNote && <p className="proof-verification-note">{verificationNote}</p>}
              <div className="proof-cert-grid">
                {fields.map(([label, value]) => (
                  <div className="proof-field-row" key={label}>
                    <span className="proof-field-label">{label}</span>
                    <span className={'proof-field-val ' + (label.includes('SHA-256') || label.includes('signer') || label === 'Task ID' ? 'mono' : '')}>{String(value)}</span>
                  </div>
                ))}
              </div>
              <p className="proof-limits-note">A valid signature binds this receipt to its approved task and output. It does not independently prove faithful computation or the worker's execution environment.</p>
              <details className="proof-json-details">
                <summary>View the complete signed receipt JSON</summary>
                <div className="proof-json-wrap"><pre><code>{receiptJson}</code></pre></div>
              </details>
            </div>
          </>
        ) : (
          <div className="proof-modal-body proof-empty-state">
            <h3>How receipt verification works</h3>
            <p>The browser checks the gateway signature against the approved quote, downloads the raw output and compares its SHA-256 hash, then verifies the worker signature when a worker receipt is present.</p>
            <p>For Devnet tasks it also checks the confirmed Solana task receipt and settlement against the approved owner, source, and spending limit. Off-chain tasks have no Solana settlement or on-chain task receipt.</p>
            <p>Signatures bind the reported evidence; they do not prove that a remote worker faithfully computed the result or ran in a particular environment. Open a completed Studio run to inspect its actual receipt.</p>
          </div>
        )}

        <footer className="proof-modal-footer">
          {hasReceipt && <div className="proof-footer-actions">
            <button className="console-button secondary" onClick={handleCopy}><Icon name="copy" size={16} />{copied ? 'Copied receipt JSON' : 'Copy receipt JSON'}</button>
            <button className="console-button primary" onClick={handleDownload}><Icon name="download" size={16} />Download receipt</button>
          </div>}
          <button className="console-text-button" onClick={onClose}>Close</button>
        </footer>
      </div>
    </div>
  );
}
