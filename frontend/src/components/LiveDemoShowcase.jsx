import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';
import ProofVerifierModal from './ProofVerifierModal';
import './LiveDemoShowcase.css';

const SCENARIOS = [
  {
    id: 'resilient-csv',
    label: 'Resilient CSV Pipeline',
    icon: 'code',
    badge: 'Primary Scenario',
    title: '17,000-Row CSV Aggregation & Crash Recovery',
    description: 'Owner delegates a private 17,000-row CSV with a 100,000 lamports spend cap. The worker is interrupted after step 1, then resumes seamlessly from journal: 0 duplicate tasks, 0 extra charges, identical result.',
    tariff: '100,000 lamports cap',
    runtime: '7.96s (with recovery)',
    stats: [
      { label: 'Accepted rows', value: '16,983 (17 invalid)', positive: true },
      { label: 'Crash resilience', value: '0 duplicate tasks', positive: true },
      { label: 'Capital loss', value: '0 lamports (Protected)', positive: true },
      { label: 'Verified output', value: 'report.json · categories.csv', neutral: true },
    ],
    bars: [24, 48, 85, 120, 150, 160, 138, 102, 65, 35, 18, 6],
    studioPreset: 'dataset',
    steps: [
      { num: '1', title: '1. Stage CSV data', desc: '17,000 rows · 64 MiB limit' },
      { num: '2', title: '2. Approve budget cap', desc: 'Solana ceiling locked' },
      { num: '3', title: '3. Crash & journal resume', desc: 'Interrupted · 0 duplicates' },
      { num: '4', title: '4. Verified report files', desc: 'Ed25519 signature verified' },
    ],
    runningNotes: [
      'Staging 17,000 synthetic rows (SHA-256 checked, dataset kept out of prompt)...',
      'Owner locks 100,000 lamports budget ceiling on Solana payment channel...',
      'Simulating process interruption at step 1... resuming from journal with 0 duplicate tasks...',
      'Verifying signed gateway receipt and comparing report.json hashes byte-for-byte...',
    ],
  },
  {
    id: 'guardrail',
    label: 'Budget Guardrail',
    icon: 'shield',
    badge: 'Policy Enforcement',
    title: 'Spending Cap & Runaway Protection',
    description: 'Agent requests 500,000 lamports for unconstrained execution. Gateway blocks the request before worker execution because the owner allowance is capped at 50,000 lamports.',
    tariff: 'Rejected',
    runtime: '0.01s',
    stats: [
      { label: 'Requested budget', value: '500,000 lamports' },
      { label: 'Owner allowance', value: '50,000 lamports' },
      { label: 'Gateway verdict', value: '403 Capped', warning: true },
      { label: 'Capital loss', value: '0 lamports (Protected)', positive: true },
    ],
    bars: [10, 15, 20, 25, 30, 20, 15, 10, 5, 0, 0, 0],
    studioPreset: 'policy',
    steps: [
      { num: '1', title: '1. Quote requested', desc: '500,000 lamports requested' },
      { num: '2', title: '2. Policy validation', desc: 'Compare owner allowance' },
      { num: '3', title: '3. Execution blocked', desc: '403 Forbidden · worker stopped' },
      { num: '4', title: '4. Treasury protected', desc: '0 lamports spent' },
    ],
    runningNotes: [
      'Agent creates task request specifying 500,000 lamports budget...',
      'Gateway compares request against Owner Passport allowance (50,000 max)...',
      'Allowance exceeded: Gateway terminates request with 403 Capped...',
      'Zero transactions submitted to Solana network, principal treasury protected...',
    ],
  },
  {
    id: 'monte-carlo',
    label: 'Monte Carlo Risk',
    icon: 'chip',
    badge: 'Bounded CPU',
    title: '10,000 Portfolio Risk Simulation',
    description: 'Agent requests bounded CPU compute to evaluate tail loss (VaR 95%) and Sharpe ratio without accessing network or host environment.',
    tariff: '35,000 lamports',
    runtime: '0.28s',
    stats: [
      { label: 'Expected alpha', value: '+18.4%', positive: true },
      { label: 'VaR (95%)', value: '-3.2%', neutral: true },
      { label: 'Worker runtime', value: '284 ms' },
      { label: 'Settlement cost', value: '35,000 lamports' },
    ],
    bars: [12, 28, 55, 84, 120, 158, 142, 105, 68, 38, 18, 8],
    studioPreset: 'risk',
    steps: [
      { num: '1', title: '1. Script submitted', desc: 'Bounded Python CPU script' },
      { num: '2', title: '2. Quoted & signed', desc: '35,000 lamports limit' },
      { num: '3', title: '3. Sandboxed compute', desc: 'Isolated worker process' },
      { num: '4', title: '4. Signed receipt', desc: 'Ed25519 signature returned' },
    ],
    runningNotes: [
      'Staging portfolio distribution parameters for Python worker...',
      'Authorizing single-task quote and verifying Ed25519 signature...',
      'Running 10,000 Monte Carlo paths in isolated 512 MiB CPU worker...',
      'Validating returned receipt against gateway public key...',
    ],
  },
];

