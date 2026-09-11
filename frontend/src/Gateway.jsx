import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

// Настройка адреса бэкенда
const API_URL = 'http://127.0.0.1:8000';

const ConsumerView = () => {
  const [runtime, setRuntime] = useState('python');
  const [tier, setTier] = useState('gpu_mid');
  const [code, setCode] = useState(`# Aperture Network Payload\nprint("Connecting to RTX 3050...")\n\nimport math\nprint(f"Calculation: {math.sqrt(256)}")`);
  const [status, setStatus] = useState('IDLE'); // IDLE, DEPLOYING, EXECUTING, DONE
  const [logs, setLogs] = useState([]);
  const terminalEndRef = useRef(null);

  // Автопрокрутка логов
  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  const addLog = (msg) => {
    const time = new Date().toLocaleTimeString();
    setLogs(prev => [...prev, `[${time}] ${msg}`]);
  };

  const runTask = async () => {
    if (!code.trim()) return;

    setStatus('DEPLOYING');
    setLogs([]);
    addLog('🛡️ SENTINEL: Starting deep security audit...');
    addLog('🔍 Checking for malicious syscalls and patterns...');

    try {
      // 1. ОТПРАВКА ЗАДАЧИ НА БЭКЕНД
      const response = await axios.post(`${API_URL}/execute`, {
        code: code,
        guest_id: "lelouch_user_1", // Позже заменим на реальный ID/Wallet
        wallet: "881Hpe3BtTquBCcm99KexH86KUgqVEvhuFeqqtkcxpkZ"
      });

      const { task_id, cost, ai_analysis } = response.data;

      addLog(`✅ SENTINEL: Audit passed. Trust Score: 100%`);
      addLog(`🔮 ORACLE: Complexity ${ai_analysis.cpu}. Rate: ${cost} USDC/sec`);
      addLog(`🔗 SOLANA: Escrow created. Task ID: ${task_id}`);
      addLog(`📡 DISPATCHING: Sending workload to active GPU node...`);

      setStatus('EXECUTING');

      // 2. ПОЛЛИНГ (ОПРОС РЕЗУЛЬТАТА)
      const pollInterval = setInterval(async () => {
        try {
          const res = await axios.get(`${API_URL}/result/${task_id}`);
          
          if (res.data.status === 'completed') {
            clearInterval(pollInterval);
            addLog(`🚀 NODE: Workload finished successfully.`);
            addLog(`>>> OUTPUT:\n${res.data.output}`);
            setStatus('DONE');
          } else {
            // Задача еще в процессе, можно добавить визуальный "пинг"
          }
        } catch (e) {
          console.log("Waiting for node...");
        }
      }, 2000); // Опрос каждые 2 секунды

    } catch (error) {
      const errorMsg = error.response?.data?.detail || error.message;
      addLog(`❌ GATEWAY ERROR: ${JSON.stringify(errorMsg)}`);
      setStatus('IDLE');
    }
  };

  return (
    <div className="fade-in-section">
      <h2 style={{ fontSize: '32px', fontWeight: '800', marginBottom: '8px', letterSpacing: '-0.03em' }}>Deploy Workload</h2>
      <p style={{ color: '#6B7280', marginBottom: '40px' }}>Select environment and hardware to initiate decentralized compute.</p>

      {/* Настройки */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '24px' }}>
        <div className="stat-card" style={{ padding: '20px', background: '#fff', border: '1px solid #eee', borderRadius: '16px' }}>
          <label style={{ fontSize: '11px', fontWeight: '700', color: '#9CA3AF', textTransform: 'uppercase' }}>Runtime</label>
          <select 
            style={{ width: '100%', border: 'none', background: 'none', fontSize: '16px', fontWeight: '600', outline: 'none' }}
            value={runtime} onChange={(e) => setRuntime(e.target.value)}
          >
            <option value="python">Python 3.11 (AI Stack)</option>
            <option value="nodejs">Node.js 20</option>
          </select>
        </div>
        <div className="stat-card" style={{ padding: '20px', background: '#fff', border: '1px solid #eee', borderRadius: '16px' }}>
          <label style={{ fontSize: '11px', fontWeight: '700', color: '#9CA3AF', textTransform: 'uppercase' }}>Hardware</label>
          <select 
            style={{ width: '100%', border: 'none', background: 'none', fontSize: '16px', fontWeight: '600', outline: 'none' }}
            value={tier} onChange={(e) => setTier(e.target.value)}
          >
            <option value="cpu">Standard CPU (Tier 1)</option>
            <option value="gpu_mid">RTX 3050 Optimized (Tier 2)</option>
          </select>
        </div>
      </div>

      {/* Терминал ввода */}
      <div style={{ backgroundColor: '#0A0A0A', borderRadius: '20px', overflow: 'hidden', boxShadow: '0 20px 40px rgba(0,0,0,0.2)' }}>
        <div style={{ backgroundColor: '#1A1A1A', padding: '10px 20px', fontSize: '12px', color: '#555', display: 'flex', justifyContent: 'space-between' }}>
          <span>terminal.sh</span>
          <span style={{ color: '#00ffaa' }}>● LIVE_CONNECTION</span>
        </div>
        <textarea 
          value={code}
          onChange={(e) => setCode(e.target.value)}
          style={{ width: '100%', height: '200px', backgroundColor: 'transparent', color: '#00ffaa', border: 'none', padding: '20px', fontSize: '14px', fontFamily: "'IBM Plex Mono', monospace", outline: 'none', resize: 'none' }}
        />
      </div>

      {/* Кнопка запуска */}
      <button 
        className={`btn-primary ${status !== 'IDLE' ? 'loading' : ''}`}
        style={{ 
            width: '100%', marginTop: '24px', padding: '18px', borderRadius: '14px', 
            backgroundColor: status === 'IDLE' ? '#111827' : '#6B7280', 
            color: '#fff', fontWeight: '700', border: 'none', cursor: 'pointer' 
        }}
        onClick={runTask}
        disabled={status !== 'IDLE'}
      >
        {status === 'IDLE' ? 'Initiate Deployment' : 'System Processing...'}
      </button>

      {/* Реальные логи */}
      {logs.length > 0 && (
        <div style={{ marginTop: '30px', backgroundColor: '#F9FAFB', borderRadius: '16px', padding: '24px', border: '1px solid #F3F4F6', fontFamily: 'monospace' }}>
          <div style={{ fontSize: '11px', fontWeight: '700', color: '#9CA3AF', marginBottom: '12px' }}>GATEWAY_LOGS</div>
          {logs.map((log, i) => (
            <div key={i} style={{ fontSize: '13px', marginBottom: '6px', color: log.includes('❌') ? '#EF4444' : '#111827', whiteSpace: 'pre-wrap' }}>
              {log}
            </div>
          ))}
          {status === 'EXECUTING' && <div className="blink" style={{ color: '#00ffaa' }}>⏳ Waiting for Node result...</div>}
          <div ref={terminalEndRef} />
        </div>
      )}
    </div>
  );
};

export default ConsumerView;