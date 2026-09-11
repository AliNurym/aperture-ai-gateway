import React, { useState, useEffect, useRef } from 'react';

const STAGES = [
  {
    id: 1,
    title: "Web3 Auth & PDA Escrow",
    shortTitle: "01. Web3 Escrow",
    icon: "account_balance_wallet",
    color: "#2563eb",
    bgTint: "rgba(37, 99, 235, 0.08)",
    badge: "STAGE 01 &bull; CRYPTOGRAPHIC LOCK",
    tagline: "Ed25519 signature authentication & state channel PDA initialization",
    summary: "User authenticates with Phantom/Solflare and locks micro-SOL into an Anchor smart contract PDA ([b\"channel\", user.key()]). Zero custodial risk—unspent funds remain refundable at any moment.",
    codeSnippet: `# 1. Initialize Solana State Channel PDA
pda, bump = Pubkey.find_program_address(
    [b"channel", bytes(user_pubkey)], 
    PROGRAM_ID
)
# CPI Lock: Micro-streaming fuel tank
await program.rpc.open_channel(
    initial_deposit=500_000_000, # 0.5 SOL
    accounts={"channel": pda, "user": user_pubkey}
)`,
    metrics: [
      { label: "Channel Architecture", val: "PDA State Channel" },
      { label: "Authentication", val: "Ed25519 Solana Signature" },
      { label: "Custody Model", val: "Non-Custodial Escrow" }
    ],
    visualState: {
      statusText: "CHANNEL PDA ACTIVE",
      statusColor: "#2563eb",
      highlightLine: "escrow_locked",
      badgeText: "Solana Devnet: Escrow Initialized"
    }
  },
  {
    id: 2,
    title: "AI Sentinel AST Security & Complexity",
    shortTitle: "02. AST Audit",
    icon: "policy",
    color: "#059669",
    bgTint: "rgba(5, 150, 105, 0.08)",
    badge: "STAGE 02 &bull; PRE-FLIGHT AUDIT",
    tagline: "Deterministic static Abstract Syntax Tree (AST) inspection in <1ms",
    summary: "Before any code touches physical silicon, AI Sentinel traverses Python bytecode syntax nodes. Dangerous syscalls (os.system, subprocess, socket) are intercepted immediately, while loop nesting depth and tensor arithmetic dictate algorithmic intensity.",
    codeSnippet: `# 2. Deterministic AST Security & Complexity Walker
class CodeComplexityVisitor(ast.NodeVisitor):
    def visit_For(self, node):
        self.loop_depth += 1 # Exponential complexity
        self.generic_visit(node)
        
    def visit_Import(self, node):
        for name in node.names:
            if name.name in DANGEROUS_MODULES:
                raise SecurityViolation("Restricted syscall banned")`,
    metrics: [
      { label: "Audit Latency", val: "<0.8ms Static Scan" },
      { label: "Sandbox Security", val: "Banned Syscall Shield" },
      { label: "Complexity Score", val: "Calculated: 74 / 100" }
    ],
    visualState: {
      statusText: "AST AUDIT: 100% VERIFIED CLEAN",
      statusColor: "#059669",
      highlightLine: "ast_clean",
      badgeText: "Threat Vector: 0 Blocked / Safe"
    }
  },
  {
    id: 3,
    title: "Pyth Hermes Dynamic Burn Rate",
    shortTitle: "03. Dynamic Price",
    icon: "candlestick_chart",
    color: "#7c3aed",
    bgTint: "rgba(124, 58, 237, 0.08)",
    badge: "STAGE 03 &bull; REAL-TIME ORACLE",
    tagline: "Sub-second SOL/USD price feed calibrates dynamic Lamport micro-streaming",
    summary: "Aperture's dynamic pricing algorithm queries the Pyth Network Hermes sub-second price feed. Algorithmic complexity is mapped against live Solana market rates to establish an exact burn rate in Lamports per second (e.g. 1,490 Lamports/sec ≈ $0.0014/hr).",
    codeSnippet: `# 3. Pyth Hermes Oracle Price Calibration
sol_usd = pyth_hermes.get_price("SOL/USD") # $99.81
base_rate = 0.00000150 # SOL/sec

# Robin Hood complexity curve:
burn_rate_sol = (base_rate * (complexity / 30.0)) / hw_power
burn_rate_lamports = int(burn_rate_sol * 1_000_000_000)

# Modulate Smart Contract On-Chain Burn Rate
await program.rpc.update_burn_rate(burn_rate_lamports)`,
    metrics: [
      { label: "Oracle Feed", val: "Pyth Network Hermes" },
      { label: "Dynamic Rate", val: "1,490 Lamports / sec" },
      { label: "Hourly Cost", val: "~$0.0014 / Hour" }
    ],
    visualState: {
      statusText: "BURN RATE APPLIED: 1,490 L/s",
      statusColor: "#7c3aed",
      highlightLine: "rate_updated",
      badgeText: "Pyth Hermes: $99.81 USD"
    }
  },
  {
    id: 4,
    title: "NVIDIA Silicon Hardware Execution",
    shortTitle: "04. GPU Compute",
    icon: "memory",
    color: "#2563eb",
    bgTint: "rgba(37, 99, 235, 0.08)",
    badge: "STAGE 04 &bull; PHYSICAL HARDWARE",
    tagline: "Subprocess dispatch to bare-metal NVIDIA RTX 3050 GPU with live stdout",
    summary: "Audited workloads are pulled FIFO by verified worker daemons. The Python payload executes on physical GPU silicon with real-time NVML telemetry (temperature, utilization %, VRAM) and streaming stdout lines sent back to the user terminal every 300ms.",
    codeSnippet: `# 4. Physical GPU Execution & NVML Monitoring
nvmlInit()
handle = nvmlDeviceGetHandleByIndex(0)
temp = nvmlDeviceGetTemperature(handle, 0) # 50.0°C
util = nvmlDeviceGetUtilizationRates(handle).gpu # 88%

# Isolated subprocess execution + stdout streaming
proc = subprocess.Popen([sys.executable, task_file], stdout=PIPE)
for line in iter(proc.stdout.readline, ''):
    stream_chunk_to_gateway(task_id, line)`,
    metrics: [
      { label: "Executing Hardware", val: "NVIDIA RTX 3050 4GB" },
      { label: "Silicon Temp", val: "50.0°C (Direct NVML)" },
      { label: "Streaming Latency", val: "~300ms Live Telemetry" }
    ],
    visualState: {
      statusText: "EXECUTING ON SILICON: 12.0 TFLOPS",
      statusColor: "#2563eb",
      highlightLine: "gpu_active",
      badgeText: "NODE-HOST-GPU-01 (RTX 3050)"
    }
  },
  {
    id: 5,
    title: "Autonomous On-Chain Settlement & NFT",
    shortTitle: "05. Settlement",
    icon: "verified",
    color: "#059669",
    bgTint: "rgba(5, 150, 105, 0.08)",
    badge: "STAGE 05 &bull; SOLANA DEVNET FINALITY",
    tagline: "Cryptographic escrow settlement, burn reset, and compressed receipt NFT",
    summary: "Upon completion, the exact execution duration is submitted to the smart contract. Burn rate is reset to zero, unspent funds remain safely in the user's PDA, and a Metaplex Bubblegum compressed NFT compute receipt is minted with cryptographic proof.",
    codeSnippet: `# 5. Smart Contract Settlement & NFT Receipt
final_cost = execution_time * burn_rate_sol
# Reset burn rate to 0 immediately
await program.rpc.update_burn_rate(new_rate=0)

# Mint Verifiable Bubblegum Compressed NFT Receipt
tx_sig = await helius_rpc.mint_compressed_nft({
    "name": f"Aperture Task {task_id[-6:].upper()}",
    "attributes": [
        {"trait_type": "Duration", "value": f"{duration:.2f}s"},
        {"trait_type": "Cost_Lamports", "value": f"{lamports_burned}"}
    ]
})`,
    metrics: [
      { label: "Solana Finality", val: "~400ms Confirmation" },
      { label: "Receipt Standard", val: "Bubblegum Compressed NFT" },
      { label: "Idle Overhead", val: "$0.00 (Zero Idle Waste)" }
    ],
    visualState: {
      statusText: "SETTLED ON SOLANA DEVNET",
      statusColor: "#059669",
      highlightLine: "settlement_done",
      badgeText: "Transaction Confirmed: 4qA2...URYX"
    }
  }
];