export default function LiveDemoShowcase({ onOpenStudio, onOpenWorkflows }) {
  const [activeScenarioId, setActiveScenarioId] = useState('resilient-csv');
  const [isRunning, setIsRunning] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [hasCompleted, setHasCompleted] = useState(false);
  const [showReceiptGuide, setShowReceiptGuide] = useState(false);
  const timers = useRef([]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const scenario = SCENARIOS.find(s => s.id === activeScenarioId) || SCENARIOS[0];

  const runSimulation = () => {
    if (isRunning) return;
    timers.current.forEach(clearTimeout);
    setIsRunning(true);
    setHasCompleted(false);
    setCurrentStep(1);

    // Sequence through the 4 pipeline steps with enough time to read notes
    timers.current = [
      setTimeout(() => setCurrentStep(2), 700),
      setTimeout(() => setCurrentStep(3), 1450),
      setTimeout(() => setCurrentStep(4), 2200),
      setTimeout(() => {
        setIsRunning(false);
        setHasCompleted(true);
        timers.current = [];
      }, 2900),
    ];
  };

  const handleScenarioChange = (id) => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setActiveScenarioId(id);
    setIsRunning(false);
    setCurrentStep(0);
    setHasCompleted(false);
  };

  const currentNote = isRunning && currentStep > 0
    ? (scenario.runningNotes?.[currentStep - 1] || 'Simulating workflow...')
    : null;

  return (
    <section className="console-panel live-demo-showcase" aria-label="Illustrative agent workflow simulator">
      <div className="demo-showcase-header">
        <div className="demo-header-copy">
          <span className="console-eyebrow">
            <Icon name="spark" size={14} />
            INTERACTIVE SCENARIO SIMULATOR
          </span>
          <h2>See how Aperture protects agent workflows</h2>
          <p>
            Experience the core value: owner budget cap, isolated execution, and recovery after interruptions with zero duplicate tasks and zero extra charges.
          </p>
        </div>

        <div className="demo-scenario-tabs">
          {SCENARIOS.map(s => (
            <button
              key={s.id}
              className={`demo-scenario-tab ${activeScenarioId === s.id ? 'active' : ''}`}
              onClick={() => handleScenarioChange(s.id)}
              disabled={isRunning}
            >
              <Icon name={s.icon} size={14} />
              <span>{s.label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="demo-stage-box">
        <div className="demo-stage-info">
          <div className="demo-info-top">
            <span className="demo-badge">{scenario.badge}</span>
            <span className="demo-tariff-chip">Ceiling: <strong>{scenario.tariff}</strong> · Benchmark: <strong>{scenario.runtime}</strong></span>
          </div>
          <h3>{scenario.title}</h3>
          <p>{scenario.description}</p>
        </div>

        <div className="demo-pipeline-progress">
          {scenario.steps.map((st, i) => {
            const stepNum = i + 1;
            const isActive = currentStep >= stepNum;
            const isDone = currentStep > stepNum || hasCompleted;
            return (
              <div key={st.num} className="demo-step-wrapper">
                <div className={`demo-progress-step ${isActive ? 'active' : ''} ${isDone ? 'done' : ''}`}>
                  <div className="step-circle">{isDone ? <Icon name="check" size={14} /> : st.num}</div>
                  <span className="demo-step-title">{st.title}</span>
                  <small className="demo-step-sub">{st.desc}</small>
                </div>
                {i < scenario.steps.length - 1 && <div className={`demo-progress-line ${currentStep > stepNum ? 'filled' : ''}`} />}
              </div>
            );
          })}
        </div>

        {isRunning && (
          <div className="demo-running-banner">
            <span className="demo-pulse-orb" />
            <span>{currentNote}</span>
          </div>
        )}

        {hasCompleted && (
          <div className="demo-results-card">
            <div className="demo-results-header">
              <div className="demo-preview-tag">
                <Icon name="check" size={16} />
                <span>VERIFIED RUN · 0 DUPLICATE TASKS · 0 EXTRA CHARGES</span>
              </div>
              <span className="demo-settle-tag">Local benchmark snapshot from 05.10.2026</span>
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

            <div className="demo-histogram-wrap" aria-label="Illustrative output distribution preview">
              <span className="demo-chart-label">Processed Batch Cardinality ({scenario.id === 'resilient-csv' ? '17,000 Row Distribution across 5 Steps' : scenario.id === 'monte-carlo' ? 'Gaussian Log-Normal VaR' : 'Policy Bound'})</span>
              <div className="demo-histogram">
                {scenario.bars.map((height, i) => (
                  <div key={i} className="demo-bar" style={{ height: `${(height / 160) * 100}%` }} title={`Step batch ${i + 1}: ${height} relative weight`} />
                ))}
              </div>
            </div>

            <div className="demo-results-actions">
              {onOpenWorkflows && (
                <button className="console-button primary" onClick={onOpenWorkflows}>
                  <Icon name="arrow" size={17} />
                  Run Live Workflow in Console
                </button>
              )}
              <button className="console-button secondary" onClick={() => onOpenStudio && onOpenStudio(scenario.studioPreset)}>
                <Icon name="code" size={17} />
                Inspect Code in Studio
              </button>
              <button className="console-button secondary" onClick={() => setShowReceiptGuide(true)}>
                <Icon name="shield" size={17} />
                Receipt Verification Guide
              </button>
              <button className="console-text-button" onClick={runSimulation}>
                <Icon name="refresh" size={15} />
                Simulate Again
              </button>
            </div>
          </div>
        )}

        {!isRunning && !hasCompleted && (
          <div className="demo-trigger-action">
            <button className="console-button primary demo-run-btn" onClick={runSimulation}>
              <Icon name="play" size={18} />
              Simulate Resilient Workflow
            </button>
            <span className="demo-hint-text">Simulates intentional crash at step 1 and automatic resumption with zero duplicate tasks</span>
          </div>
        )}
      </div>

      <ProofVerifierModal
        isOpen={showReceiptGuide}
        onClose={() => setShowReceiptGuide(false)}
      />
    </section>
  );
}
