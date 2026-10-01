import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import { LAMPORTS_PER_SOL, PublicKey, SystemProgram, Transaction, TransactionInstruction } from '@solana/web3.js';
import Icon from './components/Icon';
import ResultFiles from './components/ResultFiles';
import { APERTURE_PROGRAM_ID, GATEWAY_PUBKEY_PIN, TREASURY_PUBKEY_PIN, QUOTE_MESSAGE_KEYS, canonicalQuoteMessage, sha256Hex, verifyGatewayReceipt, verifyDevnetSettlement } from './utils/protocol';
import { MAX_SOURCE_BYTES, WORKLOADS, validateSource, resultStatus } from './utils/workloads';
import { requestErrorMessage as errorMessage } from './utils/requestError';
import { saveFile } from './utils/downloadFile';
import { MAX_INPUT_BYTES, hashBytes, jobManifest, uploadInput, validateObject, verifyJobManifest } from './utils/jobs';
import { verifyUserSignature, workflowContext, workflowRequest } from './utils/browserWorkflows';
import './Dashboard.css';

const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const ACTIVE = ['uploading', 'reviewing', 'signing', 'submitting', 'uncertain', 'retryable', 'queued', 'running', 'settlement_pending', 'verifying', 'stopping'];
const LABELS = { idle: 'Ready when you are', quoted: 'Review your spending limit', reviewing: 'Requesting a quote', signing: 'Waiting for signature', submitting: 'Submitting workload', uncertain: 'Submission status uncertain', retryable: 'Waiting to retry admission', queued: 'Waiting for a worker', running: 'Workload in progress', settlement_pending: 'Result saved · settlement pending', verifying: 'Verifying the saved result', stopping: 'Requesting cancellation', completed: 'Run completed', unverified: 'Receipt unverified', blocked: 'Source policy blocked', failed: 'Run failed', cancelled: 'Run cancelled' };
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
  try {
    sessionStorage.setItem(ACTIVE_STORAGE_KEY, JSON.stringify({ id: run.id, token: run.token, mode: run.mode, name: run.name, started: run.started, offset: run.offset, estimate: run.estimate, quote: run.quote, terminal: Boolean(run.terminal) }));
    return true;
  } catch { return false; }
}
function quoteForReceipt(quote) {
  return Object.fromEntries([...QUOTE_MESSAGE_KEYS, 'effective_runtime_seconds', ...(quote.workload ? ['workload', 'workload_sha256', 'workload_canonical'] : [])].map(key => [key, quote[key]]));
}
async function verifyReturnedReceipt(receipt, quote, taskId, token, connection, signal) {
  const raw = await axios.get(API_URL + '/download/' + taskId, {
    headers: { 'X-Aperture-Task-Token': token }, responseType: 'text', signal, timeout: 15000,
  });
  const verification = await verifyGatewayReceipt(receipt, quote, taskId, raw.data);
  if (!verification.verified || receipt.settlement_type !== 'DEVNET') return { ...verification, verifiedOutput: verification.verified ? raw.data : null };
  const chainVerification = await verifyDevnetSettlement(connection, receipt, quote, taskId);
  return { ...verification, ...chainVerification, verifiedOutput: chainVerification.verified ? raw.data : null, reason: verification.reason + ' ' + chainVerification.reason };
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
    const restored = { ...pending };
    if (restored.admission_state !== 'rate_limited' || typeof restored.admission_detail !== 'string') {
      delete restored.admission_state;
      delete restored.admission_detail;
    } else {
      restored.admission_detail = restored.admission_detail.slice(0, 240);
    }
    return restored;
  } catch { return null; }
}
function savePendingAdmission(pending) {
  try {
    sessionStorage.setItem(PENDING_ADMISSION_KEY, JSON.stringify(pending));
  } catch {
    throw new Error('Private tab storage could not save this signed request. Allow tab storage before submitting or recovering it.');
  }
}
function clearPendingAdmission() {
  try { sessionStorage.removeItem(PENDING_ADMISSION_KEY); } catch { /* Tab storage may be unavailable. */ }
}

