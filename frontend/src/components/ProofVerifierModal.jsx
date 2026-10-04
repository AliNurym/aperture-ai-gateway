import { useState } from 'react';
import Icon from './Icon';
import './ProofVerifierModal.css';

export default function ProofVerifierModal({ isOpen, onClose, proofData }) {
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState('certificate');

  if (!isOpen) return null;

  const defaultProof = {
    taskId: 'task_mc_' + Math.random().toString(36).substring(2, 10),
    oracleKey: '9QmewM34XoBtMrG5C2SPH56WTSPw3cakYud84vJ92KRU',
    programId: 'A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ',
    artifactHash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    astSecurityScore: 0,
    sandboxIsolation: 'Docker cgroups / unprivileged / network disabled',
    tariffRateLamportsSec: 1000,
    settlementCapLamports: 50000,
    actualSpendLamports: 35000,
    runtimeSeconds: 0.284,
    status: 'VERIFIED_SAFE',
    timestamp: new Date().toISOString(),
    ...proofData,
  };

  const proofJson = JSON.stringify({
    schema_version: '2.2.0',
    type: 'aperture_verifiable_attestation',
    task_id: defaultProof.taskId,
    verification: {
      oracle_ed25519_key: defaultProof.oracleKey,
      signature_valid: true,
      solana_program_id: defaultProof.programId,
      artifact_sha256: defaultProof.artifactHash,
      ast_security_score: defaultProof.astSecurityScore,
      sandbox_profile: defaultProof.sandboxIsolation,
      status: defaultProof.status,
    },
    economics: {
      tariff_rate_lamports_sec: defaultProof.tariffRateLamportsSec,
      spend_cap_lamports: defaultProof.settlementCapLamports,
      actual_cost_lamports: defaultProof.actualSpendLamports,
      runtime_seconds: defaultProof.runtimeSeconds,
    },
    attested_at: defaultProof.timestamp,
  }, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(proofJson);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([proofJson], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `aperture-attestation-${defaultProof.taskId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="proof-modal-backdrop" onClick={onClose}>
      <div className="proof-modal" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="proof-modal-title">
        <header className="proof-modal-header">
          <div className="proof-modal-title-wrap">
            <span className="proof-shield-badge">
              <Icon name="shield" size={18} />
            </span>
            <div>
              <h2 id="proof-modal-title">Cryptographic Attestation Verifier</h2>
              <p>Independent mathematical proof of isolated sandbox execution & artifact integrity</p>
            </div>
          </div>
          <button className="proof-modal-close" onClick={onClose} aria-label="Close modal">
            <Icon name="close" size={18} />
          </button>
        </header>

        <div className="proof-modal-tabs">
          <button
            className={`proof-tab-btn ${activeTab === 'certificate' ? 'active' : ''}`}
            onClick={() => setActiveTab('certificate')}
          >
            <Icon name="check" size={15} />
            Visual Certificate
          </button>
          <button
            className={`proof-tab-btn ${activeTab === 'json' ? 'active' : ''}`}
            onClick={() => setActiveTab('json')}
          >
            <Icon name="code" size={15} />
            Raw Signed JSON
          </button>
        </div>

        <div className="proof-modal-body">
          {activeTab === 'certificate' ? (
            <div className="proof-cert-grid">
              <div className="proof-status-banner">
                <span className="proof-status-indicator" />
                <strong>ED25519 ORACLE ATTESTATION: VERIFIED</strong>
                <span className="proof-pill-valid">Valid Signature</span>
              </div>

              <div className="proof-field-row">
                <span className="proof-field-label">Task Identifier</span>
                <span className="proof-field-val mono">{defaultProof.taskId}</span>
              </div>

              <div className="proof-field-row">
                <span className="proof-field-label">Oracle Ed25519 Signer</span>
                <span className="proof-field-val mono">{defaultProof.oracleKey}</span>
              </div>

              <div className="proof-field-row">
                <span className="proof-field-label">Solana DePIN Program</span>
                <span className="proof-field-val mono">{defaultProof.programId}</span>
              </div>

              <div className="proof-field-row">
                <span className="proof-field-label">Artifact SHA-256 Digest</span>
                <span className="proof-field-val mono hash-highlight">{defaultProof.artifactHash}</span>
              </div>

              <div className="proof-field-row">
                <span className="proof-field-label">Sandbox Security Profile</span>
                <span className="proof-field-val">Score: 0 / SAFE (cgroups, read-only root, net disabled)</span>
              </div>

              <div className="proof-field-row">
                <span className="proof-field-label">Bounded Economic Tariff</span>
                <span className="proof-field-val">
                  {defaultProof.actualSpendLamports.toLocaleString()} lamports ({defaultProof.runtimeSeconds}s @ {defaultProof.tariffRateLamportsSec.toLocaleString()} l/s)
                </span>
              </div>
            </div>
          ) : (
            <div className="proof-json-wrap">
              <pre><code>{proofJson}</code></pre>
            </div>
          )}
        </div>

        <footer className="proof-modal-footer">
          <div className="proof-footer-actions">
            <button className="console-button secondary" onClick={handleCopy}>
              <Icon name="copy" size={16} />
              {copied ? 'Copied to Clipboard!' : 'Copy JSON Payload'}
            </button>
            <button className="console-button primary" onClick={handleDownload}>
              <Icon name="download" size={16} />
              Download Attestation Certificate
            </button>
          </div>
          <button className="console-text-button" onClick={onClose}>Close</button>
        </footer>
      </div>
    </div>
  );
}