export default function HowItWorks({ onLaunchStudio }) {
  const [activeStageIdx, setActiveStageIdx] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [progressPercent, setProgressPercent] = useState(0);
  const timerRef = useRef(null);
  const progressIntervalRef = useRef(null);

  const stage = STAGES[activeStageIdx];
  const STAGE_DURATION_MS = 5000;
  const UPDATE_FREQ_MS = 50;

  // Auto-play progress bar and step transition
  useEffect(() => {
    if (!isPlaying) {
      if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
      return;
    }

    let elapsed = 0;
    setProgressPercent(0);

    progressIntervalRef.current = setInterval(() => {
      elapsed += UPDATE_FREQ_MS;
      const pct = Math.min(100, (elapsed / STAGE_DURATION_MS) * 100);
      setProgressPercent(pct);

      if (elapsed >= STAGE_DURATION_MS) {
        elapsed = 0;
        setActiveStageIdx(prev => (prev + 1) % STAGES.length);
      }
    }, UPDATE_FREQ_MS);

    return () => {
      if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
    };
  }, [isPlaying, activeStageIdx]);

  const handleStageSelect = (idx) => {
    setActiveStageIdx(idx);
    setProgressPercent(0);
  };

  const handlePrev = () => {
    setActiveStageIdx(prev => (prev - 1 + STAGES.length) % STAGES.length);
    setProgressPercent(0);
  };

  const handleNext = () => {
    setActiveStageIdx(prev => (prev + 1) % STAGES.length);
    setProgressPercent(0);
  };

  return (
    <div className="aperture-how-it-works-section m3-anim-2" style={{ marginTop: '48px', marginBottom: '48px' }}>
      
      {/* Section Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: '16px', marginBottom: '24px' }}>
        <div>
          <div className="aperture-announcement-pill" style={{ marginBottom: '10px' }}>
            <span className="aperture-status-dot"></span>
            <span>INTERACTIVE PROTOCOL DEMONSTRATION &bull; AUTONOMOUS LIFECYCLE</span>
          </div>
          <h2 style={{ fontSize: '28px', fontWeight: '800', color: 'var(--m3-text-primary)', margin: '0 0 6px 0', letterSpacing: '-0.02em' }}>
            How Aperture DePIN Executes in 400ms Slots
          </h2>
          <p style={{ color: 'var(--m3-text-secondary)', fontSize: '14.5px', margin: 0, maxWidth: '680px' }}>
            Watch the live 5-stage interactive demonstration below showing how Python AI workloads are audited, priced, dispatched to physical silicon, and settled on Solana Devnet.
          </p>
        </div>

        {/* Playback Controls & Studio CTA */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', background: '#f8fafc', border: '1px solid var(--m3-border)', borderRadius: 'var(--m3-radius-pill)', padding: '4px 8px', gap: '4px' }}>
            <button
              onClick={handlePrev}
              style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: '6px', color: 'var(--m3-text-secondary)' }}
              title="Previous Stage"
            >
              <span className="material-symbols-rounded" style={{ fontSize: '18px' }}>skip_previous</span>
            </button>

            <button
              onClick={() => setIsPlaying(!isPlaying)}
              style={{
                background: isPlaying ? 'var(--m3-surface)' : 'var(--m3-primary)',
                color: isPlaying ? 'var(--m3-text-primary)' : '#ffffff',
                border: '1px solid var(--m3-border)',
                borderRadius: 'var(--m3-radius-pill)',
                padding: '6px 14px',
                fontSize: '12.5px',
                fontWeight: '700',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <span className="material-symbols-rounded" style={{ fontSize: '16px' }}>
                {isPlaying ? 'pause' : 'play_arrow'}
              </span>
              {isPlaying ? 'Pause' : 'Auto-Play'}
            </button>

            <button
              onClick={handleNext}
              style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: '6px', color: 'var(--m3-text-secondary)' }}
              title="Next Stage"
            >
              <span className="material-symbols-rounded" style={{ fontSize: '18px' }}>skip_next</span>
            </button>
          </div>

          {onLaunchStudio && (
            <button
              onClick={onLaunchStudio}
              className="m3-btn-primary"
              style={{ height: '40px', padding: '0 18px', fontSize: '13px' }}
            >
              Try in Studio →
            </button>
          )}
        </div>
      </div>

      {/* Stage Step Track Tabs with Dynamic Progress Fill */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px', marginBottom: '20px' }}>
        {STAGES.map((s, idx) => {
          const isActive = idx === activeStageIdx;
          const isPassed = idx < activeStageIdx;
          return (
            <button
              key={s.id}
              onClick={() => handleStageSelect(idx)}
              style={{
                background: isActive ? '#ffffff' : (isPassed ? '#f8fafc' : '#ffffff'),
                border: `1.5px solid ${isActive ? s.color : 'var(--m3-border)'}`,
                borderRadius: 'var(--m3-radius-lg)',
                padding: '12px 14px',
                textAlign: 'left',
                cursor: 'pointer',
                position: 'relative',
                overflow: 'hidden',
                boxShadow: isActive ? 'var(--m3-elevation-2)' : 'none',
                transition: 'all 0.25s var(--m3-motion-emphasized)'
              }}
            >
              {/* Dynamic Animated Progress Fill Bar */}
              {isActive && (
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    height: '3px',
                    width: `${progressPercent}%`,
                    background: s.color,
                    transition: 'width 0.05s linear'
                  }}
                />
              )}

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{
                  fontSize: '10px',
                  fontWeight: '800',
                  color: isActive ? s.color : 'var(--m3-text-muted)',
                  letterSpacing: '0.05em'
                }}>
                  STEP 0{s.id}
                </span>
                <span
                  className="material-symbols-rounded"
                  style={{ fontSize: '16px', color: isActive ? s.color : 'var(--m3-text-muted)' }}
                >
                  {s.icon}
                </span>
              </div>
              
              <div style={{
                fontSize: '12.5px',
                fontWeight: isActive ? '800' : '600',
                color: isActive ? 'var(--m3-text-primary)' : 'var(--m3-text-secondary)',
                lineHeight: '1.3'
              }}>
                {s.shortTitle.split('. ')[1]}
              </div>
            </button>
          );
        })}
      </div>

      {/* Main Interactive Stage Display Container */}
      <div style={{
        background: '#ffffff',
        border: '1px solid var(--m3-border)',
        borderRadius: 'var(--m3-radius-2xl)',
        boxShadow: 'var(--m3-elevation-3)',
        overflow: 'hidden',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))'
      }}>

        {/* Left Panel: Detailed Architectural Explanation */}
        <div style={{ padding: '36px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
              <span
                className="m3-badge"
                style={{
                  background: stage.bgTint,
                  color: stage.color,
                  border: `1px solid ${stage.color}40`,
                  fontSize: '11px',
                  fontWeight: '800'
                }}
              >
                <span className="aperture-status-dot" style={{ background: stage.color }}></span>
                {stage.badge}
              </span>
              <span style={{ fontSize: '12px', color: 'var(--m3-text-muted)' }}>
                Stage {stage.id} of 5
              </span>
            </div>

            <h3 style={{ fontSize: '24px', fontWeight: '800', color: 'var(--m3-text-primary)', margin: '0 0 10px 0', letterSpacing: '-0.02em' }}>
              {stage.title}
            </h3>

            <p style={{ fontSize: '13.5px', fontWeight: '600', color: stage.color, marginBottom: '14px' }}>
              {stage.tagline}
            </p>

            <p style={{ fontSize: '14px', color: 'var(--m3-text-secondary)', lineHeight: '1.65', marginBottom: '24px' }}>
              {stage.summary}
            </p>

            {/* Stage Metrics Chips */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', marginBottom: '20px' }}>
              {stage.metrics.map((m, i) => (
                <div
                  key={i}
                  style={{
                    background: '#f8fafc',
                    border: '1px solid var(--m3-border)',
                    borderRadius: 'var(--m3-radius-md)',
                    padding: '10px 12px'
                  }}
                >
                  <div style={{ fontSize: '10.5px', fontWeight: '700', color: 'var(--m3-text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>
                    {m.label}
                  </div>
                  <div style={{ fontSize: '12.5px', fontWeight: '800', color: 'var(--m3-text-primary)', fontFamily: 'monospace' }}>
                    {m.val}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Stage Action Pill */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid var(--m3-border)', paddingTop: '18px' }}>
            <span style={{ fontSize: '12.5px', color: 'var(--m3-text-muted)' }}>
              Auto-advancing in {Math.ceil((STAGE_DURATION_MS * (100 - progressPercent)) / 100000)}s...
            </span>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={handlePrev}
                className="m3-btn-secondary"
                style={{ height: '34px', padding: '0 12px', fontSize: '12px' }}
              >
                ← Prev
              </button>
              <button
                onClick={handleNext}
                className="m3-btn-primary"
                style={{ height: '34px', padding: '0 14px', fontSize: '12px' }}
              >
                Next Step →
              </button>
            </div>
          </div>
        </div>

        {/* Right Panel: Simulated Live Silicon & Blockchain Console */}
        <div style={{
          background: '#090d16',
          borderLeft: '1px solid var(--m3-border)',
          padding: '24px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          color: '#f8fafc'
        }}>
          
          {/* Mock Window Header */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', paddingBottom: '12px', borderBottom: '1px solid #1e293b' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#ef4444' }}></span>
                <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#eab308' }}></span>
                <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#22c55e' }}></span>
                <span style={{ fontSize: '12px', fontFamily: 'monospace', color: '#94a3b8', marginLeft: '6px' }}>
                  aperture_protocol_v1.0 &bull; stage_0{stage.id}.py
                </span>
              </div>

              <span
                style={{
                  fontSize: '11px',
                  fontFamily: 'monospace',
                  fontWeight: '700',
                  padding: '3px 10px',
                  borderRadius: 'var(--m3-radius-pill)',
                  background: 'rgba(255, 255, 255, 0.08)',
                  color: stage.visualState.statusColor,
                  border: `1px solid ${stage.visualState.statusColor}40`
                }}
              >
                ● {stage.visualState.statusText}
              </span>
            </div>

            {/* Code / Logic Canvas */}
            <div style={{
              background: '#040711',
              borderRadius: 'var(--m3-radius-lg)',
              padding: '16px',
              border: '1px solid #1e293b',
              fontFamily: 'monospace',
              fontSize: '12.5px',
              lineHeight: '1.6',
              color: '#e2e8f0',
              overflowX: 'auto',
              marginBottom: '16px'
            }}>
              <pre style={{ margin: 0 }}>
                <code>{stage.codeSnippet}</code>
              </pre>
            </div>
          </div>

          {/* Dynamic Live Telemetry Status Bar */}
          <div style={{
            background: '#0e1526',
            borderRadius: 'var(--m3-radius-md)',
            padding: '14px 16px',
            border: '1px solid #1e293b',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '8px',
            fontSize: '12px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="aperture-status-dot" style={{ background: stage.visualState.statusColor }}></span>
              <span style={{ color: '#cbd5e1' }}>{stage.visualState.badgeText}</span>
            </div>

            <span style={{ color: '#64748b', fontFamily: 'monospace' }}>
              Slot Time: 400ms &bull; Zero Custody
            </span>
          </div>

        </div>

      </div>

    </div>
  );
}
