import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { Buffer } from 'buffer';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import { LAMPORTS_PER_SOL, PublicKey, SystemProgram, Transaction, TransactionInstruction } from '@solana/web3.js';
import Icon from './components/Icon';
import { WORKLOADS, estimateDemo, resultStatus } from './utils/workloads';
import './Dashboard.css';

const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const DEFAULT_PROGRAM_ID = 'A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ';
const ACTIVE = ['reviewing', 'signing', 'submitting', 'queued', 'running', 'settlement_pending', 'stopping'];
const LABELS = { idle: 'Ready when you are', quoted: 'Review your spending limit', reviewing: 'Requesting a quote', signing: 'Waiting for signature', submitting: 'Submitting workload', queued: 'Waiting for a worker', running: 'Workload in progress', settlement_pending: 'Result saved · settlement pending', stopping: 'Requesting cancellation', completed: 'Run completed', blocked: 'Source policy blocked', failed: 'Run failed', cancelled: 'Run cancelled' };
const ACTIVE_STORAGE_KEY = 'aperture-active:' + API_URL;
function readActiveRun() {
  try {
    const run = JSON.parse(sessionStorage.getItem(ACTIVE_STORAGE_KEY));
    return run?.mode === 'gateway' && /^task-[a-f0-9]{32}$/.test(run.id) && typeof run.token === 'string' && run.token.length >= 32 && Number.isFinite(run.started) ? run : null;
  } catch { return null; }
}
function saveActiveRun(run) {
  // This bearer capability is kept only in this tab. No wallet key or source is stored.
  try { sessionStorage.setItem(ACTIVE_STORAGE_KEY, JSON.stringify({ id: run.id, token: run.token, mode: run.mode, name: run.name, started: run.started, offset: run.offset, estimate: run.estimate })); }
  catch { /* Storage may be unavailable; monitoring remains live in memory. */ }
}

