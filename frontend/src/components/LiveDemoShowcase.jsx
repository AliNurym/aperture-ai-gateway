import { useState, useEffect } from 'react';
import Icon from './Icon';
import ProofVerifierModal from './ProofVerifierModal';
import './LiveDemoShowcase.css';

const SCENARIOS = [
  {
    id: 'monte-carlo',
    badge: 'DePIN AI Compute',
    title: '10,000 Portfolio Risk Simulation',
    description: 'Agent requests bounded compute to evaluate tail loss (VaR 95%) and Sharpe ratio without exposing portfolio weights.',
    tariff: '35,000 lamports',
    runtime: '0.28s',
    stats: [
      { label: 'Expected Alpha', value: '+18.4%', positive: true },
      { label: 'VaR (95% Confidence)', value: '-3.2%', neutral: true },
      { label: 'Execution Time', value: '284 ms' },
      { label: 'Gas Cost', value: '0.000035 SOL' },
    ],
    bars: [12, 28, 55, 84, 120, 158, 142, 105, 68, 38, 18, 8],
    studioPreset: 'risk',
  },
  {
    id: 'csv-analytics',
    badge: 'Zero-Leak Analytics',
    title: 'Confidential Dataset Aggregation',
    description: 'Streams customer records through isolated sandbox containers. Only mathematical sums return to agent context.',
    tariff: '18,500 lamports',
    runtime: '0.19s',
    stats: [
      { label: 'Records Ingested', value: '5,000 rows' },
      { label: 'Aggregate Volume', value: '$1,429,800', positive: true },
      { label: 'Context Token Leakage', value: '0 tokens', positive: true },
      { label: 'Integrity Digest', value: 'SHA-256 MATCH' },
    ],
    bars: [45, 88, 130, 95, 110, 140, 75, 120, 90, 60, 40, 20],
    studioPreset: 'dataset',
  },
  {
    id: 'guardrail',
    badge: 'Cryptographic Safety',
    title: 'Budget Guardrail & Cap Enforcement',
    description: 'Demonstrates automated rejection of unauthorized spend before code is allowed to execute.',
    tariff: 'Rejected',
    runtime: '0.01s',
    stats: [
      { label: 'Requested Budget', value: '500,000 lamports' },
      { label: 'Owner Allowance', value: '50,000 lamports' },
      { label: 'Gateway Verdict', value: '403 Capped', warning: true },
      { label: 'Capital Loss', value: '0 lamports (Protected)', positive: true },
    ],
    bars: [10, 15, 20, 25, 30, 20, 15, 10, 5, 0, 0, 0],
    studioPreset: 'policy',
  },
];