function formatSol(value) {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toLocaleString('en-US', { maximumFractionDigits: 9 }) : 'Unavailable';
}
function validateDatasetInputs(sampleId, spec) {
  if (sampleId !== 'dataset') return;
  const inputName = spec?.parameters?.input_name;
  if (typeof inputName !== 'string' || !spec?.inputs.some(item => item.name === inputName)) throw new Error('Upload the CSV dataset and set parameters.input_name to its exact filename before reviewing or signing this sample.');
}
function admissionOutcomeIsUncertain(error) {
  const statusCode = error.response?.status;
  return !statusCode || statusCode === 408 || statusCode >= 500;
}
function admissionWasRateLimited(error) {
  return error.response?.status === 429;
}
function rateLimitNotice(detail) {
  return detail + ' This attempt was rate limited. The exact signed authorization is saved in this tab; retry it to recover the original admission.';
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

export default function Dashboard({ gatewayHealth, gatewayOnline, workerCount, reviewedSourcesOnly, selection, releasedObject, onBusyChange, onRecord, externalBusy = false }) {
  const { publicKey, signMessage, sendTransaction, wallet, connect, connecting } = useWallet();
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
  const [dataJob, setDataJob] = useState(Boolean(WORKLOADS[0].dataJob));
  const [dataInputs, setDataInputs] = useState([]);
  const [parametersText, setParametersText] = useState(JSON.stringify(WORKLOADS[0].parameters || {}, null, 2));
  const gatewayOffChain = gatewayHealth?.demo_mode === true;
  const [receipt, setReceipt] = useState(null);
  const [verificationBusy, setVerificationBusy] = useState(false);
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
  const dataInputRef = useRef(null);
  const uploadController = useRef(null);
  const uploadGeneration = useRef(0);
  const quoteReviewController = useRef(null);
  const draftRevision = useRef(0);
  const inputReferences = useRef(new Map());
  const handledRelease = useRef(null);
  const walletIdentity = publicKey?.toBase58() || null;
  const currentIdentity = useRef(walletIdentity);
  const otherFlowBusy = useRef(externalBusy);
  const logRef = useRef(null);
  const followLogs = useRef(true);
  const resultAccess = useRef(new Map());
  const verificationController = useRef(null);
  const busy = ACTIVE.includes(status) || verificationBusy;
  const draftLocked = busy || externalBusy;
  const executionReady = gatewayOnline && gatewayHealth?.status === 'ready' && workerCount > 0;
  let resultFiles = [];
  let invalidResultFiles = false;
  if (receipt?.backendReceipt && Object.hasOwn(receipt.backendReceipt, 'artifacts')) {
    try {
      const files = receipt.backendReceipt.artifacts;
      if (!Array.isArray(files) || files.length > 16) throw new Error('Invalid result file list.');
      files.forEach(item => validateObject(item, 8 * 1024 * 1024));
      if (new Set(files.map(item => item.name.toLowerCase())).size !== files.length || files.reduce((sum, item) => sum + item.size_bytes, 0) > 16 * 1024 * 1024) throw new Error('Invalid result file bounds.');
      resultFiles = files;
    } catch { invalidResultFiles = true; }
  }
  const progressStep = status === 'idle' ? 0
    : ['reviewing', 'quoted', 'signing', 'submitting', 'uncertain', 'retryable', 'blocked'].includes(status) ? 1
      : ['queued', 'running', 'settlement_pending', 'stopping'].includes(status) ? 2
        : status === 'failed' && !receipt?.backendReceipt ? 1 : 3;

  const connectWallet = async () => {
    if (!wallet) { setVisible(true); return; }
    try { await connect(); }
    catch (error) { setNotice('Wallet connection failed: ' + errorMessage(error)); }
  };

  const refreshChannel = useCallback(async () => {
    if (!publicKey) {
      setWalletBalance(null);
      setChannel(null);
      setProtocolConfig(null);
      return null;
    }
    const owner = publicKey.toBase58();
    const { data: health } = await axios.get(API_URL + '/health', { timeout: 10000 });
    if (currentIdentity.current !== owner) throw new Error('The signing identity changed while checking the payment channel.');
    if (health.demo_mode === true) {
      setWalletBalance(null); setChannel(null); setProtocolConfig(null);
      return { channel: null, config: null, development: true };
    }
    const [walletResult, channelResult, configResult] = await Promise.allSettled([
      connection.getBalance(publicKey, 'confirmed'),
      axios.get(API_URL + '/balance/' + publicKey.toBase58(), { timeout: 10000 }),
      axios.get(API_URL + '/channel-config', { timeout: 10000 }),
    ]);
    if (currentIdentity.current !== owner) throw new Error('The signing identity changed while checking the payment channel.');
    setWalletBalance(walletResult.status === 'fulfilled' ? walletResult.value / LAMPORTS_PER_SOL : null);
    const nextChannel = channelResult.status === 'fulfilled' ? channelResult.value.data : null;
    const nextConfig = configResult.status === 'fulfilled' ? configResult.value.data : null;
    setChannel(nextChannel);
    setProtocolConfig(nextConfig);
    return { channel: nextChannel, config: nextConfig, development: false };
  }, [connection, publicKey]);

  useEffect(() => {
    if (!publicKey) return undefined;
    const owner = publicKey.toBase58();
    const refresh = () => refreshChannel().catch(() => { if (currentIdentity.current === owner) { setWalletBalance(null); setChannel(null); setProtocolConfig(null); } });
    refresh();
    const timer = setInterval(refresh, 20000);
    return () => clearInterval(timer);
  }, [publicKey, refreshChannel]);

  const submitChannelInstruction = async (instruction) => {
    if (otherFlowBusy.current) throw new Error('An agent workflow is using the execution slot. Finish or stop it before changing channel funds.');
    const transaction = new Transaction().add(instruction);
    const latest = await connection.getLatestBlockhash('confirmed');
    if (otherFlowBusy.current) throw new Error('An agent workflow is using the execution slot. Finish or stop it before changing channel funds.');
    transaction.feePayer = publicKey;
    transaction.recentBlockhash = latest.blockhash;
    const signature = await sendTransaction(transaction, connection);
    const confirmation = await connection.confirmTransaction({ ...latest, signature }, 'confirmed');
    if (confirmation.value.err) throw new Error('Transaction failed: ' + JSON.stringify(confirmation.value.err));
    return signature;
  };

  const handleDeposit = async () => {
    if (otherFlowBusy.current || busy || channelBusy) return;
    const amount = Number(depositAmount);
    const lamportsNumber = Math.round(amount * LAMPORTS_PER_SOL);
    if (!Number.isFinite(amount) || amount <= 0 || !Number.isSafeInteger(lamportsNumber)) {
      setNotice('Enter a valid SOL amount that fits safely in a transaction.');
      return;
    }
    if (!publicKey || !sendTransaction) { await connectWallet(); return; }
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
    if (otherFlowBusy.current) return;
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
  useLayoutEffect(() => {
    otherFlowBusy.current = externalBusy;
    if (!externalBusy) return;
    const interruptedUpload = uploadController.current;
    const interruptedReview = quoteReviewController.current;
    if (interruptedUpload) {
      uploadGeneration.current += 1;
      interruptedUpload.abort();
      uploadController.current = null;
    }
    if (interruptedReview) {
      draftRevision.current += 1;
      interruptedReview.abort();
      quoteReviewController.current = null;
      setQuote(null);
    }
    if (interruptedUpload || interruptedReview) {
      setStatus(previous => !active.current && ['uploading', 'reviewing'].includes(previous) ? 'idle' : previous);
      setNotice('An agent workflow is using the execution slot. Draft preparation paused; completed uploads are retained.');
    }
  }, [externalBusy]);
  useLayoutEffect(() => {
    draftRevision.current += 1;
    quoteReviewController.current?.abort();
    quoteReviewController.current = null;
    setQuote(null);
    setStatus(previous => previous === 'quoted' || previous === 'reviewing' && !active.current ? 'idle' : previous);
  }, [code, walletIdentity, maxCost, maxRuntime, gatewayOffChain, dataJob, dataInputs, parametersText]);
  useLayoutEffect(() => {
    currentIdentity.current = walletIdentity;
    setWalletBalance(null); setChannel(null); setProtocolConfig(null);
    uploadGeneration.current += 1;
    const interrupted = uploadController.current;
    uploadController.current = null;
    interrupted?.abort();
    setDataInputs(inputReferences.current.get(walletIdentity) || []);
    if (interrupted) {
      setStatus(previous => previous === 'uploading' ? 'idle' : previous);
      setNotice('Input upload stopped because the signing identity changed. Completed uploads are retained for their original identity.');
    }
  }, [walletIdentity]);
  useLayoutEffect(() => {
    if (!releasedObject || handledRelease.current === releasedObject
        || releasedObject.api_url !== API_URL || releasedObject.gateway_pubkey !== gatewayHealth?.gateway_pubkey
        || releasedObject.program_id !== gatewayHealth?.program_id
        || releasedObject.network !== (gatewayOffChain ? 'off_chain' : 'devnet')) return;
    handledRelease.current = releasedObject;
    const cached = inputReferences.current.get(releasedObject.owner);
    if (cached) inputReferences.current.set(releasedObject.owner, cached.filter(item => item.descriptor.object_id !== releasedObject.object_id));
    if (walletIdentity !== releasedObject.owner || !dataInputs.some(item => item.descriptor.object_id === releasedObject.object_id)) return;
    uploadGeneration.current += 1;
    uploadController.current?.abort();
    uploadController.current = null;
    draftRevision.current += 1;
    quoteReviewController.current?.abort();
    quoteReviewController.current = null;
    setDataInputs(previous => previous.filter(item => item.descriptor.object_id !== releasedObject.object_id));
    setQuote(null); setAnalysis(null);
    setStatus(previous => !active.current && ['quoted', 'reviewing', 'uploading'].includes(previous) ? 'idle' : previous);
    setNotice('A released file was removed from these job inputs. Choose a retained input before reviewing a new quote.');
  }, [releasedObject, walletIdentity, gatewayHealth?.gateway_pubkey, gatewayHealth?.program_id, gatewayOffChain, dataInputs]);
  useEffect(() => {
    if (!quote) return undefined;
    const timer = setTimeout(() => { setQuote(null); setStatus(previous => previous === 'quoted' ? 'idle' : previous); setNotice('Quote expired. Review a fresh quote before signing.'); }, Math.max(0, quote.expires_at * 1000 - Date.now()));
    return () => clearTimeout(timer);
  }, [quote]);
  useEffect(() => {
    if (selection && !active.current && !verificationController.current && !otherFlowBusy.current) {
      setCode(selection.code); setName(selection.name); setSampleId(selection.id);
      setDataJob(Boolean(selection.dataJob)); setParametersText(JSON.stringify(selection.parameters || {}, null, 2));
      setStatus('idle'); setNotice(''); setAnalysis(null); setReceipt(null);
    }
  }, [selection]);
  useEffect(() => {
    if (logRef.current && followLogs.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);
  useEffect(() => {
    const warn = event => { if (active.current || verificationController.current) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => { window.removeEventListener('beforeunload', warn); clearTimeout(pollTimer.current); controller.current?.abort(); verificationController.current?.abort(); uploadController.current?.abort(); quoteReviewController.current?.abort(); active.current = null; };
  }, []);

  const log = (message, kind = 'info') => setLogs(previous => [...previous, { message, kind, time: new Date().toLocaleTimeString([], { hour12: false }) }].slice(-500));
  const selectSample = sample => {
    if (active.current || verificationController.current || otherFlowBusy.current) return;
    setCode(sample.code); setName(sample.name); setSampleId(sample.id);
    setDataJob(Boolean(sample.dataJob)); setParametersText(JSON.stringify(sample.parameters || {}, null, 2));
    setStatus('idle'); setAnalysis(null); setReceipt(null); setNotice('');
  };
  const finish = (run, outcome, details = {}) => {
    if (active.current !== run) return;
    clearTimeout(pollTimer.current);
    controller.current?.abort();
    active.current = null;
    if (run.token) {
      resultAccess.current.set(run.id, { token: run.token, quote: run.quote });
      while (resultAccess.current.size > 20) resultAccess.current.delete(resultAccess.current.keys().next().value);
    }
    if (run.mode === 'gateway' && run.token) {
      // Retain the latest accepted task so a reload can verify and reopen its files.
      run.terminal = true;
      if (saveActiveRun(run)) { clearPendingAdmission(); setPendingAdmission(null); }
      else setNotice('This tab could not save the finished task. Download the files you need before closing it; its original signed request remains available if previously saved.');
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
      const response = await axios.get(API_URL + '/stream_log/' + run.id, { params: { offset: run.offset }, headers: { 'X-Aperture-Task-Token': run.token }, signal: controller.current.signal, timeout: 8000 });
      if (active.current !== run) return;
      const data = response.data;
      (data.lines || []).forEach(chunk => chunk.split('\n').filter(Boolean).forEach(line => log(line, 'output')));
      run.offset = data.next_offset ?? run.offset;
      saveActiveRun(run);
      if (['queued', 'running', 'settlement_pending'].includes(data.task_status)) setStatus(data.task_status);
      if (run.retries && !run.verifying) { setNotice(''); run.retries = 0; log('Connection restored.'); }
      if (data.is_completed) {
        run.verifying = true;
        setStatus('verifying');
        const outcome = resultStatus(data.output, data.receipt);
        const evidence = data.receipt || {};
        let verification = { verified: false, reason: 'No gateway receipt was returned.' };
        if (run.mode === 'gateway' && data.receipt) {
          try {
            verification = await verifyReturnedReceipt(data.receipt, run.quote, run.id, run.token, connection, controller.current.signal);
          } catch (error) {
            if (axios.isCancel(error)) throw error;
            if (axios.isAxiosError(error) && (admissionOutcomeIsUncertain(error) || admissionWasRateLimited(error)) && (run.verificationRetries || 0) < 2) {
              run.verificationRetries = (run.verificationRetries || 0) + 1;
              throw error;
            }
            verification = { verified: false, reason: 'Receipt or raw output could not be verified: ' + errorMessage(error) };
          }
        }
        if (active.current !== run) return;
        setNotice('');
        if (run.retries && verification.verified) log('Result verification recovered.', 'success');
        log(outcome === 'completed' ? 'Worker returned a result.' : 'Task ended: ' + outcome + '.', outcome === 'completed' ? 'success' : 'warning');
        if (run.mode === 'gateway') refreshChannel().catch(() => {});
        const displayedOutcome = run.mode === 'gateway' && !verification.verified ? 'unverified' : outcome;
        const proof = evidence.settlement_type === 'DEVNET' && typeof evidence.settlement_signature === 'string'
          ? 'https://explorer.solana.com/tx/' + encodeURIComponent(evidence.settlement_signature) + '?cluster=devnet' : null;
        finish(run, displayedOutcome, { reportedStatus: outcome, output: verification.verified ? verification.verifiedOutput : data.output || '', settlementType: evidence.settlement_type || 'UNKNOWN', proof, costSol: Number.isSafeInteger(evidence.charged_lamports) ? evidence.charged_lamports / LAMPORTS_PER_SOL : null, workerId: evidence.worker_id || null, durationSeconds: evidence.execution_time ?? null, backendReceipt: evidence, chainReceiptAddress: verification.chainReceipt || null, receiptVerified: run.mode === 'gateway' ? verification.verified : null, verificationNote: run.mode === 'gateway' ? verification.reason : null, ...run.estimate });
        return;
      }
    } catch (error) {
      if (active.current !== run || axios.isCancel(error)) return;
      run.retries = (run.retries || 0) + 1;
      setNotice(run.verifying
        ? 'The gateway saved the result. Retrying its verification after a connection interruption.'
        : 'Connection interrupted. Retrying status updates. The task may still be running on the gateway.');
    } finally {
      run.polling = false;
    }
    if (active.current === run) pollTimer.current = setTimeout(() => monitor(run), Math.min(8000, 1000 * 2 ** (run.retries || 0)));
  };

  useEffect(() => {
    const pending = readPendingAdmission();
    const accepted = readActiveRun();
    // A newly signed request takes priority over an older completed task.
    const restored = pending && accepted && pending.body.quote_id !== accepted.quote?.quote_id && pending.started >= accepted.started ? null : accepted;
    if (restored && !active.current) {
      clearPendingAdmission(); setPendingAdmission(null);
      const run = { ...restored, offset: 0 };
      active.current = run;
      controller.current = new AbortController();
      setName(run.name); setSampleId('custom');
      setCode('# Saved gateway task restored from this browser tab.\n# Original Python source is not stored in this checkpoint.\n# Inspect its source hash in the verified receipt.\n');
      setStatus('queued');
      setNotice(run.terminal ? 'Restoring the latest saved result. Its receipt and output will be verified again before files can be opened.' : 'Restored the active gateway task from this browser tab. Monitoring continues; the original source was not saved.');
      monitor(run);
      return () => { clearTimeout(pollTimer.current); controller.current?.abort(); if (active.current === run) active.current = null; };
    }
    if (pending) {
      active.current = { id: 'request-pending', name: pending.name, mode: 'gateway', started: pending.started, offset: 0, estimate: pending.estimate, quote: pending.quote, submitting: true };
      setPendingAdmission(pending);
      setName(pending.name); setSampleId('custom'); setCode(pending.body.code);
      const wasRateLimited = pending.admission_state === 'rate_limited';
      setStatus(wasRateLimited ? 'retryable' : 'uncertain');
      setNotice(wasRateLimited
        ? rateLimitNotice(pending.admission_detail || 'Gateway admission was rate limited or at capacity.')
        : 'A signed workload may already have reached the gateway. Resume the exact saved request to recover its task; no new quote will be created.');
    }
    return undefined;
    // Restore once; monitor owns this run object and never switches task on render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reviewQuote = async () => {
    if (active.current || busy || otherFlowBusy.current) return;
    if (!publicKey) { await connectWallet(); return; }
    const wallet = publicKey.toBase58();
    const revision = draftRevision.current;
    const attempt = new AbortController();
    quoteReviewController.current?.abort();
    quoteReviewController.current = attempt;
    const current = () => !attempt.signal.aborted && !otherFlowBusy.current && quoteReviewController.current === attempt && currentIdentity.current === wallet && draftRevision.current === revision;
    setNotice(''); setQuote(null); setStatus('reviewing');
    try {
      validateSource(code);
      const budget = Math.round(Number(maxCost) * LAMPORTS_PER_SOL);
      const runtime = Number(maxRuntime);
      if (!Number.isSafeInteger(budget) || budget < 1 || budget > 1e9 || !Number.isInteger(runtime) || runtime < 1 || runtime > 180) throw new Error('Choose a positive budget up to 1 SOL and a whole runtime from 1 to 180 seconds.');
      const liveState = await refreshChannel();
      if (!current()) return;
      const spec = dataJob ? await jobManifest(code, dataInputs.map(item => item.descriptor), parametersText) : null;
      if (!current()) return;
      validateDatasetInputs(sampleId, spec);
      if (dataInputs.some(item => item.owner !== wallet)) throw new Error('Input files belong to a different signing identity. Upload them again.');
      const { data } = await axios.post(API_URL + '/quotes', { wallet, agent_pubkey: wallet, code, max_cost_lamports: budget, max_runtime_seconds: runtime, ...(spec ? { job_version: 1, inputs: spec.inputs, parameters: spec.parameters } : {}) }, { timeout: 15000, signal: attempt.signal });
      if (!current()) return;
      const sourceHash = await sha256Hex(code);
      if (!current()) return;
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
      if (spec) await verifyJobManifest(data, spec);
      else if (data.workload) throw new Error('The quote added an unrequested data job.');
      if (!current()) return;
      setQuote(data); setStatus('quoted');
      setAnalysis({ score: data.analysis?.scores?.final_score ?? data.analysis?.complexity_score ?? 0, rateLamports: data.rate_lamports, description: data.analysis?.reason || 'Gateway source policy accepted this workload.' });
    } catch (error) {
      if (!current() || axios.isCancel(error)) return;
      setStatus(error.response?.status === 403 ? 'blocked' : 'idle');
      setNotice(errorMessage(error));
      if (error.response?.status === 403) log('Gateway policy rejected the source: ' + errorMessage(error), 'warning');
    } finally {
      if (quoteReviewController.current === attempt) {
        quoteReviewController.current = null;
        setStatus(previous => previous === 'reviewing' ? 'idle' : previous);
      }
    }
  };

  const resumePendingAdmission = async () => {
    if (!pendingAdmission) return;
    if (otherFlowBusy.current) {
      setNotice('An agent workflow is using the execution slot. The exact signed admission remains saved; finish or stop the workflow before retrying it.');
      return;
    }
    const pending = {
      mode: pendingAdmission.mode, name: pendingAdmission.name, started: pendingAdmission.started,
      estimate: pendingAdmission.estimate, quote: pendingAdmission.quote, body: pendingAdmission.body,
    };
    try { savePendingAdmission(pending); }
    catch (error) { setNotice(error.message + ' The previous recovery checkpoint remains available.'); return; }
    setPendingAdmission(pending);
    let run = active.current;
    if (run && !(run.submitting && ['uncertain', 'retryable'].includes(status))) return;
    if (!run) {
      run = { id: 'request-' + crypto.randomUUID(), name: pending.name, mode: 'gateway', started: pending.started, offset: 0, estimate: pending.estimate, quote: pending.quote, submitting: true };
      active.current = run;
    }
    controller.current = new AbortController();
    setStatus('submitting'); setNotice('Recovering the exact signed request. The gateway will return the same task if it already accepted it.');
    let admissionAttempted = false;
    try {
      if (currentIdentity.current !== pending.body.wallet) throw new Error('Reconnect the original signing wallet before recovering its saved admission.');
      const health = await workflowRequest({ api_url: API_URL }, '/health', { signal: controller.current.signal });
      const context = workflowContext(API_URL, pending.body.wallet, health);
      if (['program_id', 'gateway_pubkey', 'treasury', 'network'].some(key => pending.quote[key] !== context[key])
          || pending.quote.wallet !== pending.body.wallet || pending.quote.agent_pubkey !== pending.body.wallet
          || pending.body.agent_pubkey !== pending.body.wallet || pending.body.quote_id !== pending.quote.quote_id
          || pending.body.message !== canonicalQuoteMessage(pending.quote)
          || pending.quote.code_sha256 !== await sha256Hex(pending.body.code)) throw new Error('The retained authorization differs from its source or the current gateway. Restore the original deployment before recovering it.');
      if (pending.quote.workload) {
        if (pending.body.job_version !== 1) throw new Error('The saved data job is incomplete. Keep its checkpoint.');
        const spec = await jobManifest(pending.body.code, pending.body.inputs, JSON.stringify(pending.body.parameters));
        await verifyJobManifest(pending.quote, spec);
      }
      await verifyUserSignature(pending.body.wallet, Uint8Array.from(pending.body.signature), pending.body.message);
      if (active.current !== run || currentIdentity.current !== pending.body.wallet || otherFlowBusy.current) throw new Error('The signing wallet or active execution changed during recovery. Its checkpoint is retained.');
      admissionAttempted = true;
      const { data } = await axios.post(API_URL + '/execute', pending.body, { signal: controller.current.signal, timeout: 15000 });
      if (active.current !== run) return;
      if (!/^task-[a-f0-9]{32}$/.test(data?.task_id || '') || typeof data?.task_access_token !== 'string' || data.task_access_token.length < 32) {
        throw new Error('The gateway response did not include a valid task capability.');
      }
      const recoveredRun = { ...run, id: data.task_id, token: data.task_access_token };
      active.current = recoveredRun;
      if (saveActiveRun(recoveredRun)) { clearPendingAdmission(); setPendingAdmission(null); }
      else setNotice('The gateway confirmed the task, but this tab could not save its capability. The original signed request remains retained; keep this tab open.');
      setStatus('queued');
      log('Recovered the exact signed admission. Monitoring the original task.');
      monitor(recoveredRun);
    } catch (error) {
      if (active.current !== run || axios.isCancel(error)) return;
      if (!admissionAttempted) {
        setStatus('uncertain');
        setNotice('Recovery paused: ' + errorMessage(error) + ' The original signed request is retained; no admission was attempted.');
        return;
      }
      if (admissionWasRateLimited(error)) {
        retainRateLimitedAdmission(pending, error);
        return;
      }
      if (admissionOutcomeIsUncertain(error)) {
        setStatus('uncertain');
        setNotice('The gateway still has not confirmed this signed request. Its exact authorization remains saved in this tab; retry recovery when the connection is available.');
        log('Admission recovery is still uncertain. No new quote was created.', 'warning');
        return;
      }
      setStatus('uncertain');
      setNotice('Recovery was rejected: ' + errorMessage(error) + ' The original authorization is retained. Restore its gateway configuration before recovering; do not replace a potentially accepted task.');
    }
  };

  const retainRateLimitedAdmission = (pending, error) => {
    const retryable = { ...pending, admission_state: 'rate_limited', admission_detail: errorMessage(error).slice(0, 240) };
    let checkpointWarning = '';
    try { savePendingAdmission(retryable); }
    catch { checkpointWarning = ' The retry status could not be updated in tab storage; the original signed request remains retained. Keep this tab open.'; }
    setPendingAdmission(retryable);
    setStatus('retryable');
    setNotice(rateLimitNotice(retryable.admission_detail) + checkpointWarning);
    log('Gateway rate limit or capacity rejected admission. The signed authorization remains available for retry.', 'warning');
  };

  const start = async () => {
    if (active.current || verificationController.current || busy || otherFlowBusy.current) return;
    if (!executionReady) { setNotice('Execution is not ready. Connect a configured gateway and an authenticated worker before signing.'); return; }
    setNotice('');
    try { validateSource(code); } catch (error) { setNotice(error.message); return; }
    if (!publicKey) { await connectWallet(); return; }
    if (!signMessage) { setNotice('This wallet cannot sign messages. Choose a compatible Solana wallet.'); return; }
    if (!quote || quote.expires_at * 1000 <= Date.now()) { setNotice('Review a fresh quote before signing this workload.'); setQuote(null); return; }
    const wallet = publicKey.toBase58();
    const challenge = quote;
    const revision = draftRevision.current;
    const run = { id: 'request-' + crypto.randomUUID(), name, mode: 'gateway', started: Date.now(), offset: 0 };
    active.current = run;
    controller.current = new AbortController();
    const ensureCurrent = () => {
      if (active.current !== run) throw new DOMException('Workload preparation was cancelled.', 'AbortError');
      if (otherFlowBusy.current) throw new Error('An agent workflow is using the execution slot. Finish or stop it before authorizing a Studio task.');
      if (currentIdentity.current !== wallet || draftRevision.current !== revision) throw new Error('The signing identity or workload changed. Review a fresh quote before signing.');
      if (challenge.wallet !== wallet || challenge.agent_pubkey !== wallet) throw new Error('The quote belongs to a different signing identity. Review a fresh quote.');
      if (challenge.expires_at * 1000 <= Date.now()) throw new Error('Quote expired. Review a fresh quote before signing.');
    };
    followLogs.current = true;
    setLogs([]); setReceipt(null); setStatus('reviewing');
    try {
      ensureCurrent();
      let liveState;
      try { liveState = await refreshChannel(); }
      catch (error) { throw new Error('Could not check the payment channel: ' + errorMessage(error)); }
      ensureCurrent();
      if (challenge.network !== (liveState?.development ? 'off_chain' : 'devnet')) { setQuote(null); throw new Error('The gateway mode changed after this quote. Review a fresh quote before signing.'); }
      if (!liveState?.development && !liveState?.config?.initialized) throw new Error('The gateway protocol is not configured. Check its Devnet program and authority settings.');
      if (!liveState?.development && (!liveState?.channel?.initialized || Number(liveState.channel.lamports) < challenge.max_cost_lamports)) throw new Error('Fund an idle payment channel to cover the full authorized maximum cost before submitting.');
      const config = { signal: controller.current.signal, timeout: 15000 };
      if (challenge.code_sha256 !== await sha256Hex(code)) throw new Error('The source differs from the approved quote. Review a fresh quote.');
      ensureCurrent();
      const spec = dataJob ? await jobManifest(code, dataInputs.map(item => item.descriptor), parametersText) : null;
      ensureCurrent();
      validateDatasetInputs(sampleId, spec);
      if (spec) await verifyJobManifest(challenge, spec);
      ensureCurrent();
      setQuote(null);
      log('Authorizing the reviewed rate, source hash, maximum spend and runtime.');
      if (active.current !== run) return;
      setStatus('signing');
      let signature;
      try { signature = await signMessage(new TextEncoder().encode(challenge.message)); }
      catch { throw new Error('Wallet signature declined. The workload was not submitted.'); }
      if (active.current !== run) return;
      ensureCurrent();
      setStatus('submitting');
      const body = { quote_id: challenge.quote_id, code, wallet, agent_pubkey: wallet, signature: Array.from(signature), message: challenge.message };
      if (challenge.workload) Object.assign(body, { job_version: 1, inputs: challenge.workload.inputs, parameters: challenge.workload.parameters });
      run.estimate = { score: challenge.analysis?.scores?.final_score ?? 0, rateLamports: challenge.rate_lamports };
      run.quote = quoteForReceipt(challenge);
      const pending = { mode: 'gateway', name: run.name, started: run.started, estimate: run.estimate, quote: run.quote, body };
      savePendingAdmission(pending); setPendingAdmission(pending);
      run.submitting = true;
      let data;
      try { ({ data } = await axios.post(API_URL + '/execute', body, config)); }
      catch (error) {
        if (axios.isCancel(error)) throw error;
        if (admissionWasRateLimited(error)) {
          retainRateLimitedAdmission(pending, error);
          return;
        }
        if (!admissionOutcomeIsUncertain(error)) {
          clearPendingAdmission(); setPendingAdmission(null);
          throw error;
        }
        // The exact signed quote is idempotent; a lost response cannot dispatch twice.
        try { ({ data } = await axios.post(API_URL + '/execute', body, config)); }
        catch (retryError) {
          if (axios.isCancel(retryError)) throw retryError;
          if (admissionWasRateLimited(retryError)) {
            retainRateLimitedAdmission(pending, retryError);
            return;
          }
          if (!admissionOutcomeIsUncertain(retryError)) {
            setStatus('uncertain');
            setNotice('The first admission response was lost and recovery was rejected: ' + errorMessage(retryError) + ' The exact signed request remains saved; recover the original task before making another quote.');
            return;
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
      if (saveActiveRun(run)) { clearPendingAdmission(); setPendingAdmission(null); }
      else setNotice('The gateway confirmed the task, but this tab could not save its capability. The original signed request remains retained; keep this tab open.');
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
      const { data } = await axios.post(API_URL + '/stop/' + run.id, null, { headers: { 'X-Aperture-Task-Token': run.token }, timeout: 15000 });
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
    if (!file || active.current || otherFlowBusy.current) return;
    if (file.size > MAX_SOURCE_BYTES) { setNotice('Choose a Python file of 32,000 UTF-8 bytes or smaller.'); return; }
    try {
      const content = await file.text();
      if (active.current || otherFlowBusy.current) return;
      setCode(content); setName(file.name); setSampleId('custom'); setAnalysis(null); setReceipt(null); setStatus('idle'); setNotice('');
    } catch { setNotice('The file could not be read. Please try another file.'); }
  };
  const addDataFiles = async event => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length || busy || otherFlowBusy.current) return;
    if (!publicKey) { setNotice('Connect your wallet, then select the files again.'); await connectWallet(); return; }
    if (!signMessage) { setNotice('Choose a wallet that supports message signing to authorize file uploads.'); return; }
    if (dataInputs.length + files.length > 16 || new Set([...dataInputs.map(item => item.descriptor.name.toLowerCase()), ...files.map(file => file.name.toLowerCase())]).size !== dataInputs.length + files.length
        || dataInputs.reduce((total, item) => total + item.descriptor.size_bytes, 0) + files.reduce((total, file) => total + file.size, 0) > MAX_INPUT_BYTES) {
      setNotice('Choose up to 16 uniquely named files totaling 64 MiB.'); return;
    }
    setStatus('uploading'); setNotice(''); setQuote(null); setDataJob(true);
    const owner = publicKey.toBase58();
    const attempt = new AbortController();
    const generation = ++uploadGeneration.current;
    uploadController.current = attempt;
    const ensureCurrent = () => {
      if (attempt.signal.aborted || otherFlowBusy.current || uploadGeneration.current !== generation || currentIdentity.current !== owner) throw new DOMException('Input upload was cancelled.', 'AbortError');
    };
    let staged = [...dataInputs];
    try {
      ensureCurrent();
      if (gatewayHealth?.program_id && gatewayHealth.program_id !== APERTURE_PROGRAM_ID
          || GATEWAY_PUBKEY_PIN && gatewayHealth?.gateway_pubkey !== GATEWAY_PUBKEY_PIN) throw new Error('Gateway identity differs from this frontend deployment.');
      for (const file of files) {
        ensureCurrent();
        const descriptor = await uploadInput({ apiUrl: API_URL, file, owner, signMessage,
          health: { ...gatewayHealth, program_id: APERTURE_PROGRAM_ID }, signal: attempt.signal, ensureCurrent });
        ensureCurrent();
        staged = [...staged, { owner, descriptor }];
        inputReferences.current.set(owner, staged);
        while (inputReferences.current.size > 16) inputReferences.current.delete(inputReferences.current.keys().next().value);
        setDataInputs(staged);
        if (sampleId === 'dataset' && staged.length === 1 && /\.csv$/i.test(file.name)) {
          setParametersText(previous => {
            try {
              const parameters = JSON.parse(previous);
              return parameters?.input_name === 'dataset.csv'
                ? JSON.stringify({ ...parameters, input_name: file.name }, null, 2) : previous;
            } catch { return previous; }
          });
        }
      }
    } catch (error) {
      if (!attempt.signal.aborted && uploadGeneration.current === generation && currentIdentity.current === owner && !axios.isCancel(error) && error.name !== 'AbortError') setNotice('Could not stage all selected files: ' + errorMessage(error));
    } finally {
      if (uploadController.current === attempt) {
        uploadController.current = null;
        setStatus(previous => previous === 'uploading' ? 'idle' : previous);
      }
    }
  };
  const readResultFile = async item => {
    const authorization = resultAccess.current.get(receipt.taskId);
    if (!receipt.receiptVerified || !authorization) throw new Error('Verify the receipt before opening its result files.');
    const itemRef = validateObject(item, 8 * 1024 * 1024);
    if (!receipt.backendReceipt.artifacts?.some(file => file.object_id === itemRef.object_id && file.name === itemRef.name
        && file.size_bytes === itemRef.size_bytes && file.sha256 === itemRef.sha256)) throw new Error('The selected file is absent from the signed receipt.');
    const verification = await verifyReturnedReceipt(receipt.backendReceipt, authorization.quote, receipt.taskId, authorization.token, connection);
    if (!verification.verified) throw new Error(verification.reason || 'Result receipt could not be verified.');
    const data = await workflowRequest({ api_url: API_URL }, '/tasks/' + receipt.taskId + '/artifacts/' + itemRef.object_id,
      { token: authorization.token, bytes: true, maximum: itemRef.size_bytes });
    if (data.byteLength !== itemRef.size_bytes || await hashBytes(data) !== itemRef.sha256) throw new Error('Downloaded file differs from its signed size or SHA-256.');
    return data;
  };
  const downloadResultFile = async item => {
    const data = await readResultFile(item);
    saveFile(item.name, data, 'application/octet-stream');
  };
  const copyCode = async () => {
    try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1800); }
    catch { setNotice('Clipboard unavailable. Select the code and copy it manually.'); }
  };
  const downloadRaw = async () => {
    if (!receipt?.taskId || receipt.mode !== 'gateway') return;
    try {
      const completed = resultAccess.current.get(receipt.taskId);
      if (!completed) throw new Error('Raw log access is available for runs completed in this tab.');
      const { data } = await axios.get(API_URL + '/download/' + receipt.taskId, { headers: { 'X-Aperture-Task-Token': completed.token }, responseType: 'text', timeout: 15000 });
      saveFile('aperture-' + receipt.taskId + '.txt', data);
    } catch (error) { setNotice(errorMessage(error)); }
  };
  const retryVerification = async () => {
    const saved = receipt;
    const authorization = saved && resultAccess.current.get(saved.taskId);
    if (busy || verificationController.current || !saved?.backendReceipt) return;
    if (!authorization) { setNotice('Verification access is available for runs completed in this tab.'); return; }
    const attempt = new AbortController();
    verificationController.current = attempt;
    setVerificationBusy(true); setNotice('');
    let verification;
    try {
      verification = await verifyReturnedReceipt(saved.backendReceipt, authorization.quote, saved.taskId, authorization.token, connection, attempt.signal);
    } catch (error) {
      if (attempt.signal.aborted) return;
      verification = { verified: false, reason: 'Receipt or raw output could not be verified: ' + errorMessage(error) };
    } finally {
      if (verificationController.current === attempt) verificationController.current = null;
      if (!attempt.signal.aborted) setVerificationBusy(false);
    }
    if (attempt.signal.aborted) return;
    const updated = { ...saved, status: verification.verified ? saved.reportedStatus : 'unverified', output: verification.verified ? verification.verifiedOutput : saved.output, receiptVerified: verification.verified, verificationNote: verification.reason, chainReceiptAddress: verification.chainReceipt || null };
    setReceipt(current => current?.taskId === saved.taskId ? updated : current);
    setRuns(previous => previous.map(run => run.taskId === saved.taskId ? updated : run));
    setStatus(updated.status);
    log(verification.verified ? 'Receipt verification passed.' : 'Receipt remains unverified.', verification.verified ? 'success' : 'warning');
    onRecord?.({ id: saved.taskId, name: saved.name, mode: saved.mode, status: updated.status, timestamp: saved.timestamp });
  };

  return <div className="studio">
    {externalBusy && <div className="studio-policy" role="status"><Icon name="network" size={18} /><p>An agent workflow is using the execution slot. New Studio preparations are paused; existing task monitoring and cancellation remain available.</p></div>}
    {reviewedSourcesOnly && <div className="studio-policy" role="status"><Icon name="shield" size={18} /><p>Reviewed samples only. Edited or imported source needs operator approval.</p></div>}
    {notice && <div className={'studio-notice ' + (status === 'blocked' ? 'blocked' : '')} role="alert"><Icon name="shield" size={18} /><p>{notice}</p>{pendingAdmission && ['uncertain', 'retryable'].includes(status) && <button className="console-button secondary" disabled={externalBusy} onClick={resumePendingAdmission}>{status === 'retryable' ? 'Retry signed admission' : 'Recover signed request'}</button>}</div>}
    <section className="console-panel studio-status-card" aria-busy={busy}>
      <div className="studio-status-heading">
        <div className={'studio-status-icon ' + status} data-busy={busy}>
          <Icon name={status === 'completed' ? 'check' : ['failed', 'blocked', 'unverified'].includes(status) ? 'shield' : busy ? 'refresh' : 'spark'} size={23} />
        </div>
        <div>
          <h2 aria-live="polite">{verificationBusy ? LABELS.verifying : status === 'uploading' ? 'Staging your input files' : LABELS[status]}</h2>
          <p>{status === 'idle' ? 'Set your limits, then review the price.' : status === 'quoted' ? 'Check the quote before signing.' : busy ? 'Your run stays active when you change pages.' : 'Inspect the result or prepare another run.'}</p>
        </div>
      </div>
      <ol className="studio-steps">
        {['Prepare', 'Review', 'Run', 'Result'].map((step, index) => (
          <li key={step} className={(index <= progressStep ? 'reached' : '') + (index === progressStep ? ' current' : '')} aria-current={index === progressStep ? 'step' : undefined}>
            <span>{index + 1}</span>{step}
          </li>
        ))}
      </ol>
    </section>
    <div className="studio-grid">
      <section className="studio-editor">
        <div className="studio-editor-heading"><div><span className="studio-file-dot" /><strong>workload.py</strong><span className="studio-language">PYTHON</span></div><div><button onClick={copyCode} title="Copy source" aria-label={copied ? 'Code copied' : 'Copy code'}><Icon name={copied ? 'check' : 'copy'} size={18} /></button><button onClick={() => inputRef.current.click()} disabled={draftLocked} title="Import Python file" aria-label="Import Python file"><Icon name="upload" size={18} /></button></div></div>
        <div className="studio-presets"><label htmlFor="workload-preset">Sample</label><select id="workload-preset" value={sampleId} disabled={draftLocked} onChange={event => selectSample(WORKLOADS.find(sample => sample.id === event.target.value))}>{WORKLOADS.map(sample => <option value={sample.id} key={sample.id}>{sample.name}</option>)}{sampleId === 'custom' && <option value="custom">Custom workload</option>}</select><button disabled={draftLocked} onClick={() => selectSample(WORKLOADS.find(sample => sample.id === sampleId) || WORKLOADS[0])} title="Reset sample" aria-label="Reset sample"><Icon name="refresh" size={16} /></button></div>
        <div className="studio-source"><textarea aria-label="Python source code" value={code} spellCheck={false} disabled={draftLocked} onChange={event => { if (otherFlowBusy.current) return; setCode(event.target.value); setSampleId('custom'); setName('Custom workload'); setAnalysis(null); setReceipt(null); setStatus('idle'); }} /></div>
        <div className="studio-editor-meta"><span>UTF-8 · {code.split('\n').length} lines</span><span>{new TextEncoder().encode(code).length.toLocaleString()} / {MAX_SOURCE_BYTES.toLocaleString()} bytes</span></div>
        <input ref={inputRef} type="file" accept=".py,text/plain" hidden onChange={importFile} />
      </section>
      <aside className="studio-inspector" aria-label="Run settings">
        <section className="console-panel studio-data">
          <div className="console-section-heading"><div><span className="console-eyebrow">DATA → COMPUTE → FILES</span><h2>Job inputs</h2></div><Icon name="upload" size={20} /></div>
          <label className="studio-data-toggle"><input type="checkbox" checked={dataJob} disabled={draftLocked} onChange={event => { if (!otherFlowBusy.current) setDataJob(event.target.checked); }} />Enable files and parameters</label>
          {dataJob && <>
            <p>Upload your dataset once. The quote binds its hash, parameters and source.</p>
            <ul className="studio-file-list">{dataInputs.map(item => <li key={item.descriptor.object_id}><div><strong>{item.descriptor.name}</strong><small>{(item.descriptor.size_bytes / 1024).toFixed(1)} KB · {item.descriptor.sha256.slice(0, 10)}…</small></div><button disabled={draftLocked} aria-label={'Remove ' + item.descriptor.name + ' from job'} onClick={() => setDataInputs(previous => { const next = previous.filter(value => value !== item); inputReferences.current.set(item.owner, next); return next; })}><Icon name="close" size={16} /></button></li>)}</ul>
            <button className="console-button secondary" disabled={draftLocked || !gatewayOnline} onClick={() => dataInputRef.current.click()}><Icon name="upload" size={16} />{status === 'uploading' ? 'Uploading…' : 'Choose input files'}</button>
            <small className="studio-data-limit">16 files · 64 MiB total · private to your signing identity</small>
            <label className="studio-parameters" htmlFor="job-parameters">Parameters · JSON<textarea id="job-parameters" value={parametersText} disabled={draftLocked} spellCheck={false} onChange={event => { if (!otherFlowBusy.current) setParametersText(event.target.value); }} /></label>
          </>}
          <input ref={dataInputRef} type="file" multiple hidden onChange={addDataFiles} />
        </section>
        <section className="console-panel studio-estimate">
          <div className="console-section-heading"><h2>Run limits</h2><Icon name="shield" size={18} /></div>
          <div className="studio-budget">
            <label htmlFor="task-max-cost"><span>Maximum cost<small>SOL</small></span><input id="task-max-cost" type="number" min="0.000000001" max="1" step="0.000001" value={maxCost} disabled={draftLocked} onChange={event => { if (!otherFlowBusy.current) setMaxCost(event.target.value); }} /></label>
            <label htmlFor="task-max-runtime"><span>Runtime limit<small>seconds</small></span><input id="task-max-runtime" type="number" min="1" max="180" step="1" value={maxRuntime} disabled={draftLocked} onChange={event => { if (!otherFlowBusy.current) setMaxRuntime(event.target.value); }} /></label>
          </div>
          {!quote && <p>Review the price before you authorize a run.</p>}
          {quote && <div className="studio-quote">
            <h3>Your quote</h3>
            <dl>
              <div><dt>Rate · source heuristic</dt><dd>{quote.rate_lamports / 1e9} SOL/s</dd></div>
              <div><dt>Maximum charge</dt><dd>{quote.max_cost_lamports / 1e9} SOL</dd></div>
              <div><dt>Execution limit</dt><dd>{quote.effective_runtime_seconds}s</dd></div>
              <div><dt>Expires</dt><dd>{new Date(quote.expires_at * 1000).toLocaleTimeString()}</dd></div>
            </dl>
            <p>Signing approves this source, {quote.workload ? 'input files, parameters and ' : ''}budget. Changes require a new quote.</p>
          </div>}
          <div className="studio-run-control">{busy ? <button className="console-button secondary" disabled={!['queued', 'running', 'settlement_pending'].includes(status)} onClick={stop}><Icon name="stop" size={16} />{status === 'stopping' ? 'Stopping…' : ['queued', 'running', 'settlement_pending'].includes(status) ? 'Stop run' : 'Please wait…'}</button> : <button className="console-button primary" onClick={quote ? start : reviewQuote} disabled={externalBusy || channelBusy || connecting || Boolean(quote && !executionReady)} aria-busy={channelBusy || connecting}><Icon name={channelBusy || connecting ? 'refresh' : !publicKey ? 'wallet' : quote ? 'play' : 'shield'} size={16} />{externalBusy ? 'Agent workflow active' : connecting ? 'Connecting…' : channelBusy ? 'Channel transaction…' : !publicKey ? 'Connect wallet' : quote ? executionReady ? 'Accept quote & sign' : 'Execution unavailable' : 'Review price & limits'}</button>}</div>
          {quote && !executionReady && <p className="studio-execution-help">{!gatewayOnline ? 'Reconnect the gateway to execute this workload.' : 'Execution needs a configured gateway and an authenticated worker.'}</p>}
          {analysis && <details className="studio-disclosure">
            <summary>Source analysis & pricing</summary>
            <dl><div><dt>Complexity</dt><dd>{analysis.score}</dd></div><div><dt>Quoted rate</dt><dd>{analysis.rateLamports} lamports/s</dd></div></dl>
            <p>The rate comes from static source analysis, not measured worker performance or a live market price.</p>
            <p>{analysis.description}</p>
          </details>}
        </section>
        <section className="console-panel studio-channel">
          <div className="console-section-heading"><div><span className="console-eyebrow">{gatewayOffChain ? 'EXECUTION IDENTITY' : 'DEVNET PAYMENT'}</span><h2>{gatewayOffChain ? 'Signed execution' : 'Payment channel'}</h2></div><Icon name={gatewayOffChain ? 'shield' : 'wallet'} size={18} /></div>
          {gatewayOffChain ? <>
            <p className="studio-channel-help">The worker returns signed output. No on-chain payment.</p>
            <details className="studio-disclosure"><summary>Identity details</summary><dl>
              <div><dt>Your signing key</dt><dd>{publicKey ? publicKey.toBase58().slice(0, 6) + '…' + publicKey.toBase58().slice(-6) : 'Not connected'}</dd></div>
              <div><dt>Gateway signer</dt><dd title={gatewayHealth?.gateway_pubkey}>{gatewayHealth?.gateway_pubkey ? gatewayHealth.gateway_pubkey.slice(0, 6) + '…' + gatewayHealth.gateway_pubkey.slice(-6) : 'Unavailable'}</dd></div>
              <div><dt>Connected workers</dt><dd>{gatewayOnline ? workerCount : 'Unavailable'}</dd></div>
              <div><dt>On-chain charge</dt><dd>None</dd></div>
            </dl></details>
          </> : publicKey ? <>
            <p className="studio-channel-wallet">Wallet · {publicKey.toBase58().slice(0, 5)}…{publicKey.toBase58().slice(-5)}</p>
            <dl>
              <div><dt>Wallet balance</dt><dd>{walletBalance === null ? 'Unavailable' : formatSol(walletBalance) + ' SOL'}</dd></div>
              <div><dt>Channel balance</dt><dd>{channel?.balance == null ? 'Unavailable' : formatSol(channel.balance) + ' SOL'}</dd></div>
              <div><dt>Protocol</dt><dd>{protocolConfig?.initialized ? 'Configured' : 'Unavailable'}</dd></div>
            </dl>
            <label className="studio-channel-label" htmlFor="channel-deposit">Deposit amount</label>
            <div className="studio-channel-deposit">
              <input id="channel-deposit" inputMode="decimal" type="number" min="0.000000001" step="0.01" value={depositAmount} disabled={draftLocked || channelBusy} onChange={event => { if (!otherFlowBusy.current) setDepositAmount(event.target.value); }} />
              <span>SOL</span>
            </div>
            <button className="console-button secondary studio-channel-action" onClick={handleDeposit} disabled={draftLocked || channelBusy || !sendTransaction || !protocolConfig?.initialized} aria-busy={channelBusy}>
              <Icon name={channelBusy ? 'refresh' : 'wallet'} size={16} />{channelBusy ? 'Waiting for Devnet…' : channel?.initialized ? 'Add to channel' : 'Open & fund channel'}
            </button>
            {channel?.initialized && <button className="console-text-button studio-channel-close" onClick={handleCloseChannel} disabled={draftLocked || channelBusy || Number(channel.burn_rate_lamports) > 0}>
              Close channel and refund remaining SOL<Icon name="arrow" size={15} />
            </button>}
            {!protocolConfig?.initialized && <p className="studio-channel-help">The gateway must be deployed and its protocol configuration initialized before the channel can be opened.</p>}
            {protocolConfig?.initialized && !channel?.initialized && <p className="studio-channel-help">Your wallet will sign a Devnet transaction to open this channel.</p>}
          </> : <>
            <p className="studio-channel-help">Connect your wallet to fund a Devnet payment channel.</p>
          </>}
        </section>
      </aside>
    </div>
    <section className="studio-terminal"><div className="studio-terminal-heading"><h2><Icon name="code" size={18} />Run output<span className="studio-terminal-count">{logs.length} events</span></h2><button className="console-text-button" disabled={!logs.length} onClick={() => saveFile('aperture-output.txt', logs.map(entry => '[' + entry.time + '] ' + entry.message).join('\n'))}><Icon name="download" size={16} />Save log</button></div><div className="studio-log" ref={logRef} onScroll={event => { const element = event.currentTarget; followLogs.current = element.scrollHeight - element.scrollTop - element.clientHeight < 32; }} role="log" aria-label="Run output" aria-live="polite" aria-atomic="false">{logs.length ? logs.map((entry, index) => <div className={'studio-log-line ' + entry.kind} key={index}><time>{entry.time}</time><span>{entry.message}</span></div>) : <div className="studio-terminal-empty"><span>›</span> Your run output will appear here.</div>}</div></section>
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
        {invalidResultFiles && <p className="studio-verification unverified" role="status">Result file manifest is invalid. Its files cannot be downloaded.</p>}
        {resultFiles.length > 0 && <div className="studio-result-files"><h3>Result files</h3><p>Open a report or download its exact bytes. Each file is checked against the signed receipt.</p><ResultFiles files={resultFiles} scope={receipt.taskId + ':' + receipt.receiptVerified} disabled={!receipt.receiptVerified} onRead={readResultFile} onDownload={downloadResultFile} /></div>}
        {receipt.backendReceipt && (
          <>
            <p className={'studio-verification ' + (receipt.receiptVerified ? 'verified' : 'unverified')} role="status">
              <Icon name={receipt.receiptVerified ? 'check' : 'shield'} size={18} />
              <span>{receipt.status === 'unverified' && `Gateway-reported outcome: ${LABELS[receipt.reportedStatus] || receipt.reportedStatus}. `}
              {receipt.verificationNote || 'Receipt signatures and chain state were not independently verified.'}</span>
            </p>
            <details className="studio-disclosure studio-receipt-disclosure"><summary>Receipt evidence</summary><dl className="studio-receipt-evidence">
              {[
                ['Worker', receipt.backendReceipt.worker_id], ['Exit code', receipt.backendReceipt.exit_code],
                ['Execution boundary', receipt.backendReceipt.execution_backend], ['Agent public key', receipt.backendReceipt.agent_pubkey],
                ['Source SHA-256', receipt.backendReceipt.code_sha256], ['Raw output SHA-256', receipt.backendReceipt.output_sha256],
                ['Worker signature', receipt.backendReceipt.worker_signature], ['Receipt hash', receipt.backendReceipt.receipt_sha256],
                ...(receipt.chainReceiptAddress ? [['On-chain task receipt', receipt.chainReceiptAddress]] : []),
              ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? 'Unavailable'}</dd></div>)}
            </dl></details>
          </>
        )}
        <div className="studio-receipt-actions">
          {receipt.status === 'unverified' && receipt.mode === 'gateway' && receipt.backendReceipt?.signed_message && <button className="console-button secondary" disabled={busy} onClick={retryVerification}><Icon name="refresh" size={16} />{verificationBusy ? 'Verifying…' : 'Retry verification'}</button>}
          <button className="console-button secondary" onClick={() => saveFile('aperture-' + receipt.taskId + '.json', JSON.stringify(receipt.backendReceipt || receipt, null, 2), 'application/json')}><Icon name="download" size={16} />Download receipt</button>
          {receipt.mode === 'gateway' && <button className="console-text-button" onClick={downloadRaw}><Icon name="download" size={16} />Download raw output</button>}
          {receipt.proof && /^https:\/\/explorer\.solana\.com\/tx\//.test(receipt.proof) && <a className="console-text-button" href={receipt.proof} target="_blank" rel="noreferrer">View Devnet transaction<Icon name="external" size={16} /></a>}
        </div>
      </section>
    )}
    {runs.length > 1 && <section className="console-panel studio-history"><h2>This session</h2>{runs.map(run => <button key={run.taskId} onClick={() => setReceipt(run)} disabled={busy}><span><Icon name="chip" size={16} />{run.name}</span><span>Gateway · {run.status}<Icon name="arrow" size={16} /></span></button>)}</section>}
  </div>;
}