function saveFile(name, content, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function errorMessage(error) {
  const detail = error.response?.data?.detail;
  return typeof detail === 'string' ? detail : error.message || 'The request could not be completed.';
}
async function anchorInstructionData(name, amount) {
  const input = new TextEncoder().encode(`global:${name}`);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', input));
  const discriminator = digest.slice(0, 8);
  if (amount === undefined) return discriminator;
  const data = new Uint8Array(16);
  data.set(discriminator, 0);
  let remaining = BigInt(amount);
  for (let index = 0; index < 8; index += 1) {
    data[8 + index] = Number(remaining & 0xffn);
    remaining >>= 8n;
  }
  return data;
}

export default function Dashboard({ isDemoMode = true, selection, onBusyChange, onRecord }) {
  const { publicKey, signMessage, sendTransaction } = useWallet();
  const { connection } = useConnection();
  const { setVisible } = useWalletModal();
  const [code, setCode] = useState(WORKLOADS[0].code);
  const [sampleId, setSampleId] = useState(WORKLOADS[0].id);
  const [name, setName] = useState(WORKLOADS[0].name);
  const [status, setStatus] = useState('idle');
  const [logs, setLogs] = useState([]);
  const [notice, setNotice] = useState('');
  const [analysis, setAnalysis] = useState(null);
  const [quote, setQuote] = useState(null);
  const [maxCost, setMaxCost] = useState('0.001');
  const [maxRuntime, setMaxRuntime] = useState('30');
  const [gatewayDemo, setGatewayDemo] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const [copied, setCopied] = useState(false);
  const [runs, setRuns] = useState([]);
  const [walletBalance, setWalletBalance] = useState(0);
  const [channel, setChannel] = useState(null);
  const [protocolConfig, setProtocolConfig] = useState(null);
  const [depositAmount, setDepositAmount] = useState('0.1');
  const [channelBusy, setChannelBusy] = useState(false);
  const active = useRef(null);
  const pollTimer = useRef(null);
  const controller = useRef(null);
  const inputRef = useRef(null);
  const logRef = useRef(null);
  const resultTokens = useRef(new Map());
  const busy = ACTIVE.includes(status);

  const refreshChannel = useCallback(async () => {
    if (isDemoMode || !publicKey) {
      setWalletBalance(0);
      setChannel(null);
      setProtocolConfig(null);
      return null;
    }
    const [walletResult, channelResult, configResult, healthResult] = await Promise.allSettled([
      connection.getBalance(publicKey, 'confirmed'),
      axios.get(API_URL + '/balance/' + publicKey.toBase58(), { timeout: 10000 }),
      axios.get(API_URL + '/channel-config', { timeout: 10000 }),
      axios.get(API_URL + '/health', { timeout: 10000 }),
    ]);
    if (walletResult.status === 'fulfilled') setWalletBalance(walletResult.value / LAMPORTS_PER_SOL);
    const nextChannel = channelResult.status === 'fulfilled' ? channelResult.value.data : null;
    const nextConfig = configResult.status === 'fulfilled' ? configResult.value.data : null;
    setChannel(nextChannel);
    setProtocolConfig(nextConfig);
    const development = healthResult.status === 'fulfilled' && healthResult.value.data.demo_mode;
    setGatewayDemo(Boolean(development));
    return { channel: nextChannel, config: nextConfig, development };
  }, [connection, isDemoMode, publicKey]);

  useEffect(() => {
    if (isDemoMode || !publicKey) return undefined;
    refreshChannel();
    const timer = setInterval(refreshChannel, 20000);
    return () => clearInterval(timer);
  }, [isDemoMode, publicKey, refreshChannel]);

  const submitChannelInstruction = async (instruction) => {
    const transaction = new Transaction().add(instruction);
    const latest = await connection.getLatestBlockhash('confirmed');
    transaction.feePayer = publicKey;
    transaction.recentBlockhash = latest.blockhash;
    const signature = await sendTransaction(transaction, connection);
    const confirmation = await connection.confirmTransaction({ ...latest, signature }, 'confirmed');
    if (confirmation.value.err) throw new Error('Transaction failed: ' + JSON.stringify(confirmation.value.err));
    return signature;
  };

  const handleDeposit = async () => {
    const amount = Number(depositAmount);
    const lamportsNumber = Math.round(amount * LAMPORTS_PER_SOL);
    if (!Number.isFinite(amount) || amount <= 0 || !Number.isSafeInteger(lamportsNumber)) {
      setNotice('Enter a valid SOL amount that fits safely in a transaction.');
      return;
    }
    if (!publicKey || !sendTransaction) { setVisible(true); return; }
    setChannelBusy(true);
    setNotice('');
    try {
      const state = await refreshChannel();
      if (!state?.config?.initialized) throw new Error('The gateway protocol config is unavailable or not initialized.');
      if (state?.channel?.burn_rate_lamports > 0) throw new Error('Stop the active workload before adding funds to the channel.');
      const programId = new PublicKey(state.config.program_id || DEFAULT_PROGRAM_ID);
      const [configPda] = PublicKey.findProgramAddressSync([Buffer.from('config')], programId);
      const [channelPda] = PublicKey.findProgramAddressSync([Buffer.from('channel'), publicKey.toBuffer()], programId);
      const opening = !state?.channel?.initialized;
      const instruction = new TransactionInstruction({
        programId,
        keys: opening ? [
          { pubkey: configPda, isSigner: false, isWritable: false },
          { pubkey: channelPda, isSigner: false, isWritable: true },
          { pubkey: publicKey, isSigner: true, isWritable: true },
          { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
        ] : [
          { pubkey: channelPda, isSigner: false, isWritable: true },
          { pubkey: publicKey, isSigner: true, isWritable: true },
          { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
        ],
        data: await anchorInstructionData(opening ? 'open_channel' : 'top_up', BigInt(lamportsNumber)),
      });
      const signature = await submitChannelInstruction(instruction);
      setNotice((opening ? 'Channel opened' : 'Channel topped up') + '. Devnet transaction: ' + signature);
      await refreshChannel();
    } catch (error) {
      setNotice('Channel deposit failed: ' + errorMessage(error));
    } finally {
      setChannelBusy(false);
    }
  };

  const handleCloseChannel = async () => {
    if (!publicKey || !sendTransaction || !protocolConfig?.initialized || !channel?.initialized) return;
    if (busy || Number(channel.burn_rate_lamports) > 0) {
      setNotice('Wait until the workload is stopped and channel billing is idle before closing it.');
      return;
    }
    setChannelBusy(true);
    setNotice('');
    try {
      const programId = new PublicKey(protocolConfig.program_id || DEFAULT_PROGRAM_ID);
      const [configPda] = PublicKey.findProgramAddressSync([Buffer.from('config')], programId);
      const [channelPda] = PublicKey.findProgramAddressSync([Buffer.from('channel'), publicKey.toBuffer()], programId);
      const instruction = new TransactionInstruction({
        programId,
        keys: [
          { pubkey: configPda, isSigner: false, isWritable: false },
          { pubkey: channelPda, isSigner: false, isWritable: true },
          { pubkey: publicKey, isSigner: true, isWritable: true },
          { pubkey: new PublicKey(protocolConfig.treasury), isSigner: false, isWritable: true },
        ],
        data: await anchorInstructionData('close_channel'),
      });
      const signature = await submitChannelInstruction(instruction);
      setNotice('Channel closed and remaining funds refunded. Devnet transaction: ' + signature);
      await refreshChannel();
    } catch (error) {
      setNotice('Could not close payment channel: ' + errorMessage(error));
    } finally {
      setChannelBusy(false);
    }
  };

  useEffect(() => { onBusyChange?.(busy || channelBusy); }, [busy, channelBusy, onBusyChange]);
  useEffect(() => { setQuote(null); setStatus(previous => previous === 'quoted' ? 'idle' : previous); }, [code, publicKey, maxCost, maxRuntime, isDemoMode]);
  useEffect(() => {
    if (!quote) return undefined;
    const timer = setTimeout(() => { setQuote(null); setStatus('idle'); setNotice('Quote expired. Review a fresh quote before signing.'); }, Math.max(0, quote.expires_at * 1000 - Date.now()));
    return () => clearTimeout(timer);
  }, [quote]);
  useEffect(() => {
    if (selection && !active.current) {
      setCode(selection.code); setName(selection.name); setSampleId(selection.id);
      setStatus('idle'); setNotice(''); setAnalysis(null); setReceipt(null);
    }
  }, [selection]);
  useEffect(() => {
    if (!active.current) { setStatus('idle'); setNotice(''); setAnalysis(null); setReceipt(null); setLogs([]); }
  }, [isDemoMode]);
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);
  useEffect(() => {
    const warn = event => { if (active.current) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => { window.removeEventListener('beforeunload', warn); clearTimeout(pollTimer.current); controller.current?.abort(); active.current = null; };
  }, []);

  const log = (message, kind = 'info') => setLogs(previous => [...previous, { message, kind, time: new Date().toLocaleTimeString([], { hour12: false }) }].slice(-500));
  const selectSample = sample => {
    if (active.current) return;
    setCode(sample.code); setName(sample.name); setSampleId(sample.id);
    setStatus('idle'); setAnalysis(null); setReceipt(null); setNotice('');
  };
  const finish = (run, outcome, details = {}) => {
    if (active.current !== run) return;
    clearTimeout(pollTimer.current);
    controller.current?.abort();
    active.current = null;
    if (run.token) resultTokens.current.set(run.id, run.token);
    if (run.mode === 'gateway') { try { sessionStorage.removeItem(ACTIVE_STORAGE_KEY); } catch { /* Tab storage unavailable. */ } }
    setStatus(outcome);
    const result = { taskId: run.id, name: run.name, mode: run.mode, status: outcome, timestamp: new Date().toISOString(), durationSeconds: +((Date.now() - run.started) / 1000).toFixed(2), ...details };
    setReceipt(result);
    setRuns(previous => [result, ...previous].slice(0, 20));
    onRecord?.({ id: run.id, name: run.name, mode: run.mode, status: outcome, timestamp: result.timestamp });
  };
  const monitor = async run => {
    if (active.current !== run || run.polling) return;
    clearTimeout(pollTimer.current);
    run.polling = true;
    try {
      const response = await axios.get(API_URL + '/stream_log/' + run.id, { params: { offset: run.offset, access_token: run.token }, signal: controller.current.signal, timeout: 8000 });
      if (active.current !== run) return;
      const data = response.data;
      (data.lines || []).forEach(chunk => chunk.split('\n').filter(Boolean).forEach(line => log(line, 'output')));
      run.offset = data.next_offset ?? run.offset;
      saveActiveRun(run);
      if (['queued', 'running', 'settlement_pending'].includes(data.task_status)) setStatus(data.task_status);
      if (run.retries) { setNotice(''); run.retries = 0; log('Connection restored.'); }
      if (data.is_completed) {
        const outcome = resultStatus(data.output, data.receipt);
        const evidence = data.receipt || {};
        log(outcome === 'completed' ? 'Worker returned a result.' : 'Task ended: ' + outcome + '.', outcome === 'completed' ? 'success' : 'warning');
        if (run.mode === 'gateway') refreshChannel();
        finish(run, outcome, { output: data.output || '', settlementType: evidence.settlement_type || 'UNKNOWN', proof: evidence.explorer_url || null, costSol: evidence.cost_sol ?? null, workerId: evidence.worker_id || null, durationSeconds: evidence.execution_time ?? null, backendReceipt: evidence, ...run.estimate });
        return;
      }
    } catch (error) {
      if (active.current !== run || axios.isCancel(error)) return;
      run.retries = (run.retries || 0) + 1;
      setNotice('Connection interrupted. Retrying status updates. The task may still be running on the gateway.');
    } finally {
      run.polling = false;
    }
    if (active.current === run) pollTimer.current = setTimeout(() => monitor(run), Math.min(8000, 1000 * 2 ** (run.retries || 0)));
  };

  useEffect(() => {
    const restored = readActiveRun();
    if (!restored || active.current) return undefined;
    const run = { ...restored, offset: 0 };
    active.current = run;
    controller.current = new AbortController();
    setName(run.name); setSampleId('custom');
    setCode('# Active gateway task restored from this browser tab.\n# Original Python source is not stored in the browser.\n# Inspect its source hash in the completed receipt.\n');
    setStatus('queued');
    setNotice('Restored the active gateway task from this browser tab. Monitoring continues; the original source was not saved.');
    monitor(run);
    return () => { clearTimeout(pollTimer.current); controller.current?.abort(); if (active.current === run) active.current = null; };
    // Restore once; monitor owns this run object and never switches task on render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reviewQuote = async () => {
    if (active.current || busy) return;
    if (!publicKey) { setVisible(true); return; }
    setNotice(''); setQuote(null); setStatus('reviewing');
    try {
      estimateDemo(code);
      const budget = Math.round(Number(maxCost) * LAMPORTS_PER_SOL);
      const runtime = Number(maxRuntime);
      if (!Number.isSafeInteger(budget) || budget < 1 || budget > 1e9 || !Number.isInteger(runtime) || runtime < 1 || runtime > 180) throw new Error('Choose a positive budget up to 1 SOL and a whole runtime from 1 to 180 seconds.');
      const wallet = publicKey.toBase58();
      const { data } = await axios.post(API_URL + '/quotes', { wallet, agent_pubkey: wallet, code, max_cost_lamports: budget, max_runtime_seconds: runtime }, { timeout: 15000 });
      const sourceHash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(code)))).map(byte => byte.toString(16).padStart(2, '0')).join('');
      if (data.wallet !== wallet || data.agent_pubkey !== wallet || data.code_sha256 !== sourceHash || data.max_cost_lamports !== budget || data.max_runtime_seconds !== runtime) throw new Error('The returned quote does not match the source and spending bounds.');
      setQuote(data); setStatus('quoted');
      setAnalysis({ score: data.analysis?.scores?.final_score ?? data.analysis?.complexity_score ?? 0, rateLamports: data.rate_lamports, description: data.analysis?.reason || 'Gateway source policy accepted this workload.' });
    } catch (error) { setStatus('idle'); setNotice(errorMessage(error)); }
  };

  const start = async () => {
    if (active.current) return;
    setNotice('');
    let estimate;
    try { estimate = estimateDemo(code); } catch (error) { setNotice(error.message); return; }
    if (!isDemoMode && !publicKey) { setVisible(true); return; }
    if (!isDemoMode && !signMessage) { setNotice('This wallet cannot sign messages. Choose a compatible Solana wallet.'); return; }
    if (!isDemoMode) {
      if (!quote || quote.expires_at * 1000 <= Date.now()) { setNotice('Review a fresh quote before signing this workload.'); setQuote(null); return; }
      let liveState;
      try { liveState = await refreshChannel(); }
      catch (error) { setNotice('Could not check the Devnet payment channel: ' + errorMessage(error)); return; }
      if (!liveState?.development && !liveState?.config?.initialized) { setNotice('The gateway protocol is not configured. Check its Devnet program and authority settings.'); return; }
      if (!liveState?.development && (!liveState?.channel?.initialized || Number(liveState.channel.lamports) < quote.max_cost_lamports)) {
        setNotice('Fund an idle payment channel to cover the full authorized maximum cost before submitting.');
        return;
      }
    }
    const run = { id: (isDemoMode ? 'demo-' : 'request-') + crypto.randomUUID(), name, mode: isDemoMode ? 'demo' : 'gateway', started: Date.now(), offset: 0 };
    active.current = run;
    controller.current = new AbortController();
    setLogs([]); setReceipt(null); setStatus('reviewing');
    if (isDemoMode) {
      setAnalysis({ score: estimate.score, rateLamports: estimate.rateLamports, description: 'Illustrative browser estimate. No Python is executed.' });
      log('Browser demo started. No worker or wallet is involved.');
      if (estimate.restricted) {
        setAnalysis({ score: 0, rateLamports: 0, description: 'This demonstration stops at the policy review step.' });
        log('Example policy: this workload contains a restricted import.', 'warning');
        finish(run, 'blocked', { settlementType: 'SIMULATION', output: 'Restricted import detected in the demonstration. No code was executed.', score: 0, rateLamports: 0, costSol: 0 });
        return;
      }
      setStatus('running');
      log('Illustrative estimate: ' + estimate.score + '/100 · ' + estimate.rateLamports + ' lamports/s.');
      const stages = ['Previewing the worker dispatch step…', 'Previewing the result and receipt step…', 'Demo complete. Your Python source was not executed.'];
      let step = 0;
      const tick = () => {
        if (active.current !== run) return;
        log(stages[step], step === 2 ? 'success' : 'info');
        step++;
        if (step < stages.length) pollTimer.current = setTimeout(tick, 650);
        else finish(run, 'completed', { settlementType: 'SIMULATION', output: 'Browser workflow preview completed. No computation or payment was performed.', score: estimate.score, rateLamports: estimate.rateLamports, costSol: 0 });
      };
      pollTimer.current = setTimeout(tick, 650);
      return;
    }
    try {
      const config = { signal: controller.current.signal, timeout: 15000 };
      const wallet = publicKey.toBase58();
      const challenge = quote;
      setQuote(null);
      log('Authorizing the reviewed rate, source hash, maximum spend and runtime.');
      if (active.current !== run) return;
      setStatus('signing');
      let signature;
      try { signature = await signMessage(new TextEncoder().encode(challenge.message)); }
      catch { throw new Error('Wallet signature declined. The workload was not submitted.'); }
      if (active.current !== run) return;
      setStatus('submitting');
      run.submitting = true;
      const body = { quote_id: challenge.quote_id, code, wallet, agent_pubkey: wallet, signature: Array.from(signature), message: challenge.message };
      let data;
      try { ({ data } = await axios.post(API_URL + '/execute', body, config)); }
      catch (error) {
        if (error.response || axios.isCancel(error)) throw error;
        // The exact signed quote is idempotent; a lost response cannot dispatch twice.
        ({ data } = await axios.post(API_URL + '/execute', body, config));
      }
      if (active.current !== run) return;
      run.id = data.task_id; run.token = data.task_access_token;
      run.estimate = { score: challenge.analysis?.scores?.final_score ?? 0, rateLamports: challenge.rate_lamports };
      saveActiveRun(run);
      setStatus('queued');
      log('Accepted by the gateway. Waiting for an authenticated worker.');
      monitor(run);
    } catch (error) {
      if (active.current !== run) return;
      const uncertainSubmission = !error.response && run.submitting;
      const message = uncertainSubmission ? 'Submission was not confirmed. Check the gateway before retrying; it may have received the task.' : errorMessage(error);
      setNotice(message); log(message, 'warning');
      finish(run, error.response?.status === 403 ? 'blocked' : 'failed', { settlementType: uncertainSubmission ? 'UNKNOWN' : 'NONE', output: message });
    }
  };
  const stop = async () => {
    const run = active.current;
    if (!run || !['queued', 'running', 'settlement_pending'].includes(status)) return;
    if (run.mode === 'demo') { log('Browser demo cancelled.', 'warning'); finish(run, 'cancelled', { settlementType: 'SIMULATION', costSol: 0 }); return; }
    setStatus('stopping');
    try {
      const { data } = await axios.post(API_URL + '/stop/' + run.id, null, { params: { access_token: run.token }, timeout: 15000 });
      if (active.current !== run) return;
      log('Gateway accepted cancellation.', 'warning');
      refreshChannel();
      setStatus(data.status === 'settlement_pending' ? 'settlement_pending' : 'stopping');
      monitor(run);
    } catch (error) {
      if (active.current !== run) return;
      setStatus('running'); setNotice('Cancellation was not confirmed: ' + errorMessage(error) + ' Status monitoring continues.');
    }
  };
  const importFile = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || active.current) return;
    if (file.size > 65536) { setNotice('Choose a Python file smaller than 64 KB.'); return; }
    try {
      const content = await file.text();
      if (active.current) return;
      setCode(content); setName(file.name); setSampleId('custom'); setAnalysis(null); setReceipt(null); setStatus('idle'); setNotice('');
    } catch { setNotice('The file could not be read. Please try another file.'); }
  };
  const copyCode = async () => {
    try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1800); }
    catch { setNotice('Clipboard unavailable. Select the code and copy it manually.'); }
  };
  const downloadRaw = async () => {
    if (!receipt?.taskId || receipt.mode !== 'gateway') return;
    try {
      const completed = resultTokens.current.get(receipt.taskId);
      if (!completed) throw new Error('Raw log access is available for runs completed in this tab.');
      const { data } = await axios.get(API_URL + '/download/' + receipt.taskId, { params: { access_token: completed }, responseType: 'text', timeout: 15000 });
      saveFile('aperture-' + receipt.taskId + '.txt', data);
    } catch (error) { setNotice(errorMessage(error)); }
  };

  return <div className="studio">
    {notice && <div className="studio-notice" role="alert"><Icon name="shield" size={18} /><p>{notice}</p></div>}
    <div className="studio-grid">
      <section className="studio-editor">
        <div className="studio-editor-heading"><div><span className="studio-file-dot" /><strong>workload.py</strong><span className="studio-language">PYTHON</span></div><div><button onClick={copyCode} title="Copy source" aria-label={copied ? 'Code copied' : 'Copy code'}><Icon name={copied ? 'check' : 'copy'} size={17} /></button><button onClick={() => inputRef.current.click()} disabled={busy} title="Import Python file" aria-label="Import Python file"><Icon name="upload" size={17} /></button></div></div>
        <div className="studio-presets"><label htmlFor="workload-preset">Sample</label><select id="workload-preset" value={sampleId} disabled={busy} onChange={event => selectSample(WORKLOADS.find(sample => sample.id === event.target.value))}>{WORKLOADS.map(sample => <option value={sample.id} key={sample.id}>{sample.name}</option>)}{sampleId === 'custom' && <option value="custom">Custom workload</option>}</select><button disabled={busy} onClick={() => selectSample(WORKLOADS.find(sample => sample.id === sampleId) || WORKLOADS[0])} title="Reset sample" aria-label="Reset sample"><Icon name="refresh" size={16} /></button></div>
        <div className="studio-source"><textarea aria-label="Python source code" value={code} spellCheck={false} disabled={busy} onChange={event => { setCode(event.target.value); setSampleId('custom'); setName('Custom workload'); setAnalysis(null); setReceipt(null); setStatus('idle'); }} /></div>
        <div className="studio-editor-meta"><span>UTF-8 · {code.split('\n').length} lines</span><span>{new TextEncoder().encode(code).length.toLocaleString()} / 65,536 bytes</span></div>
        <div className="studio-run-bar"><span><Icon name={isDemoMode ? 'spark' : 'wallet'} size={15} />{isDemoMode ? 'Browser demo' : gatewayDemo ? 'Off-chain gateway' : 'Solana Devnet'}</span>{busy ? <button className="console-button secondary" disabled={!['queued', 'running', 'settlement_pending'].includes(status)} onClick={stop}><Icon name="stop" size={16} />{status === 'stopping' ? 'Stopping…' : ['queued', 'running', 'settlement_pending'].includes(status) ? 'Stop run' : 'Please wait…'}</button> : <button className="console-button primary" onClick={isDemoMode || quote ? start : reviewQuote} disabled={channelBusy}><Icon name={channelBusy ? 'refresh' : 'play'} size={16} />{channelBusy ? 'Channel transaction…' : isDemoMode ? 'Run demo' : !publicKey ? 'Connect wallet' : quote ? 'Accept quote & sign' : 'Review price & limits'}</button>}</div>
        <input ref={inputRef} type="file" accept=".py,text/plain" hidden onChange={importFile} />
      </section>
      <aside className="studio-inspector">
        <section className="console-panel studio-status-card"><span className="console-eyebrow">RUN INSPECTOR</span><div className={'studio-status-icon ' + status}><Icon name={status === 'completed' ? 'check' : ['failed', 'blocked'].includes(status) ? 'shield' : busy ? 'refresh' : 'spark'} size={27} /></div><h2 aria-live="polite">{LABELS[status]}</h2><p>{status === 'idle' ? 'Your workload, estimate and result. Everything in one place.' : busy ? 'You can explore other pages while this run is active.' : 'Review the outcome below or start another experiment.'}</p><ol className="studio-steps">{['Prepare', 'Review', 'Run', 'Result'].map((step, index) => <li key={step} className={(status === 'idle' ? index === 0 : busy ? index <= (status === 'running' ? 2 : 1) : true) ? 'reached' : ''}><span>{index + 1}</span>{step}</li>)}</ol></section>
        <section className="console-panel studio-estimate"><div className="console-section-heading"><h2>{isDemoMode ? 'Demo estimate' : 'Price & spending limit'}</h2><Icon name="chip" size={18} /></div><dl><div><dt>Complexity</dt><dd>{analysis ? analysis.score + '/100' : '—'}</dd></div><div><dt>Quoted rate</dt><dd>{analysis ? analysis.rateLamports + ' lamports/s' : '—'}</dd></div><div><dt>Payment</dt><dd>{isDemoMode ? 'No payment' : gatewayDemo ? 'Off-chain development' : 'Devnet channel'}</dd></div></dl>{!isDemoMode && <div className="studio-budget"><label htmlFor="task-max-cost">Maximum cost · SOL<input id="task-max-cost" type="number" min="0.000000001" max="1" step="0.000001" value={maxCost} disabled={busy} onChange={event => setMaxCost(event.target.value)} /></label><label htmlFor="task-max-runtime">Maximum runtime · seconds<input id="task-max-runtime" type="number" min="1" max="180" step="1" value={maxRuntime} disabled={busy} onChange={event => setMaxRuntime(event.target.value)} /></label></div>}<p>{analysis?.description || (isDemoMode ? 'Run a workload to see its estimate.' : 'Request a quote, inspect its limits, then approve it with your wallet.')}</p>{quote && <div className="studio-quote"><strong>Ready for your approval</strong><p>Rate: {quote.rate_lamports / 1e9} SOL/s<br />Maximum charge: {quote.max_cost_lamports / 1e9} SOL<br />Execution limit: {quote.effective_runtime_seconds}s<br />Quote expires: {new Date(quote.expires_at * 1000).toLocaleTimeString()}</p><p>Editing the source, wallet or limits discards this quote. Approval signs this exact source hash and budget.</p><button className="console-button primary" onClick={start} disabled={channelBusy}>Accept quote & sign</button></div>}</section>
        {!isDemoMode && <section className="console-panel studio-channel">
          <div className="console-section-heading"><div><span className="console-eyebrow">DEVNET PAYMENT</span><h2>Payment channel</h2></div><Icon name="wallet" size={18} /></div>
          {publicKey ? <>
            <p className="studio-channel-wallet">Wallet · {publicKey.toBase58().slice(0, 5)}…{publicKey.toBase58().slice(-5)}</p>
            <dl>
              <div><dt>Wallet balance</dt><dd>{walletBalance.toFixed(4)} SOL</dd></div>
              <div><dt>Channel balance</dt><dd>{Number(channel?.balance || 0).toFixed(4)} SOL</dd></div>
              <div><dt>Protocol</dt><dd>{protocolConfig?.initialized ? 'Configured' : 'Unavailable'}</dd></div>
            </dl>
            <label className="studio-channel-label" htmlFor="channel-deposit">Deposit amount</label>
            <div className="studio-channel-deposit">
              <input id="channel-deposit" inputMode="decimal" type="number" min="0.000000001" step="0.01" value={depositAmount} disabled={busy || channelBusy} onChange={event => setDepositAmount(event.target.value)} />
              <span>SOL</span>
            </div>
            <button className="console-button primary studio-channel-action" onClick={handleDeposit} disabled={busy || channelBusy || !sendTransaction || !protocolConfig?.initialized}>
              <Icon name="wallet" size={16} />{channelBusy ? 'Waiting for Devnet…' : channel?.initialized ? 'Add to channel' : 'Open & fund channel'}
            </button>
            {channel?.initialized && <button className="console-text-button studio-channel-close" onClick={handleCloseChannel} disabled={busy || channelBusy || Number(channel.burn_rate_lamports) > 0}>
              Close channel and refund remaining SOL<Icon name="arrow" size={15} />
            </button>}
            {gatewayDemo ? <p className="studio-channel-help">This gateway uses off-chain development settlement. Real Python can execute on a worker; no SOL payment or Devnet evidence is produced.</p> : !protocolConfig?.initialized && <p className="studio-channel-help">The gateway must be deployed and its protocol configuration initialized before the channel can be opened.</p>}
            {protocolConfig?.initialized && !channel?.initialized && <p className="studio-channel-help">Your wallet will sign a Devnet transaction to open this channel.</p>}
          </> : <>
            <p className="studio-channel-help">Connect a Solana wallet to view your Devnet balance, open a payment channel and submit a live workload.</p>
            <button className="console-button primary studio-channel-action" onClick={() => setVisible(true)}>Connect wallet<Icon name="arrow" size={16} /></button>
          </>}
        </section>}
      </aside>
    </div>
    <section className="studio-terminal"><div className="studio-terminal-heading"><span><Icon name="code" size={18} />Run output<span className="studio-terminal-count">{logs.length} events</span></span><button className="console-text-button" disabled={!logs.length} onClick={() => saveFile('aperture-output.txt', logs.map(entry => '[' + entry.time + '] ' + entry.message).join('\n'))}><Icon name="download" size={16} />Save log</button></div><div className="studio-log" ref={logRef} role="log" aria-label="Run output" aria-live="polite">{logs.length ? logs.map((entry, index) => <div className={'studio-log-line ' + entry.kind} key={index}><time>{entry.time}</time><span>{entry.message}</span></div>) : <div className="studio-terminal-empty"><span>›</span> Your run output will appear here.</div>}</div></section>
    {receipt && <section className="console-panel studio-receipt"><div className="console-section-heading"><div><span className="console-eyebrow">{receipt.settlementType === 'SIMULATION' ? 'BROWSER DEMO RESULT' : 'WORKLOAD RESULT'}</span><h2>{receipt.name}</h2></div><span className={'console-tag ' + (['failed', 'blocked'].includes(receipt.status) ? 'error' : '')}>{receipt.status}</span></div><div className="studio-receipt-details"><div><span>Result type</span><strong>{receipt.settlementType}</strong></div><div><span>Worker runtime</span><strong>{receipt.durationSeconds == null ? 'Unavailable' : receipt.durationSeconds + 's'}</strong></div><div><span>Confirmed cost</span><strong>{receipt.costSol == null ? 'Not confirmed' : receipt.costSol + ' SOL'}</strong></div></div>{receipt.output && <pre>{receipt.output}</pre>}{receipt.backendReceipt && <dl className="studio-receipt-evidence">{[['Worker', receipt.backendReceipt.worker_id], ['Exit code', receipt.backendReceipt.exit_code], ['Execution boundary', receipt.backendReceipt.execution_backend], ['Agent public key', receipt.backendReceipt.agent_pubkey], ['Source SHA-256', receipt.backendReceipt.code_sha256], ['Raw output SHA-256', receipt.backendReceipt.output_sha256], ['Worker signature', receipt.backendReceipt.worker_signature], ['Receipt hash', receipt.backendReceipt.receipt_sha256]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? 'Unavailable'}</dd></div>)}<p>{receipt.backendReceipt.attestation}</p></dl>}<div className="studio-receipt-actions"><button className="console-button secondary" onClick={() => saveFile('aperture-' + receipt.taskId + '.json', JSON.stringify(receipt.backendReceipt || receipt, null, 2), 'application/json')}><Icon name="download" size={16} />Download canonical receipt</button>{receipt.mode === 'gateway' && <button className="console-text-button" onClick={downloadRaw}><Icon name="download" size={16} />Download raw output</button>}{receipt.proof && /^https:\/\/explorer\.solana\.com\/tx\//.test(receipt.proof) && <a className="console-text-button" href={receipt.proof} target="_blank" rel="noreferrer">View Devnet transaction<Icon name="external" size={16} /></a>}</div></section>}
    {runs.length > 1 && <section className="console-panel studio-history"><h2>This session</h2>{runs.map(run => <button key={run.taskId} onClick={() => setReceipt(run)} disabled={busy}><span><Icon name={run.mode === 'demo' ? 'spark' : 'chip'} size={16} />{run.name}</span><span>{run.mode === 'demo' ? 'Demo' : 'Gateway'} · {run.status}<Icon name="arrow" size={16} /></span></button>)}</section>}
  </div>;
}
