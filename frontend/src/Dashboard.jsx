import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import { LAMPORTS_PER_SOL, PublicKey, SystemProgram, Transaction, TransactionInstruction } from '@solana/web3.js';
import Icon from './components/Icon';
import { APERTURE_PROGRAM_ID, GATEWAY_PUBKEY_PIN, TREASURY_PUBKEY_PIN, QUOTE_MESSAGE_KEYS, canonicalQuoteMessage, sha256Hex, verifyGatewayReceipt, verifyDevnetSettlement } from './utils/protocol';
import { WORKLOADS, validateSource, resultStatus } from './utils/workloads';
import './Dashboard.css';

const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const ACTIVE = ['reviewing', 'signing', 'submitting', 'uncertain', 'queued', 'running', 'settlement_pending', 'stopping'];
const LABELS = { idle: 'Ready when you are', quoted: 'Review your spending limit', reviewing: 'Requesting a quote', signing: 'Waiting for signature', submitting: 'Submitting workload', uncertain: 'Submission status uncertain', queued: 'Waiting for a worker', running: 'Workload in progress', settlement_pending: 'Result saved · settlement pending', stopping: 'Requesting cancellation', completed: 'Run completed', unverified: 'Receipt unverified', blocked: 'Source policy blocked', failed: 'Run failed', cancelled: 'Run cancelled' };
const ACTIVE_STORAGE_KEY = 'aperture-active:' + API_URL;
const PENDING_ADMISSION_KEY = 'aperture-pending-admission:' + API_URL;
function readActiveRun() {
  try {
    const run = JSON.parse(sessionStorage.getItem(ACTIVE_STORAGE_KEY));
    return run?.mode === 'gateway' && /^task-[a-f0-9]{32}$/.test(run.id) && typeof run.token === 'string' && run.token.length >= 32 && Number.isFinite(run.started) ? run : null;
  } catch { return null; }
}
function saveActiveRun(run) {
  // This bearer capability is kept only in this tab. No wallet key or source is stored.
  try { sessionStorage.setItem(ACTIVE_STORAGE_KEY, JSON.stringify({ id: run.id, token: run.token, mode: run.mode, name: run.name, started: run.started, offset: run.offset, estimate: run.estimate, quote: run.quote })); }
  catch { /* Storage may be unavailable; monitoring remains live in memory. */ }
}
function quoteForReceipt(quote) {
  return Object.fromEntries(QUOTE_MESSAGE_KEYS.map(key => [key, quote[key]]));
}
function readPendingAdmission() {
  try {
    const pending = JSON.parse(sessionStorage.getItem(PENDING_ADMISSION_KEY));
    const body = pending?.body;
    if (pending?.mode !== 'gateway' || typeof pending.name !== 'string' || !Number.isFinite(pending.started)
        || !body || typeof body.quote_id !== 'string' || typeof body.wallet !== 'string'
        || typeof body.code !== 'string' || typeof body.message !== 'string'
        || pending.quote?.quote_id !== body.quote_id
        || !Array.isArray(body.signature) || body.signature.length !== 64
        || body.signature.some(byte => !Number.isInteger(byte) || byte < 0 || byte > 255)) return null;
    return pending;
  } catch { return null; }
}
function savePendingAdmission(pending) {
  try { sessionStorage.setItem(PENDING_ADMISSION_KEY, JSON.stringify(pending)); }
  catch { /* The live request continues; recovery is unavailable if its response is lost. */ }
}
function clearPendingAdmission() {
  try { sessionStorage.removeItem(PENDING_ADMISSION_KEY); } catch { /* Tab storage may be unavailable. */ }
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
function formatSol(value) {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toLocaleString('en-US', { maximumFractionDigits: 9 }) : 'Unavailable';
}
function admissionOutcomeIsUncertain(error) {
  const statusCode = error.response?.status;
  return !statusCode || statusCode === 408 || statusCode === 429 || statusCode >= 500;
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

export default function Dashboard({ gatewayHealth, gatewayOnline, workerCount, reviewedSourcesOnly, selection, onBusyChange, onRecord }) {
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
  const [pendingAdmission, setPendingAdmission] = useState(() => readPendingAdmission());
  const [maxCost, setMaxCost] = useState('0.001');
  const [maxRuntime, setMaxRuntime] = useState('30');
  const gatewayOffChain = gatewayHealth?.demo_mode === true;
  const [receipt, setReceipt] = useState(null);
  const [copied, setCopied] = useState(false);
  const [runs, setRuns] = useState([]);
  const [walletBalance, setWalletBalance] = useState(null);
  const [channel, setChannel] = useState(null);
  const [protocolConfig, setProtocolConfig] = useState(null);
  const [depositAmount, setDepositAmount] = useState('0.01');
  const [channelBusy, setChannelBusy] = useState(false);
  const active = useRef(null);
  const pollTimer = useRef(null);
  const controller = useRef(null);
  const inputRef = useRef(null);
  const logRef = useRef(null);
  const followLogs = useRef(true);
  const resultTokens = useRef(new Map());
  const busy = ACTIVE.includes(status);
  const executionReady = gatewayOnline && gatewayHealth?.status === 'ready' && workerCount > 0;
  const progressStep = status === 'idle' ? 0
    : ['reviewing', 'quoted', 'signing', 'submitting', 'uncertain', 'blocked'].includes(status) ? 1
      : ['queued', 'running', 'settlement_pending', 'stopping'].includes(status) ? 2
        : status === 'failed' && !receipt?.backendReceipt ? 1 : 3;

  const refreshChannel = useCallback(async () => {
    if (!publicKey) {
      setWalletBalance(null);
      setChannel(null);
      setProtocolConfig(null);
      return null;
    }
    const { data: health } = await axios.get(API_URL + '/health', { timeout: 10000 });
    if (health.demo_mode === true) {
      setWalletBalance(null); setChannel(null); setProtocolConfig(null);
      return { channel: null, config: null, development: true };
    }
    const [walletResult, channelResult, configResult] = await Promise.allSettled([
      connection.getBalance(publicKey, 'confirmed'),
      axios.get(API_URL + '/balance/' + publicKey.toBase58(), { timeout: 10000 }),
      axios.get(API_URL + '/channel-config', { timeout: 10000 }),
    ]);
    setWalletBalance(walletResult.status === 'fulfilled' ? walletResult.value / LAMPORTS_PER_SOL : null);
    const nextChannel = channelResult.status === 'fulfilled' ? channelResult.value.data : null;
    const nextConfig = configResult.status === 'fulfilled' ? configResult.value.data : null;
    setChannel(nextChannel);
    setProtocolConfig(nextConfig);
    return { channel: nextChannel, config: nextConfig, development: false };
  }, [connection, publicKey]);

  useEffect(() => {
    if (!publicKey) return undefined;
    const refresh = () => refreshChannel().catch(() => { setWalletBalance(null); setChannel(null); setProtocolConfig(null); });
    refresh();
    const timer = setInterval(refresh, 20000);
    return () => clearInterval(timer);
  }, [publicKey, refreshChannel]);

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
      const programId = new PublicKey(state.config.program_id || APERTURE_PROGRAM_ID);
      const [configPda] = PublicKey.findProgramAddressSync([new TextEncoder().encode('config')], programId);
      const [channelPda] = PublicKey.findProgramAddressSync([new TextEncoder().encode('channel'), publicKey.toBytes()], programId);
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
      const programId = new PublicKey(protocolConfig.program_id || APERTURE_PROGRAM_ID);
      const [configPda] = PublicKey.findProgramAddressSync([new TextEncoder().encode('config')], programId);
      const [channelPda] = PublicKey.findProgramAddressSync([new TextEncoder().encode('channel'), publicKey.toBytes()], programId);
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
  useEffect(() => { setQuote(null); setStatus(previous => previous === 'quoted' ? 'idle' : previous); }, [code, publicKey, maxCost, maxRuntime, gatewayOffChain]);
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
    if (logRef.current && followLogs.current) logRef.current.scrollTop = logRef.current.scrollHeight;
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
    if (run.mode === 'gateway') {
      try { sessionStorage.removeItem(ACTIVE_STORAGE_KEY); } catch { /* Tab storage unavailable. */ }
      clearPendingAdmission(); setPendingAdmission(null);
    }
    setStatus(outcome);
    // Local authorization failures have no accepted task or gateway receipt.
    if (!run.token || !/^task-[a-f0-9]{32}$/.test(run.id)) return;
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
        let verification = { verified: false, reason: 'No gateway receipt was returned.' };
        if (run.mode === 'gateway' && data.receipt) {
          try {
            const raw = await axios.get(API_URL + '/download/' + run.id, {
              params: { access_token: run.token }, responseType: 'text', signal: controller.current.signal, timeout: 15000,
            });
            verification = await verifyGatewayReceipt(data.receipt, run.quote, run.id, raw.data);
            if (verification.verified && evidence.settlement_type === 'DEVNET') {
              const chainVerification = await verifyDevnetSettlement(connection, data.receipt, run.quote, run.id);
              verification = { ...verification, ...chainVerification, reason: verification.reason + ' ' + chainVerification.reason };
            }
          } catch (error) {
            verification = { verified: false, reason: 'Receipt or raw output could not be verified: ' + errorMessage(error) };
          }
        }
        if (active.current !== run) return;
        log(outcome === 'completed' ? 'Worker returned a result.' : 'Task ended: ' + outcome + '.', outcome === 'completed' ? 'success' : 'warning');
        if (run.mode === 'gateway') refreshChannel().catch(() => {});
        const displayedOutcome = run.mode === 'gateway' && !verification.verified ? 'unverified' : outcome;
        const proof = evidence.settlement_type === 'DEVNET' && typeof evidence.settlement_signature === 'string'
          ? 'https://explorer.solana.com/tx/' + encodeURIComponent(evidence.settlement_signature) + '?cluster=devnet' : null;
        finish(run, displayedOutcome, { reportedStatus: outcome, output: data.output || '', settlementType: evidence.settlement_type || 'UNKNOWN', proof, costSol: Number.isSafeInteger(evidence.charged_lamports) ? evidence.charged_lamports / LAMPORTS_PER_SOL : null, workerId: evidence.worker_id || null, durationSeconds: evidence.execution_time ?? null, backendReceipt: evidence, chainReceiptAddress: verification.chainReceipt || null, receiptVerified: run.mode === 'gateway' ? verification.verified : null, verificationNote: run.mode === 'gateway' ? verification.reason : null, ...run.estimate });
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
    if (restored && !active.current) {
      clearPendingAdmission(); setPendingAdmission(null);
      const run = { ...restored, offset: 0 };
      active.current = run;
      controller.current = new AbortController();
      setName(run.name); setSampleId('custom');
      setCode('# Active gateway task restored from this browser tab.\n# Original Python source is not stored in the browser.\n# Inspect its source hash in the completed receipt.\n');
      setStatus('queued');
      setNotice('Restored the active gateway task from this browser tab. Monitoring continues; the original source was not saved.');
      monitor(run);
      return () => { clearTimeout(pollTimer.current); controller.current?.abort(); if (active.current === run) active.current = null; };
    }
    const pending = readPendingAdmission();
    if (pending) {
      active.current = { id: 'request-pending', name: pending.name, mode: 'gateway', started: pending.started, offset: 0, estimate: pending.estimate, quote: pending.quote, submitting: true };
      setPendingAdmission(pending);
      setName(pending.name); setSampleId('custom'); setCode(pending.body.code);
      setStatus('uncertain');
      setNotice('A signed workload may already have reached the gateway. Resume the exact saved request to recover its task; no new quote will be created.');
    }
    return undefined;
    // Restore once; monitor owns this run object and never switches task on render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reviewQuote = async () => {
    if (active.current || busy) return;
    if (!publicKey) { setVisible(true); return; }
    setNotice(''); setQuote(null); setStatus('reviewing');
    try {
      validateSource(code);
      const budget = Math.round(Number(maxCost) * LAMPORTS_PER_SOL);
      const runtime = Number(maxRuntime);
      if (!Number.isSafeInteger(budget) || budget < 1 || budget > 1e9 || !Number.isInteger(runtime) || runtime < 1 || runtime > 180) throw new Error('Choose a positive budget up to 1 SOL and a whole runtime from 1 to 180 seconds.');
      const liveState = await refreshChannel();
      const wallet = publicKey.toBase58();
      const { data } = await axios.post(API_URL + '/quotes', { wallet, agent_pubkey: wallet, code, max_cost_lamports: budget, max_runtime_seconds: runtime }, { timeout: 15000 });
      const sourceHash = await sha256Hex(code);
      if (data.wallet !== wallet || data.agent_pubkey !== wallet || data.code_sha256 !== sourceHash || data.max_cost_lamports !== budget || data.max_runtime_seconds !== runtime) throw new Error('The returned quote does not match the source and spending bounds.');
      if (!Number.isSafeInteger(data.rate_lamports) || data.rate_lamports < 1 || data.rate_lamports > budget
          || !Number.isSafeInteger(data.expires_at) || data.expires_at * 1000 <= Date.now() || data.expires_at * 1000 > Date.now() + 120_000
          || !Number.isSafeInteger(data.passport_version) || data.passport_version < 0
          || data.effective_runtime_seconds !== Math.min(runtime, Math.floor(budget / data.rate_lamports))) throw new Error('The returned quote contains invalid rate, expiry, policy or runtime bounds.');
      if (data.program_id !== APERTURE_PROGRAM_ID) throw new Error('The quote program does not match the deployment pinned in this frontend.');
      try { new PublicKey(data.gateway_pubkey); }
      catch { throw new Error('The quote has an invalid gateway signing key.'); }
      if (GATEWAY_PUBKEY_PIN && data.gateway_pubkey !== GATEWAY_PUBKEY_PIN) throw new Error('The quote signer does not match the gateway pinned in this frontend.');
      if (data.network !== (liveState?.development ? 'off_chain' : 'devnet')) throw new Error('The quote network does not match the gateway mode.');
      if (data.network === 'devnet') {
        if (!GATEWAY_PUBKEY_PIN || !TREASURY_PUBKEY_PIN) throw new Error('Pin VITE_APERTURE_GATEWAY_PUBKEY and VITE_APERTURE_TREASURY_PUBKEY before approving Devnet work.');
        if (data.gateway_pubkey !== GATEWAY_PUBKEY_PIN || data.treasury !== TREASURY_PUBKEY_PIN) throw new Error('The quote gateway or treasury does not match this frontend deployment.');
        try { new PublicKey(data.treasury); }
        catch { throw new Error('The quote has an invalid treasury key.'); }
      } else if (data.treasury !== null) throw new Error('The off-chain quote unexpectedly names a treasury.');
      if (data.message !== canonicalQuoteMessage(data)) throw new Error('The signed quote does not match the values shown for approval.');
      setQuote(data); setStatus('quoted');
      setAnalysis({ score: data.analysis?.scores?.final_score ?? data.analysis?.complexity_score ?? 0, rateLamports: data.rate_lamports, description: data.analysis?.reason || 'Gateway source policy accepted this workload.' });
    } catch (error) {
      setStatus(error.response?.status === 403 ? 'blocked' : 'idle');
      setNotice(errorMessage(error));
      if (error.response?.status === 403) log('Gateway policy rejected the source: ' + errorMessage(error), 'warning');
    }
  };

  const resumePendingAdmission = async () => {
    const pending = pendingAdmission;
    if (!pending) return;
    let run = active.current;
    if (run && !(run.submitting && status === 'uncertain')) return;
    if (!run) {
      run = { id: 'request-' + crypto.randomUUID(), name: pending.name, mode: 'gateway', started: pending.started, offset: 0, estimate: pending.estimate, quote: pending.quote, submitting: true };
      active.current = run;
    }
    controller.current = new AbortController();
    setStatus('submitting'); setNotice('Recovering the exact signed request. The gateway will return the same task if it already accepted it.');
    try {
      const { data } = await axios.post(API_URL + '/execute', pending.body, { signal: controller.current.signal, timeout: 15000 });
      if (active.current !== run) return;
      if (!/^task-[a-f0-9]{32}$/.test(data?.task_id || '') || typeof data?.task_access_token !== 'string' || data.task_access_token.length < 32) {
        throw new Error('The gateway response did not include a valid task capability.');
      }
      const recoveredRun = { ...run, id: data.task_id, token: data.task_access_token };
      active.current = recoveredRun;
      saveActiveRun(recoveredRun); clearPendingAdmission(); setPendingAdmission(null);
      setStatus('queued'); setNotice('');
      log('Recovered the exact signed admission. Monitoring the original task.');
      monitor(recoveredRun);
    } catch (error) {
      if (active.current !== run || axios.isCancel(error)) return;
      if (admissionOutcomeIsUncertain(error)) {
        setStatus('uncertain');
        setNotice('The gateway still has not confirmed this signed request. Its exact authorization remains saved in this tab; retry recovery when the connection is available.');
        log('Admission recovery is still uncertain. No new quote was created.', 'warning');
        return;
      }
      clearPendingAdmission(); setPendingAdmission(null);
      active.current = null; controller.current?.abort();
      setStatus('failed');
      setNotice('The gateway rejected the saved request: ' + errorMessage(error) + ' Review a fresh quote before trying again.');
    }
  };

  const start = async () => {
    if (active.current) return;
    if (!executionReady) { setNotice('Execution is not ready. Connect a configured gateway and an authenticated worker before signing.'); return; }
    setNotice('');
    try { validateSource(code); } catch (error) { setNotice(error.message); return; }
    if (!publicKey) { setVisible(true); return; }
    if (!signMessage) { setNotice('This wallet cannot sign messages. Choose a compatible Solana wallet.'); return; }
    {
      if (!quote || quote.expires_at * 1000 <= Date.now()) { setNotice('Review a fresh quote before signing this workload.'); setQuote(null); return; }
      let liveState;
      try { liveState = await refreshChannel(); }
      catch (error) { setNotice('Could not check the Devnet payment channel: ' + errorMessage(error)); return; }
      if (quote.network !== (liveState?.development ? 'off_chain' : 'devnet')) { setNotice('The gateway mode changed after this quote. Review a fresh quote before signing.'); setQuote(null); return; }
      if (!liveState?.development && !liveState?.config?.initialized) { setNotice('The gateway protocol is not configured. Check its Devnet program and authority settings.'); return; }
      if (!liveState?.development && (!liveState?.channel?.initialized || Number(liveState.channel.lamports) < quote.max_cost_lamports)) {
        setNotice('Fund an idle payment channel to cover the full authorized maximum cost before submitting.');
        return;
      }
    }
    const run = { id: 'request-' + crypto.randomUUID(), name, mode: 'gateway', started: Date.now(), offset: 0 };
    active.current = run;
    controller.current = new AbortController();
    followLogs.current = true;
    setLogs([]); setReceipt(null); setStatus('reviewing');
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
      run.estimate = { score: challenge.analysis?.scores?.final_score ?? 0, rateLamports: challenge.rate_lamports };
      run.quote = quoteForReceipt(challenge);
      const pending = { mode: 'gateway', name: run.name, started: run.started, estimate: run.estimate, quote: run.quote, body };
      savePendingAdmission(pending); setPendingAdmission(pending);
      let data;
      try { ({ data } = await axios.post(API_URL + '/execute', body, config)); }
      catch (error) {
        if (axios.isCancel(error)) throw error;
        if (!admissionOutcomeIsUncertain(error)) {
          clearPendingAdmission(); setPendingAdmission(null);
          throw error;
        }
        // The exact signed quote is idempotent; a lost response cannot dispatch twice.
        try { ({ data } = await axios.post(API_URL + '/execute', body, config)); }
        catch (retryError) {
          if (axios.isCancel(retryError)) throw retryError;
          if (!admissionOutcomeIsUncertain(retryError)) {
            clearPendingAdmission(); setPendingAdmission(null);
            throw retryError;
          }
          setStatus('uncertain');
          setNotice('The gateway did not confirm admission. The exact signed request is saved in this tab; recover it before creating another workload.');
          log('Admission response was lost twice. The saved request can recover only this exact quote.', 'warning');
          return;
        }
      }
      if (active.current !== run) return;
      if (!/^task-[a-f0-9]{32}$/.test(data?.task_id || '') || typeof data?.task_access_token !== 'string' || data.task_access_token.length < 32) {
        setStatus('uncertain');
        setNotice('The gateway response was incomplete. The exact signed request is saved in this tab; recover it to check the original task.');
        return;
      }
      run.id = data.task_id; run.token = data.task_access_token;
      saveActiveRun(run);
      clearPendingAdmission(); setPendingAdmission(null);
      setStatus('queued');
      log('Accepted by the gateway. Waiting for an authenticated worker.');
      monitor(run);
    } catch (error) {
      if (active.current !== run) return;
      const uncertainSubmission = run.submitting && admissionOutcomeIsUncertain(error);
      if (uncertainSubmission) {
        setStatus('uncertain');
        setNotice('Submission status is uncertain. The exact signed request remains saved in this tab; recover it before creating another workload.');
        log('The gateway did not confirm the signed admission.', 'warning');
        return;
      }
      clearPendingAdmission(); setPendingAdmission(null);
      const message = errorMessage(error);
      setNotice(message); log(message, 'warning');
      finish(run, error.response?.status === 403 ? 'blocked' : 'failed', { settlementType: 'NONE', output: message });
    }
  };
  const stop = async () => {
    const run = active.current;
    if (!run || !['queued', 'running', 'settlement_pending'].includes(status)) return;
    const previousStatus = status;
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
      setStatus(previousStatus); setNotice('Cancellation was not confirmed: ' + errorMessage(error) + ' Status monitoring continues.');
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
    {reviewedSourcesOnly && <div className="studio-notice" role="status"><Icon name="shield" size={18} /><p>This worker accepts reviewed samples. Edited or imported source needs operator approval before it can run.</p></div>}
    {notice && <div className="studio-notice" role="alert"><Icon name="shield" size={18} /><p>{notice}</p>{pendingAdmission && status === 'uncertain' && <button className="console-button secondary" onClick={resumePendingAdmission}>Recover signed request</button>}</div>}
    <div className="studio-grid">
      <section className="studio-editor">
        <div className="studio-editor-heading"><div><span className="studio-file-dot" /><strong>workload.py</strong><span className="studio-language">PYTHON</span></div><div><button onClick={copyCode} title="Copy source" aria-label={copied ? 'Code copied' : 'Copy code'}><Icon name={copied ? 'check' : 'copy'} size={17} /></button><button onClick={() => inputRef.current.click()} disabled={busy} title="Import Python file" aria-label="Import Python file"><Icon name="upload" size={17} /></button></div></div>
        <div className="studio-presets"><label htmlFor="workload-preset">Sample</label><select id="workload-preset" value={sampleId} disabled={busy} onChange={event => selectSample(WORKLOADS.find(sample => sample.id === event.target.value))}>{WORKLOADS.map(sample => <option value={sample.id} key={sample.id}>{sample.name}</option>)}{sampleId === 'custom' && <option value="custom">Custom workload</option>}</select><button disabled={busy} onClick={() => selectSample(WORKLOADS.find(sample => sample.id === sampleId) || WORKLOADS[0])} title="Reset sample" aria-label="Reset sample"><Icon name="refresh" size={16} /></button></div>
        <div className="studio-source"><textarea aria-label="Python source code" value={code} spellCheck={false} disabled={busy} onChange={event => { setCode(event.target.value); setSampleId('custom'); setName('Custom workload'); setAnalysis(null); setReceipt(null); setStatus('idle'); }} /></div>
        <div className="studio-editor-meta"><span>UTF-8 · {code.split('\n').length} lines</span><span>{new TextEncoder().encode(code).length.toLocaleString()} / 65,536 bytes</span></div>
        <div className="studio-run-bar"><span><Icon name="chip" size={15} />{!gatewayOnline ? 'Gateway offline' : gatewayOffChain ? 'Off-chain worker' : 'Solana Devnet'}</span>{busy ? <button className="console-button secondary" disabled={!['queued', 'running', 'settlement_pending'].includes(status)} onClick={stop}><Icon name="stop" size={16} />{status === 'stopping' ? 'Stopping…' : ['queued', 'running', 'settlement_pending'].includes(status) ? 'Stop run' : 'Please wait…'}</button> : <button className="console-button primary" onClick={quote ? start : reviewQuote} disabled={channelBusy || Boolean(quote && !executionReady)} aria-busy={channelBusy}><Icon name={channelBusy ? 'refresh' : 'play'} size={16} />{channelBusy ? 'Channel transaction…' : !publicKey ? 'Connect wallet' : quote ? executionReady ? 'Accept quote & sign' : 'Execution unavailable' : 'Review price & limits'}</button>}</div>
        <input ref={inputRef} type="file" accept=".py,text/plain" hidden onChange={importFile} />
      </section>
      <aside className="studio-inspector">
        <section className="console-panel studio-status-card" aria-busy={busy}>
          <span className="console-eyebrow">RUN INSPECTOR</span>
          <div
            className={'studio-status-icon ' + status}
            data-busy={busy}
          >
            <Icon
              name={
                status === 'completed'
                  ? 'check'
                  : ['failed', 'blocked', 'unverified'].includes(status)
                    ? 'shield'
                    : busy
                      ? 'refresh'
                      : 'spark'
              }
              size={27}
            />
          </div>
          <h2 aria-live="polite">{LABELS[status]}</h2>
          <p>
            {status === 'idle'
              ? 'Your source, reviewed quote and worker result. Everything in one place.'
              : busy
                ? 'You can explore other pages while this run is active.'
                : 'Review the outcome below or start another experiment.'}
          </p>
          <ol className="studio-steps">
            {['Prepare', 'Review', 'Run', 'Result'].map((step, index) => (
              <li
                key={step}
                className={(index <= progressStep ? 'reached' : '') + (index === progressStep ? ' current' : '')}
                aria-current={index === progressStep ? 'step' : undefined}
              >
                <span>{index + 1}</span>{step}
              </li>
            ))}
          </ol>
        </section>
        <section className="console-panel studio-estimate"><div className="console-section-heading"><h2>Price & spending limit</h2><Icon name="chip" size={18} /></div><dl><div><dt>Source complexity</dt><dd>{analysis ? analysis.score : 'Not quoted'}</dd></div><div><dt>Quoted rate</dt><dd>{analysis ? analysis.rateLamports + ' lamports/s' : 'Not quoted'}</dd></div><div><dt>Settlement</dt><dd>{!gatewayOnline ? 'Gateway offline' : gatewayOffChain ? 'No on-chain payment' : 'Devnet channel'}</dd></div></dl><div className="studio-budget"><label htmlFor="task-max-cost">Maximum cost · SOL<input id="task-max-cost" type="number" min="0.000000001" max="1" step="0.000001" value={maxCost} disabled={busy} onChange={event => setMaxCost(event.target.value)} /></label><label htmlFor="task-max-runtime">Maximum runtime · seconds<input id="task-max-runtime" type="number" min="1" max="180" step="1" value={maxRuntime} disabled={busy} onChange={event => setMaxRuntime(event.target.value)} /></label></div><p>{analysis?.description || 'Request a quote, inspect its limits, then approve it with your wallet.'}</p>{quote && <div className="studio-quote"><strong>Ready for your approval</strong><p>Rate: {quote.rate_lamports / 1e9} SOL/s<br />Maximum charge: {quote.max_cost_lamports / 1e9} SOL<br />Execution limit: {quote.effective_runtime_seconds}s<br />Quote expires: {new Date(quote.expires_at * 1000).toLocaleTimeString()}</p><p>Editing the source, wallet or limits discards this quote. Approval signs this exact source hash and budget.</p><button className="console-button primary" onClick={start} disabled={channelBusy || !executionReady}>Accept quote & sign</button></div>}</section>
        <section className="console-panel studio-channel">
          <div className="console-section-heading"><div><span className="console-eyebrow">{gatewayOffChain ? 'EXECUTION IDENTITY' : 'DEVNET PAYMENT'}</span><h2>{gatewayOffChain ? 'Signed execution' : 'Payment channel'}</h2></div><Icon name={gatewayOffChain ? 'shield' : 'wallet'} size={18} /></div>
          {gatewayOffChain ? <>
            <p className="studio-channel-help">Python executes through the connected worker. This gateway produces signed output with no on-chain payment.</p>
            <dl>
              <div><dt>Your signing key</dt><dd>{publicKey ? publicKey.toBase58().slice(0, 6) + '…' + publicKey.toBase58().slice(-6) : 'Not connected'}</dd></div>
              <div><dt>Gateway signer</dt><dd title={gatewayHealth?.gateway_pubkey}>{gatewayHealth?.gateway_pubkey ? gatewayHealth.gateway_pubkey.slice(0, 6) + '…' + gatewayHealth.gateway_pubkey.slice(-6) : 'Unavailable'}</dd></div>
              <div><dt>Connected workers</dt><dd>{gatewayOnline ? workerCount : 'Unavailable'}</dd></div>
              <div><dt>On-chain charge</dt><dd>None</dd></div>
            </dl>
            {!publicKey && <button className="console-button primary studio-channel-action" onClick={() => setVisible(true)}>Connect signing key<Icon name="arrow" size={16} /></button>}
          </> : publicKey ? <>
            <p className="studio-channel-wallet">Wallet · {publicKey.toBase58().slice(0, 5)}…{publicKey.toBase58().slice(-5)}</p>
            <dl>
              <div><dt>Wallet balance</dt><dd>{walletBalance === null ? 'Unavailable' : formatSol(walletBalance) + ' SOL'}</dd></div>
              <div><dt>Channel balance</dt><dd>{channel?.balance == null ? 'Unavailable' : formatSol(channel.balance) + ' SOL'}</dd></div>
              <div><dt>Protocol</dt><dd>{protocolConfig?.initialized ? 'Configured' : 'Unavailable'}</dd></div>
            </dl>
            <label className="studio-channel-label" htmlFor="channel-deposit">Deposit amount</label>
            <div className="studio-channel-deposit">
              <input id="channel-deposit" inputMode="decimal" type="number" min="0.000000001" step="0.01" value={depositAmount} disabled={busy || channelBusy} onChange={event => setDepositAmount(event.target.value)} />
              <span>SOL</span>
            </div>
            <button className="console-button primary studio-channel-action" onClick={handleDeposit} disabled={busy || channelBusy || !sendTransaction || !protocolConfig?.initialized} aria-busy={channelBusy}>
              <Icon name={channelBusy ? 'refresh' : 'wallet'} size={16} />{channelBusy ? 'Waiting for Devnet…' : channel?.initialized ? 'Add to channel' : 'Open & fund channel'}
            </button>
            {channel?.initialized && <button className="console-text-button studio-channel-close" onClick={handleCloseChannel} disabled={busy || channelBusy || Number(channel.burn_rate_lamports) > 0}>
              Close channel and refund remaining SOL<Icon name="arrow" size={15} />
            </button>}
            {!protocolConfig?.initialized && <p className="studio-channel-help">The gateway must be deployed and its protocol configuration initialized before the channel can be opened.</p>}
            {protocolConfig?.initialized && !channel?.initialized && <p className="studio-channel-help">Your wallet will sign a Devnet transaction to open this channel.</p>}
          </> : <>
            <p className="studio-channel-help">Connect a Solana wallet to view your Devnet balance, open a payment channel and submit a live workload.</p>
            <button className="console-button primary studio-channel-action" onClick={() => setVisible(true)}>Connect wallet<Icon name="arrow" size={16} /></button>
          </>}
        </section>
      </aside>
    </div>
    <section className="studio-terminal"><div className="studio-terminal-heading"><span><Icon name="code" size={18} />Run output<span className="studio-terminal-count">{logs.length} events</span></span><button className="console-text-button" disabled={!logs.length} onClick={() => saveFile('aperture-output.txt', logs.map(entry => '[' + entry.time + '] ' + entry.message).join('\n'))}><Icon name="download" size={16} />Save log</button></div><div className="studio-log" ref={logRef} onScroll={event => { const element = event.currentTarget; followLogs.current = element.scrollHeight - element.scrollTop - element.clientHeight < 32; }} role="log" aria-label="Run output" aria-live="polite" aria-atomic="false">{logs.length ? logs.map((entry, index) => <div className={'studio-log-line ' + entry.kind} key={index}><time>{entry.time}</time><span>{entry.message}</span></div>) : <div className="studio-terminal-empty"><span>›</span> Your run output will appear here.</div>}</div></section>
    {receipt && (
      <section className="console-panel studio-receipt">
        <div className="console-section-heading">
          <div><span className="console-eyebrow">WORKLOAD RESULT</span><h2>{receipt.name}</h2></div>
          <span className={'console-tag ' + (['failed', 'blocked', 'unverified'].includes(receipt.status) ? 'error' : receipt.status === 'cancelled' ? 'neutral' : '')}>{LABELS[receipt.status] || receipt.status}</span>
        </div>
        <div className="studio-receipt-details">
          <div><span>Settlement report</span><strong>{receipt.settlementType}</strong></div>
          <div><span>Reported runtime</span><strong>{receipt.durationSeconds == null ? 'Unavailable' : receipt.durationSeconds + 's'}</strong></div>
          <div><span>Reported charge</span><strong>{receipt.settlementType === 'OFF_CHAIN' ? 'No on-chain payment' : receipt.costSol == null ? 'Not confirmed' : formatSol(receipt.costSol) + ' SOL'}</strong></div>
        </div>
        {receipt.output && <pre>{receipt.output}</pre>}
        {receipt.backendReceipt && (
          <>
            <dl className="studio-receipt-evidence">
              {[
                ['Worker', receipt.backendReceipt.worker_id], ['Exit code', receipt.backendReceipt.exit_code],
                ['Execution boundary', receipt.backendReceipt.execution_backend], ['Agent public key', receipt.backendReceipt.agent_pubkey],
                ['Source SHA-256', receipt.backendReceipt.code_sha256], ['Raw output SHA-256', receipt.backendReceipt.output_sha256],
                ['Worker signature', receipt.backendReceipt.worker_signature], ['Receipt hash', receipt.backendReceipt.receipt_sha256],
                ...(receipt.chainReceiptAddress ? [['On-chain task receipt', receipt.chainReceiptAddress]] : []),
              ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? 'Unavailable'}</dd></div>)}
            </dl>
            <p className="studio-channel-help">
              {receipt.status === 'unverified' && `Gateway-reported outcome: ${LABELS[receipt.reportedStatus] || receipt.reportedStatus}. `}
              {receipt.verificationNote || 'Receipt signatures and chain state were not independently verified.'}
            </p>
          </>
        )}
        <div className="studio-receipt-actions">
          <button className="console-button secondary" onClick={() => saveFile('aperture-' + receipt.taskId + '.json', JSON.stringify(receipt.backendReceipt || receipt, null, 2), 'application/json')}><Icon name="download" size={16} />Download receipt</button>
          {receipt.mode === 'gateway' && <button className="console-text-button" onClick={downloadRaw}><Icon name="download" size={16} />Download raw output</button>}
          {receipt.proof && /^https:\/\/explorer\.solana\.com\/tx\//.test(receipt.proof) && <a className="console-text-button" href={receipt.proof} target="_blank" rel="noreferrer">View Devnet transaction<Icon name="external" size={16} /></a>}
        </div>
      </section>
    )}
    {runs.length > 1 && <section className="console-panel studio-history"><h2>This session</h2>{runs.map(run => <button key={run.taskId} onClick={() => setReceipt(run)} disabled={busy}><span><Icon name="chip" size={16} />{run.name}</span><span>Gateway · {run.status}<Icon name="arrow" size={16} /></span></button>)}</section>}
  </div>;
}
