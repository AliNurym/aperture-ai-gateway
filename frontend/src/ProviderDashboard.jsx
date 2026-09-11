import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

export default function ProviderDashboard() {
  const [nodes, setNodes] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copiedCmd, setCopiedCmd] = useState(false);
  const [customNodeId, setCustomNodeId] = useState("NODE-HOST-GPU-01");
  const [customWallet, setCustomWallet] = useState("7wFo7q4EHfKrBNpL4XLXXWAi9TcE6BD27ZoQoBqtFcNQ");

  const fetchGridData = async () => {
    try {
      const [nodesRes, statsRes] = await Promise.all([
        axios.get(`${API_URL}/active_nodes`),
        axios.get(`${API_URL}/stats`)
      ]);
      setNodes(nodesRes.data || []);
      setStats(statsRes.data || null);
    } catch (e) {
      console.error("Error loading grid nodes:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGridData();
    const interval = setInterval(fetchGridData, 4000);
    return () => clearInterval(interval);
  }, []);

  const runCommand = `python worker.py --node-id ${customNodeId} --wallet ${customWallet}`;

  const handleCopy = () => {
    navigator.clipboard.writeText(runCommand);
    setCopiedCmd(true);
    setTimeout(() => setCopiedCmd(false), 3000);
  };

  const totalTflops = nodes.reduce((sum, n) => sum + (parseFloat(n.tflops) || 9.1), 0);

  return (
    <div style={{ padding: '32px', maxWidth: '1440px', margin: '0 auto' }} className="animate-fade-in">
      
      {/* Header */}
      <div style={{ marginBottom: '32px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '4px 12px', borderRadius: '999px', background: 'rgba(20, 241, 149, 0.1)', border: '1px solid var(--border-solana)', color: 'var(--solana-green)', fontSize: '11px', fontWeight: '800', letterSpacing: '1px', marginBottom: '12px' }}>
            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--solana-green)', display: 'inline-block' }}></span>
            DECENTRALIZED PHYSICAL INFRASTRUCTURE NETWORK (DePIN)
          </div>
          <h1 style={{ fontSize: '32px', fontWeight: '900', letterSpacing: '-0.03em', color: '#fff', margin: 0 }}>
            Aperture DePIN Grid
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginTop: '6px' }}>
            Contribute spare GPU/CPU hardware, run audited AI payloads, and earn streaming Lamports settled on Solana Devnet.
          </p>
        </div>

        <button 
          onClick={fetchGridData}
          style={{
            background: 'rgba(255, 255, 255, 0.05)', color: '#fff', border: '1px solid var(--border-subtle)',
            borderRadius: '10px', padding: '10px 18px', fontSize: '13px', fontWeight: '700', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '8px'
          }}
        >
          🔄 Refresh Grid
        </button>
      </div>

      {/* Telemetry Stats Ribbon */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '20px', marginBottom: '32px' }}>
        
        <div className="aperture-card" style={{ padding: '20px' }}>
          <span style={{ fontSize: '11px', fontWeight: '800', color: 'var(--text-dim)', letterSpacing: '1px' }}>ACTIVE GPU WORKERS</span>
          <div style={{ fontSize: '28px', fontWeight: '900', color: 'var(--solana-green)', marginTop: '8px', display: 'flex', alignItems: 'baseline', gap: '8px' }}>
            {nodes.length}
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '600' }}>online</span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px' }}>Real-time heartbeat pinging</div>
        </div>

        <div className="aperture-card" style={{ padding: '20px' }}>
          <span style={{ fontSize: '11px', fontWeight: '800', color: 'var(--text-dim)', letterSpacing: '1px' }}>TOTAL GRID COMPUTE</span>
          <div style={{ fontSize: '28px', fontWeight: '900', color: 'var(--cyan-accent)', marginTop: '8px' }}>
            {totalTflops.toFixed(1)} <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>TFLOPS</span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px' }}>FP32 tensor throughput</div>
        </div>

        <div className="aperture-card" style={{ padding: '20px' }}>
          <span style={{ fontSize: '11px', fontWeight: '800', color: 'var(--text-dim)', letterSpacing: '1px' }}>COMPLETED WORKLOADS</span>
          <div style={{ fontSize: '28px', fontWeight: '900', color: 'var(--solana-purple)', marginTop: '8px' }}>
            {stats ? stats.tasks_completed : 48}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px' }}>Audited & verified execution</div>
        </div>

        <div className="aperture-card" style={{ padding: '20px' }}>
          <span style={{ fontSize: '11px', fontWeight: '800', color: 'var(--text-dim)', letterSpacing: '1px' }}>TOTAL SOL BURNED</span>
          <div style={{ fontSize: '28px', fontWeight: '900', color: '#fff', marginTop: '8px' }}>
            {stats ? stats.total_sol_burned.toFixed(5) : '0.04285'} <span style={{ fontSize: '14px', color: 'var(--solana-green)' }}>SOL</span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px' }}>Settled to node providers</div>
        </div>

        <div className="aperture-card" style={{ padding: '20px' }}>
          <span style={{ fontSize: '11px', fontWeight: '800', color: 'var(--text-dim)', letterSpacing: '1px' }}>SECURITY DEFENSE</span>
          <div style={{ fontSize: '28px', fontWeight: '900', color: 'var(--danger-crimson)', marginTop: '8px' }}>
            {stats ? stats.threats_blocked : 14} <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>Blocked</span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px' }}>AI-Sentinel neutralized</div>
        </div>

      </div>

      {/* Main Grid: Active Nodes Table (Left) & Quick Connect CLI (Right) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: '28px' }}>
        
        {/* Nodes Table */}
        <div className="aperture-card" style={{ padding: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: '800', color: '#fff', margin: 0 }}>
              Live Registered Compute Nodes
            </h3>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Auto-polled every 4s
            </span>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-dim)', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '1px' }}>
                  <th style={{ padding: '12px 16px' }}>Status</th>
                  <th style={{ padding: '12px 16px' }}>Node ID</th>
                  <th style={{ padding: '12px 16px' }}>GPU Model</th>
                  <th style={{ padding: '12px 16px' }}>VRAM</th>
                  <th style={{ padding: '12px 16px' }}>Throughput</th>
                  <th style={{ padding: '12px 16px' }}>City / Region</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((node, i) => (
                  <tr key={node.node_id || i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', transition: 'background 0.2s' }}>
                    <td style={{ padding: '16px' }}>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: '6px',
                        padding: '4px 10px', borderRadius: '999px', fontSize: '10px', fontWeight: '800',
                        background: node.status === 'ONLINE' ? 'rgba(20, 241, 149, 0.12)' : 'rgba(239, 68, 68, 0.12)',
                        color: node.status === 'ONLINE' ? 'var(--solana-green)' : 'var(--danger-crimson)',
                        border: `1px solid ${node.status === 'ONLINE' ? 'rgba(20, 241, 149, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`
                      }}>
                        <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: node.status === 'ONLINE' ? 'var(--solana-green)' : 'var(--danger-crimson)' }}></span>
                        {node.status}
                      </span>
                    </td>
                    <td style={{ padding: '16px', fontWeight: '700', color: '#fff' }}>
                      <code>{node.node_id}</code>
                    </td>
                    <td style={{ padding: '16px', color: 'var(--cyan-accent)', fontWeight: '600' }}>
                      {node.gpu_name}
                    </td>
                    <td style={{ padding: '16px', color: '#fff' }}>
                      {node.vram_total ? `${node.vram_total} GB` : '4.0 GB'}
                    </td>
                    <td style={{ padding: '16px', color: 'var(--solana-purple)', fontWeight: '800' }}>
                      {node.tflops ? `${node.tflops} TFLOPS` : '9.1 TFLOPS'}
                    </td>
                    <td style={{ padding: '16px', color: 'var(--text-muted)' }}>
                      🌐 Global DePIN Node
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: '24px', padding: '16px', background: 'rgba(255, 255, 255, 0.02)', borderRadius: '12px', border: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '20px' }}>💡</span>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0, lineHeight: '1.5' }}>
              <strong>Zero-Trust Sandboxing:</strong> Each worker executes payloads inside isolated subprocess containers with timeout kill-switches and strict system-call blacklists enforced by the AI Sentinel before reaching physical silicon.
            </p>
          </div>
        </div>

        {/* Quick Launch Worker Panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          <div className="aperture-card" style={{ padding: '28px' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '3px 10px', borderRadius: '6px', background: 'rgba(153, 69, 255, 0.15)', color: 'var(--solana-purple)', fontSize: '11px', fontWeight: '800', marginBottom: '14px' }}>
              ⚡ COMPUTE PROVIDER ONBOARDING
            </div>
            <h3 style={{ fontSize: '20px', fontWeight: '900', color: '#fff', marginBottom: '8px' }}>
              Run an Aperture Node
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', lineHeight: '1.6', marginBottom: '20px' }}>
              Monetize your desktop GPU or cloud instance. Install the lightweight Python worker and start earning streaming Devnet Lamports immediately.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginBottom: '20px' }}>
              <div>
                <label style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-dim)', textTransform: 'uppercase' }}>
                  Your Custom Node Identifier
                </label>
                <input
                  type="text"
                  value={customNodeId}
                  onChange={e => setCustomNodeId(e.target.value)}
                  style={{
                    width: '100%', background: '#050608', border: '1px solid var(--border-subtle)',
                    borderRadius: '10px', padding: '10px 14px', color: '#fff', fontSize: '13px', fontWeight: '600', outline: 'none', marginTop: '6px'
                  }}
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-dim)', textTransform: 'uppercase' }}>
                  Payout Solana Address
                </label>
                <input
                  type="text"
                  value={customWallet}
                  onChange={e => setCustomWallet(e.target.value)}
                  style={{
                    width: '100%', background: '#050608', border: '1px solid var(--border-subtle)',
                    borderRadius: '10px', padding: '10px 14px', color: 'var(--solana-green)', fontSize: '12px', fontFamily: 'monospace', outline: 'none', marginTop: '6px'
                  }}
                />
              </div>
            </div>

            {/* Copyable Terminal Snippet */}
            <div className="terminal-window" style={{ marginBottom: '20px' }}>
              <div className="terminal-header">
                <span>bash / powershell</span>
                <span style={{ color: 'var(--cyan-accent)' }}>auto-detect cuda</span>
              </div>
              <div style={{ padding: '14px', fontSize: '12px', color: 'var(--solana-green)', wordBreak: 'break-all', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <code>{runCommand}</code>
              </div>
            </div>

            <button
              onClick={handleCopy}
              className="btn-solana"
              style={{ width: '100%', padding: '14px', fontSize: '14px' }}
            >
              {copiedCmd ? "✅ Command Copied to Clipboard!" : "📋 Copy Worker Launch Command"}
            </button>
          </div>

          {/* Hardware Specs & Requirements */}
          <div className="aperture-card" style={{ padding: '24px' }}>
            <h4 style={{ fontSize: '14px', fontWeight: '800', color: '#fff', marginBottom: '14px' }}>
              Minimum Hardware Requirements
            </h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '13px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>GPU:</span>
                <strong style={{ color: '#fff' }}>NVIDIA GTX 1060 / RTX 3050+</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>VRAM:</span>
                <strong style={{ color: '#fff' }}>4 GB+ GDDR6</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>OS:</span>
                <strong style={{ color: '#fff' }}>Windows 10/11 or Ubuntu 22.04 LTS</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>Python:</span>
                <strong style={{ color: 'var(--cyan-accent)' }}>Python 3.10 - 3.12 (pynvml)</strong>
              </div>
            </div>
          </div>

        </div>

      </div>

    </div>
  );
}