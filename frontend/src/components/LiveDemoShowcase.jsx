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
    auditBadge: 'Crash Resilient · 0 Duplicates',
    auditTrail: [
      {
        step: '01',
        label: 'Dataset Staging & Partition',
        detail: '17,000 synthetic rows partitioned into 12 batches with SHA-256 integrity check.',
        status: 'passed',
        statusLabel: 'Staged',
      },
      {
        step: '02',
        label: 'Synthetic Interruption',
        detail: 'Process halted at Step 1. State snapshot and row offset committed to on-disk journal.',
        status: 'warning',
        statusLabel: 'Interrupted',
      },
      {
        step: '03',
        label: 'Journal Resumption',
        detail: 'Resumed in 18ms from journal. Exactly 0 duplicate rows executed, 0 extra lamports spent.',
        status: 'passed',
        statusLabel: 'Recovered',
      },
      {
        step: '04',
        label: 'Consensus & Output Hash',
        detail: 'Output hashes compared byte-for-byte against pre-crash baseline. Ed25519 receipt attested.',
        status: 'passed',
        statusLabel: 'Verified',
      },
    ],
    artifacts: [
      {
        icon: 'code',
        name: 'report.json',
        size: '48.2 KB',
        description: '16,983 valid rows aggregated',
        tag: 'SHA-256 Validated',
      },
      {
        icon: 'grid',
        name: 'categories.csv',
        size: '128.4 KB',
        description: '12 partitioned categories',
        tag: '100% Parsed',
      },
      {
        icon: 'shield',
        name: 'receipt.pda',
        size: '64 B',
        description: 'Solana Devnet escrow receipt',
        tag: 'Ed25519 Signed',
      },
    ],
    stats: [
      { label: 'Accepted rows', value: '16,983 (17 invalid)', positive: true },
      { label: 'Crash resilience', value: '0 duplicate tasks', positive: true },
      { label: 'Capital loss', value: '0 lamports (Protected)', positive: true },
      { label: 'Verified output', value: 'report.json · categories.csv', neutral: true },
    ],
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
    auditBadge: 'HTTP 403 · Treasury Safe',
    auditTrail: [
      {
        step: '01',
        label: 'Agent Task Request',
        detail: 'Agent submitted workload requesting 500,000 lamports unconstrained execution.',
        status: 'neutral',
        statusLabel: 'Received',
      },
      {
        step: '02',
        label: 'Policy Gatekeeper Check',
        detail: 'Gateway checked Owner Passport policy. Maximum authorized limit is 50,000 lamports.',
        status: 'warning',
        statusLabel: 'Exceeded',
      },
      {
        step: '03',
        label: 'Pre-flight Halt',
        detail: 'Request intercepted with HTTP 403 Forbidden before worker process was instantiated.',
        status: 'passed',
        statusLabel: 'Halted',
      },
      {
        step: '04',
        label: 'Zero Treasury Impact',
        detail: 'Zero on-chain transactions broadcasted to Solana network. 0 lamports debited.',
        status: 'passed',
        statusLabel: 'Protected',
      },
    ],
    artifacts: [
      {
        icon: 'shield',
        name: 'policy_verdict.json',
        size: '1.2 KB',
        description: 'HTTP 403 Forbidden',
        tag: 'Policy Enforced',
      },
      {
        icon: 'code',
        name: 'security_audit.log',
        size: '3.4 KB',
        description: '0 lamports spent',
        tag: 'Treasury Safe',
      },
      {
        icon: 'wallet',
        name: 'passport_state.pda',
        size: '32 B',
        description: 'Allowance intact (50k)',
        tag: 'Balance Preserved',
      },
    ],
    stats: [
      { label: 'Requested budget', value: '500,000 lamports' },
      { label: 'Owner allowance', value: '50,000 lamports' },
      { label: 'Gateway verdict', value: '403 Forbidden', warning: true },
      { label: 'Capital loss', value: '0 lamports (Protected)', positive: true },
    ],
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
    auditBadge: '10k Paths · Sandboxed',
    auditTrail: [
      {
        step: '01',
        label: 'Parameter Vector Staging',
        detail: '10,000 portfolio distributions staged into isolated 512 MiB CPU worker.',
        status: 'neutral',
        statusLabel: 'Staged',
      },
      {
        step: '02',
        label: 'Sandboxed Compute',
        detail: 'Vectorized Monte Carlo loop evaluated in 284ms with 0 network and 0 disk leakage.',
        status: 'passed',
        statusLabel: 'Executed',
      },
      {
        step: '03',
        label: 'Risk Boundary Metric',
        detail: 'Tail loss VaR (95%) calculated at -3.2%; Sharpe ratio at 2.14; alpha at +18.4%.',
        status: 'passed',
        statusLabel: 'Evaluated',
      },
      {
        step: '04',
        label: 'Ed25519 Settlement Receipt',
        detail: 'Gateway validated worker cryptographic signature; 35,000 lamports released.',
        status: 'passed',
        statusLabel: 'Signed',
      },
    ],
    artifacts: [
      {
        icon: 'code',
        name: 'var_distribution.json',
        size: '38.6 KB',
        description: '10,000 vector paths',
        tag: 'VaR 95% Confirmed',
      },
      {
        icon: 'grid',
        name: 'risk_metrics.csv',
        size: '14.2 KB',
        description: 'Sharpe 2.14, Alpha 18.4%',
        tag: 'Risk Attested',
      },
      {
        icon: 'shield',
        name: 'receipt.pda',
        size: '64 B',
        description: '35k lamports settlement',
        tag: 'Ed25519 Signed',
      },
    ],
    stats: [
      { label: 'Expected alpha', value: '+18.4%', positive: true },
      { label: 'VaR (95%)', value: '-3.2%', neutral: true },
      { label: 'Worker runtime', value: '284 ms' },
      { label: 'Settlement cost', value: '35,000 lamports' },
    ],
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

            <div className="demo-audit-section">
              <div className="demo-audit-header">
                <div className="demo-audit-title-wrap">
                  <Icon name="spark" size={14} />
                  <span>Execution Audit Trail & Verified Artifacts</span>
                </div>
                <span className="demo-audit-badge">
                  <span className="demo-beacon-dot" />
                  {scenario.auditBadge}
                </span>
              </div>

              <div className="demo-audit-grid">
                <div className="demo-audit-trail">
                  <div className="demo-audit-subhead">State Journal Timeline</div>
                  <div className="demo-timeline-track">
                    {scenario.auditTrail.map((item, idx) => (
                      <div key={idx} className={`demo-timeline-item ${item.status}`}>
                        <div className="demo-timeline-node">
                          <span className="demo-node-dot" />
                          {idx < scenario.auditTrail.length - 1 && <span className="demo-node-line" />}
                        </div>
                        <div className="demo-timeline-content">
                          <div className="demo-timeline-row">
                            <strong className="demo-timeline-label">{item.label}</strong>
                            <span className={`demo-timeline-tag ${item.status}`}>{item.statusLabel}</span>
                          </div>
                          <p className="demo-timeline-detail">{item.detail}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="demo-artifacts-wrap">
                  <div className="demo-audit-subhead">Attested Output Artifacts</div>
                  <div className="demo-artifacts-list">
                    {scenario.artifacts.map((art, idx) => (
                      <div key={idx} className="demo-artifact-card">
                        <div className="demo-artifact-icon">
                          <Icon name={art.icon} size={16} />
                        </div>
                        <div className="demo-artifact-info">
                          <div className="demo-artifact-top">
                            <strong className="demo-artifact-name">{art.name}</strong>
                            <span className="demo-artifact-size">{art.size}</span>
                          </div>
                          <span className="demo-artifact-desc">{art.description}</span>
                        </div>
                        <span className="demo-artifact-tag">{art.tag}</span>
                      </div>
                    ))}
                  </div>
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