export default function LiveDemoShowcase({ onOpenStudio }) {
  const [activeScenarioId, setActiveScenarioId] = useState('monte-carlo');
  const [isRunning, setIsRunning] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [hasCompleted, setHasCompleted] = useState(false);
  const [showProofModal, setShowProofModal] = useState(false);

  const scenario = SCENARIOS.find(s => s.id === activeScenarioId) || SCENARIOS[0];

  const runSimulation = () => {
    if (isRunning) return;
    setIsRunning(true);
    setHasCompleted(false);
    setCurrentStep(1);

    // Sequence through the 4 pipeline steps
    setTimeout(() => setCurrentStep(2), 650);
    setTimeout(() => setCurrentStep(3), 1300);
    setTimeout(() => setCurrentStep(4), 1950);
    setTimeout(() => {
      setIsRunning(false);
      setHasCompleted(true);
    }, 2500);
  };

  const handleScenarioChange = (id) => {
    setActiveScenarioId(id);
    setIsRunning(false);
    setCurrentStep(0);
    setHasCompleted(false);
  };

  return (
    <section className="console-panel live-demo-showcase" aria-label="Interactive live agent demonstration">
      <div className="demo-showcase-header">
        <div className="demo-header-copy">
          <span className="console-eyebrow">
            <Icon name="spark" size={14} />
            ONE-CLICK LIVE DEMO
          </span>
          <h2>Interactive Agent Compute Simulator</h2>
          <p>Test the full DePIN lifecycle in real-time: tariff negotiation, Ed25519 authorization, AST sandbox isolation, and verifiable receipt generation.</p>
        </div>

        <div className="demo-scenario-tabs">
          {SCENARIOS.map(s => (
            <button
              key={s.id}
              className={`demo-scenario-tab ${activeScenarioId === s.id ? 'active' : ''}`}
              onClick={() => handleScenarioChange(s.id)}
              disabled={isRunning}
            >
              {s.id === 'monte-carlo' && '🎲 Monte Carlo Risk'}
              {s.id === 'csv-analytics' && '⚡ Private CSV'}
              {s.id === 'guardrail' && '🛡️ Budget Guardrail'}
            </button>
          ))}
        </div>
      </div>

      <div className="demo-stage-box">
        <div className="demo-stage-info">
          <div className="demo-info-top">
            <span className="demo-badge">{scenario.badge}</span>
            <span className="demo-tariff-chip">Tariff: <strong>{scenario.tariff}</strong></span>
          </div>
          <h3>{scenario.title}</h3>
          <p>{scenario.description}</p>
        </div>

        <div className="demo-pipeline-progress">
          <div className={`demo-progress-step ${currentStep >= 1 ? 'active' : ''} ${currentStep > 1 || hasCompleted ? 'done' : ''}`}>
            <div className="step-circle">{currentStep > 1 || hasCompleted ? <Icon name="check" size={14} /> : '1'}</div>
            <span>1. Quote Negotiation</span>
          </div>
          <div className="demo-progress-line" />

          <div className={`demo-progress-step ${currentStep >= 2 ? 'active' : ''} ${currentStep > 2 || hasCompleted ? 'done' : ''}`}>
            <div className="step-circle">{currentStep > 2 || hasCompleted ? <Icon name="check" size={14} /> : '2'}</div>
            <span>2. Ed25519 Sign</span>
          </div>
          <div className="demo-progress-line" />

          <div className={`demo-progress-step ${currentStep >= 3 ? 'active' : ''} ${currentStep > 3 || hasCompleted ? 'done' : ''}`}>
            <div className="step-circle">{currentStep > 3 || hasCompleted ? <Icon name="check" size={14} /> : '3'}</div>
            <span>3. AST Worker Sandbox</span>
          </div>
          <div className="demo-progress-line" />

          <div className={`demo-progress-step ${currentStep >= 4 || hasCompleted ? 'active done' : ''}`}>
            <div className="step-circle">{hasCompleted ? <Icon name="check" size={14} /> : '4'}</div>
            <span>4. Verified Receipt</span>
          </div>
        </div>

        {isRunning && (
          <div className="demo-running-banner">
            <span className="demo-pulse-orb" />
            <span>Executing live decentralized container on DePIN Grid...</span>
          </div>
        )}

        {hasCompleted && (
          <div className="demo-results-card">
            <div className="demo-results-header">
              <div className="demo-verified-tag">
                <Icon name="shield" size={16} />
                <span>COMPUTATION VERIFIED & ATTESTED</span>
              </div>
              <span className="demo-settle-tag">Off-chain / Solana Settlement Ready</span>
            </div>

            <div className="demo-metrics-grid">
              {scenario.stats.map((st, idx) => (
                <div key={idx} className="demo-stat-cell">
                  <span className="demo-stat-label">{st.label}</span>
                  <strong className={`demo-stat-val ${st.positive ? 'positive' : st.warning ? 'warning' : ''}`}>
                    {st.value}
                  </strong>
                </div>
              ))}
            </div>

            <div className="demo-histogram-wrap" aria-label="Visual computation artifact preview">
              <span className="demo-chart-label">Output Distribution Curve ({scenario.id === 'monte-carlo' ? 'Gaussian Log-Normal VaR' : 'Category Density'})</span>
              <div className="demo-histogram">
                {scenario.bars.map((height, i) => (
                  <div key={i} className="demo-bar" style={{ height: `${(height / 160) * 100}%` }} title={`Bin ${i + 1}: ${height} occurrences`} />
                ))}
              </div>
            </div>

            <div className="demo-results-actions">
              <button className="console-button primary" onClick={() => setShowProofModal(true)}>
                <Icon name="shield" size={17} />
                Inspect Cryptographic Proof
              </button>
              <button className="console-button secondary" onClick={() => onOpenStudio && onOpenStudio(scenario.studioPreset)}>
                <Icon name="code" size={17} />
                Open Code in Compute Studio
              </button>
              <button className="console-text-button" onClick={runSimulation}>
                <Icon name="refresh" size={15} />
                Run Again
              </button>
            </div>
          </div>
        )}

        {!isRunning && !hasCompleted && (
          <div className="demo-trigger-action">
            <button className="console-button primary demo-run-btn" onClick={runSimulation}>
              <Icon name="play" size={18} />
              Simulate Live Agent Execution
            </button>
            <span className="demo-hint-text">Simulates real tariff calculation and AST sandbox validation in ~2.5 seconds</span>
          </div>
        )}
      </div>

      <ProofVerifierModal
        isOpen={showProofModal}
        onClose={() => setShowProofModal(false)}
        proofData={{
          tariffRateLamportsSec: scenario.id === 'monte-carlo' ? 1000 : 800,
          actualSpendLamports: scenario.id === 'monte-carlo' ? 35000 : 18500,
          runtimeSeconds: scenario.id === 'monte-carlo' ? 0.284 : 0.19,
        }}
      />
    </section>
  );
}
