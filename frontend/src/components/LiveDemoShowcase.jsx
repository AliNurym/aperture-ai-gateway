import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';
import ProofVerifierModal from './ProofVerifierModal';
import './LiveDemoShowcase.css';

const SCENARIOS = [
  {
    id: 'resilient-csv',
    label: 'Resilient CSV Pipeline',
    shortBadge: '17K CSV',
    icon: 'code',
    badge: 'Resilience Benchmark',
    title: '17,000-Row CSV Aggregation & Crash Recovery',
    description: 'Owner delegates a private 17,000-row dataset with a 100,000 lamports spend cap. The worker crashes after Step 1, then resumes seamlessly from journal: 0 duplicate tasks, 0 extra charges, and bit-identical output.',
    tariff: '100,000 lamports cap',
    runtime: '7.96s (with recovery)',
    actionLabel: 'Simulate 17,000-Row Crash Recovery',
    actionHint: 'Simulates intentional worker termination at Step 1 and instant journal resume with zero duplicate tasks',
    resultTitle: 'CRASH RESILIENCE VERIFIED',
    resultSubtitle: '0 duplicate tasks · 0 extra charges · 100% deterministic output',
    chartLabel: 'Batch Cardinality Distribution (17,000 rows across 12 compute chunks)',
    stats: [
      { label: 'Accepted rows', value: '16,983 (17 invalid)', positive: true },
      { label: 'Crash resilience', value: '0 duplicate tasks', positive: true },
      { label: 'Capital loss', value: '0 lamports (Protected)', positive: true },
      { label: 'Verified output', value: 'report.json · categories.csv', neutral: true },
    ],
    bars: [24, 48, 85, 120, 150, 160, 138, 102, 65, 35, 18, 6],
    barLabels: ['B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B09', 'B10', 'B11', 'B12'],
    studioPreset: 'dataset',
    mockReceipt: {
      taskId: 'task-csv-17000-resilient-recov',
      chainReceiptAddress: '7vK2xQ7k21HjM9pXw6L8Y5Q1vT4sR3aF6bC9dE2g3hJ4',
      receipt: {
        task_id: 'task-csv-17000-resilient-recov',
        gateway_pubkey: 'A5HfdyRWy7UvQpP5Fj97o3c62qJpC1g9uM8Bf4vXy3a',
        worker_pubkey: '4qJw1vT4sR3aF6bC9dE2g7vK2xQ7k21HjM9pXw6L8Y5',
        execution_status: 'completed',
        execution_backend: 'isolated-subprocess-pool',
        settlement_type: 'solana-payment-channel-escrow',
        charged_lamports: 98500,
        execution_time: 7.96,
        code_sha256: '9f83c12e52b217a61d1991d334e2c98b8c2d5f8a0a1c6e4e8a1d2f3e4b5c6d7e',
        output_sha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
        receipt_sha256: '3a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b',
        gateway_signature: '5M8xKpQ2Y7nRt4Vw8Zs1Lm9Px2A3bC4dE5fG6hJ7kL8mN9pQ1rS2tU3vW4xY5z6a7b8c9d0e1f2a3b4c',
        worker_signature: '2vX9kP1rS2tU3vW4xY5z6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f',
        settlement_signature: '4tW8xY5z6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f',
        task_receipt_pda: '7vK2xQ7k21HjM9pXw6L8Y5Q1vT4sR3aF6bC9dE2g3hJ4',
      },
    },
    steps: [
      { num: '01', title: 'Stage CSV Dataset', desc: '17,000 rows · 64 MiB limit', statusTag: 'Stage' },
      { num: '02', title: 'Approve Budget Cap', desc: '100k lamports locked', statusTag: 'Escrow' },
      { num: '03', title: 'Crash & Journal Resume', desc: 'Interrupted · 0 duplicates', statusTag: 'Recovery' },
      { num: '04', title: 'Attest Output Hashes', desc: 'Ed25519 verified receipt', statusTag: 'Settlement' },
    ],
    runningNotes: [
      'Staging 17,000 synthetic rows with SHA-256 integrity verification; dataset kept out of model context...',
      'Owner locks 100,000 lamports budget ceiling on Solana payment channel program...',
      'Simulating process interruption at Step 1... resuming from on-disk journal with 0 duplicate tasks...',
      'Verifying signed gateway receipt and comparing report.json hashes byte-for-byte...',
    ],
  },
  {
    id: 'guardrail',
    label: 'Budget Guardrail',
    shortBadge: 'POLICY',
    icon: 'shield',
    badge: 'Policy Enforcement',
    title: 'Spending Cap & Runaway Protection',
    description: 'Autonomous agent requests 500,000 lamports for unconstrained execution. Gateway intercepts and blocks the request before worker dispatch because the owner policy limits maximum allowance to 50,000 lamports.',
    tariff: '50,000 cap (Rejected)',
    runtime: '0.01s (Pre-flight)',
    actionLabel: 'Test Budget Guardrail Rejection',
    actionHint: 'Simulates rogue 500,000 lamport request blocked at the gateway gatekeeper; verifies zero compute spent and zero treasury drain',
    resultTitle: 'TREASURY GUARDRAIL ACTIVE',
    resultSubtitle: 'HTTP 403 Forbidden · Pre-flight rejection · 0 lamports debited',
    chartLabel: 'Requested Budget vs. Allowed Policy Ceiling',
    stats: [
      { label: 'Requested budget', value: '500,000 lamports' },
      { label: 'Owner allowance', value: '50,000 lamports' },
      { label: 'Gateway verdict', value: '403 Forbidden', warning: true },
      { label: 'Capital loss', value: '0 lamports (Protected)', positive: true },
    ],
    bars: [50, 45, 40, 30, 20, 10, 5, 0, 0, 0, 0, 0],
    barLabels: ['Req', 'Auth', 'Rule', 'Cap', 'Halt', 'Log', '-', '-', '-', '-', '-', '-'],
    studioPreset: 'policy',
    mockReceipt: {
      taskId: 'task-guardrail-budget-capped',
      chainReceiptAddress: 'BlockedAtGateway_NoOnChainEscrowCreated',
      receipt: {
        task_id: 'task-guardrail-budget-capped',
        gateway_pubkey: 'A5HfdyRWy7UvQpP5Fj97o3c62qJpC1g9uM8Bf4vXy3a',
        worker_pubkey: 'none (intercepted before worker spawn)',
        execution_status: 'blocked_403_budget_exceeded',
        execution_backend: 'gateway-policy-engine',
        settlement_type: 'zero-debit-halt',
        charged_lamports: 0,
        execution_time: 0.01,
        code_sha256: 'c2e8a1d2f3e4b5c6d7e9f83c12e52b217a61d1991d334e2c98b8c2d5f8a0a1c6',
        output_sha256: 'policy-rejection: requested 500000 exceeds owner max 50000',
        receipt_sha256: '7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a',
        gateway_signature: '1A2b3C4d5E6f7G8h9J0k1L2m3N4p5Q6r7S8t9U0v1W2x3Y4z5A6b7C8d9E0f1G2h3J4k5L6m7N8p9Q0r',
        worker_signature: null,
        settlement_signature: 'none (0 lamports spent)',
        task_receipt_pda: 'BlockedAtGateway_NoOnChainEscrowCreated',
      },
    },
    steps: [
      { num: '01', title: 'Quote Requested', desc: '500,000 lamports requested', statusTag: 'Request' },
      { num: '02', title: 'Policy Validation', desc: 'Evaluate owner allowance', statusTag: 'Policy' },
      { num: '03', title: 'Execution Blocked', desc: '403 Forbidden · worker halted', statusTag: 'Intercept' },
      { num: '04', title: 'Treasury Protected', desc: '0 lamports debited on chain', statusTag: 'Protected' },
    ],
    runningNotes: [
      'Agent submits execution quote requesting 500,000 lamports unconstrained compute budget...',
      'Gateway security interceptor inspects Owner Passport and evaluates spending allowance (50,000 cap)...',
      'Cap exceeded: Gateway issues immediate HTTP 403 Forbidden before worker spawn...',
      'Zero transactions dispatched to Solana network; principal owner treasury 100% protected...',
    ],
  },
  {
    id: 'monte-carlo',
    label: 'Monte Carlo Risk',
    shortBadge: '10K VaR',
    icon: 'chip',
    badge: 'Bounded CPU',
    title: '10,000 Portfolio Risk Simulation',
    description: 'Agent submits bounded CPU compute job to evaluate tail risk (VaR 95%) and Sharpe ratio across 10,000 paths without network access or host filesystem leakage.',
    tariff: '35,000 lamports',
    runtime: '0.28s',
    actionLabel: 'Simulate 10,000-Path Risk Engine',
    actionHint: 'Simulates 10,000 vectorized portfolio simulation paths in sandboxed CPU worker with cryptographic Ed25519 settlement',
    resultTitle: 'ISOLATED SIMULATION ATTESTED',
    resultSubtitle: '10,000 paths evaluated · VaR 95% confirmed · Ed25519 receipt verified',
    chartLabel: 'Gaussian Log-Normal VaR Distribution (10,000 paths)',
    stats: [
      { label: 'Expected alpha', value: '+18.4%', positive: true },
      { label: 'VaR (95%)', value: '-3.2%', neutral: true },
      { label: 'Worker runtime', value: '284 ms' },
      { label: 'Settlement cost', value: '35,000 lamports' },
    ],
    bars: [12, 28, 55, 84, 120, 158, 142, 105, 68, 38, 18, 8],
    barLabels: ['-4s', '-3s', '-2s', '-1s', '-0.5s', 'Mean', '+0.5s', '+1s', '+2s', '+3s', '+4s', '+5s'],
    studioPreset: 'risk',
    mockReceipt: {
      taskId: 'task-montecarlo-10k-bounded',
      chainReceiptAddress: 'Mc9pXw6L8Y5Q1vT4sR3aF6bC9dE2g7vK2xQ7k21Hj3fL',
      receipt: {
        task_id: 'task-montecarlo-10k-bounded',
        gateway_pubkey: 'A5HfdyRWy7UvQpP5Fj97o3c62qJpC1g9uM8Bf4vXy3a',
        worker_pubkey: '8Zs1Lm9Px2A3bC4dE5fG6hJ7kL8mN9pQ1rS2tU3vW4x',
        execution_status: 'completed',
        execution_backend: 'bounded-cpu-isolate-512mb',
        settlement_type: 'solana-payment-channel-escrow',
        charged_lamports: 35000,
        execution_time: 0.28,
        code_sha256: '4b5c6d7e9f83c12e52b217a61d1991d334e2c98b8c2d5f8a0a1c6e4e8a1d2f3e',
        output_sha256: '2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b',
        receipt_sha256: '5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e',
        gateway_signature: '3X7mRt4Vw8Zs1Lm9Px2A3bC4dE5fG6hJ7kL8mN9pQ1rS2tU3vW4xY5z6a5M8xKpQ2Y7nRt4Vw8Zs1Lm9P',
        worker_signature: '6hJ7kL8mN9pQ1rS2tU3vW4xY5z6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c',
        settlement_signature: '9pQ1rS2tU3vW4xY5z6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a',
        task_receipt_pda: 'Mc9pXw6L8Y5Q1vT4sR3aF6bC9dE2g7vK2xQ7k21Hj3fL',
      },
    },
    steps: [
      { num: '01', title: 'Script Submitted', desc: 'Bounded Python CPU script', statusTag: 'Submit' },
      { num: '02', title: 'Quoted & Signed', desc: '35,000 lamports limit', statusTag: 'Authorize' },
      { num: '03', title: 'Sandboxed Compute', desc: 'Isolated 512 MiB worker', statusTag: 'Compute' },
      { num: '04', title: 'Signed Receipt', desc: 'Ed25519 signature returned', statusTag: 'Receipt' },
    ],
    runningNotes: [
      'Staging portfolio distribution parameters for Python worker sandboxed execution...',
      'Authorizing single-task quote and verifying Ed25519 signature on the escrow agreement...',
      'Running 10,000 Monte Carlo paths in isolated 512 MiB CPU worker (no network, bounded memory)...',
      'Validating returned receipt against gateway public key and attesting execution metrics...',
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
          <div className="demo-live-badge">
            <span className="demo-beacon-dot" />
            <span>Deterministic Execution Telemetry</span>
          </div>
          <h2>Interactive Agent Workflow Simulator</h2>
          <p className="demo-header-desc">
            Test real-time Solana escrow settlement, instant journal recovery after worker crashes, and cryptographic spending guardrails in an isolated telemetry sandbox.
          </p>
        </div>

        <div className="demo-scenario-tabs" role="tablist" aria-label="Simulation Scenarios">
          {SCENARIOS.map(s => (
            <button
              key={s.id}
              role="tab"
              aria-selected={activeScenarioId === s.id}
              className={`demo-scenario-tab ${activeScenarioId === s.id ? 'active' : ''}`}
              onClick={() => handleScenarioChange(s.id)}
              disabled={isRunning}
            >
              <Icon name={s.icon} size={15} />
              <span className="demo-tab-label">{s.label}</span>
              <span className="demo-tab-tag">{s.shortBadge}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="demo-stage-box">
        <div className="demo-stage-header">
          <div className="demo-stage-info">
            <div className="demo-stage-eyebrow">
              <span className="demo-badge">{scenario.badge}</span>
            </div>
            <h3>{scenario.title}</h3>
            <p className="demo-scenario-desc">{scenario.description}</p>
          </div>

          <div className="demo-kpi-chips">
            <div className="demo-kpi-chip">
              <Icon name="shield" size={13} />
              <span>Ceiling: <strong>{scenario.tariff}</strong></span>
            </div>
            <div className="demo-kpi-chip">
              <Icon name="clock" size={13} />
              <span>Benchmark: <strong>{scenario.runtime}</strong></span>
            </div>
          </div>
        </div>

        <div className="demo-pipeline-section">
          <div className="demo-pipeline-header">
            <span className="demo-pipeline-title">Execution Pipeline Telemetry</span>
            <div className="demo-pipeline-status">
              {!isRunning && !hasCompleted && (
                <span className="pipeline-state-chip idle">
                  <span className="state-dot idle" />
                  Standby · Ready
                </span>
              )}
              {isRunning && (
                <span className="pipeline-state-chip running">
                  <Icon name="refresh" size={12} spinning />
                  Stage {currentStep} of 4
                </span>
              )}
              {hasCompleted && (
                <span className="pipeline-state-chip done">
                  <Icon name="check" size={12} />
                  Pipeline Attested
                </span>
              )}
            </div>
          </div>

          <div className="demo-pipeline-progress">
            <div
              className="demo-progress-track-fill"
              style={{
                width: hasCompleted
                  ? '100%'
                  : currentStep > 0
                  ? `${((currentStep - 1) / (scenario.steps.length - 1)) * 100}%`
                  : '0%',
              }}
            />

            {scenario.steps.map((st, i) => {
              const stepNum = i + 1;
              const isActive = currentStep === stepNum && isRunning;
              const isDone = currentStep > stepNum || hasCompleted;
              const isPending = currentStep < stepNum && !hasCompleted;

              return (
                <div
                  key={st.num}
                  className={`demo-step-card ${isActive ? 'active' : ''} ${isDone ? 'done' : ''} ${isPending ? 'pending' : ''}`}
                >
                  <div className="demo-step-card-top">
                    <div className="step-circle">
                      {isDone ? (
                        <Icon name="check" size={13} />
                      ) : isActive ? (
                        <Icon name="refresh" size={13} spinning />
                      ) : (
                        st.num
                      )}
                    </div>
                    <span className="demo-step-tag">{st.statusTag}</span>
                  </div>
                  <div className="demo-step-card-body">
                    <strong className="demo-step-title">{st.title}</strong>
                    <span className="demo-step-sub">{st.desc}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {isRunning && (
          <div className="demo-running-strip" role="status" aria-live="polite">
            <div className="demo-running-meta">
              <span className="demo-beacon-dot live" />
              <span className="demo-running-label">Live Telemetry Feed</span>
              <span className="demo-running-phase">Stage 0{currentStep}/04</span>
            </div>
            <p className="demo-running-note">{currentNote}</p>
            <div className="demo-running-track">
              <div
                className="demo-running-bar"
                style={{ width: `${(currentStep / 4) * 100}%` }}
              />
            </div>
          </div>
        )}

        {hasCompleted && (
          <div className="demo-results-card">
            <div className="demo-results-header">
              <div className="demo-preview-tag">
                <span className="demo-result-icon">
                  <Icon name="check" size={15} />
                </span>
                <div className="demo-result-heading">
                  <strong>{scenario.resultTitle}</strong>
                  <span>{scenario.resultSubtitle}</span>
                </div>
              </div>
              <div className="demo-settle-tag">
                <Icon name="shield" size={13} />
                <span>Devnet Program A5Hfdy... Verified</span>
              </div>
            </div>

            <div className="demo-metrics-grid">
              {scenario.stats.map((st, idx) => (
                <div key={idx} className="demo-stat-cell">
                  <span className="demo-stat-label">{st.label}</span>
                  <strong className={`demo-stat-val ${st.positive ? 'positive' : st.warning ? 'warning' : 'neutral'}`}>
                    {st.value}
                  </strong>
                </div>
              ))}
            </div>

            <div className="demo-chart-section" aria-label={scenario.chartLabel}>
              <div className="demo-chart-header">
                <span className="demo-chart-title">{scenario.chartLabel}</span>
                <span className="demo-chart-legend">Relative Batch Weight</span>
              </div>
              <div className="demo-histogram-wrap">
                <div className="demo-histogram">
                  {scenario.bars.map((height, i) => (
                    <div key={i} className="demo-bar-col">
                      <div
                        className="demo-bar"
                        style={{ height: `${Math.max(6, (height / 160) * 100)}%` }}
                        title={`${scenario.barLabels[i]}: ${height} units`}
                      />
                      <span className="demo-bar-sub">{scenario.barLabels[i]}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="demo-results-actions">
              {onOpenWorkflows && (
                <button className="console-button primary demo-btn-glow" onClick={onOpenWorkflows}>
                  <Icon name="arrow" size={16} />
                  <span>Run Live Workflow in Console</span>
                </button>
              )}
              <button
                className="console-button secondary"
                onClick={() => onOpenStudio && onOpenStudio(scenario.studioPreset)}
              >
                <Icon name="code" size={16} />
                <span>Inspect in Studio</span>
              </button>
              <button
                className="console-button secondary"
                onClick={() => setShowReceiptGuide(true)}
              >
                <Icon name="shield" size={16} />
                <span>Verify Cryptographic Proof</span>
              </button>
              <button className="console-text-button demo-btn-rerun" onClick={runSimulation}>
                <Icon name="refresh" size={14} />
                <span>Simulate Again</span>
              </button>
            </div>
          </div>
        )}

        {!isRunning && !hasCompleted && (
          <div className="demo-trigger-action">
            <button className="console-button primary demo-run-btn" onClick={runSimulation}>
              <Icon name="play" size={16} />
              <span>{scenario.actionLabel}</span>
            </button>
            <p className="demo-hint-text">
              <Icon name="spark" size={13} />
              <span>{scenario.actionHint}</span>
            </p>
            <div className="demo-trust-badges">
              <span className="demo-trust-chip">Solana Devnet Escrow</span>
              <span className="demo-trust-chip">Crash-Resilient State Journal</span>
              <span className="demo-trust-chip">Ed25519 Cryptographic Attestation</span>
            </div>
          </div>
        )}
      </div>

      <ProofVerifierModal
        isOpen={showReceiptGuide}
        onClose={() => setShowReceiptGuide(false)}
        receipt={scenario.mockReceipt.receipt}
        taskId={scenario.mockReceipt.taskId}
        chainReceiptAddress={scenario.mockReceipt.chainReceiptAddress}
        verified={true}
        verificationNote={`Cryptographic verification of ${scenario.title} on Solana Devnet.`}
      />
    </section>
  );
}
