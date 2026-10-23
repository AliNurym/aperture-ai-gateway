import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import Icon from './components/Icon';
import { canonicalJson, canonicalQuoteMessage, sha256Hex, verifyGatewayReceipt, verifyDevnetSettlement } from './utils/protocol';
import { hasMatchingInferenceWorker, inferenceText, isLocalGatewayUrl, parseSentinelReport, publicInferenceProviders, publicOffer, sentinelGeminiProviders, verifyInferenceQuote } from './utils/inference';
import { requestErrorMessage } from './utils/requestError';
import './Inference.css';

const STORAGE_KEY = 'aperture-inference-active-v1';
function restoreRun() {
  try {
    const item = JSON.parse(sessionStorage.getItem(STORAGE_KEY));
    return item?.quote?.workload?.runtime === 'inference.chat' && item?.body?.quote_id === item.quote.quote_id
      && !item.rejected && (item.pending || typeof item.token === 'string' && typeof item.id === 'string') ? { ...item, terminal: false } : null;
  } catch { return null; }
}

export default function Inference({ apiUrl, gatewayHealth, preferredProviderId = "", sentinelDraft = null, onSentinelResult, onReturnToStudio, onOpenFunding, onOpenSetup, externalBusy, onBusyChange, onRecord }) {
  const { publicKey, signMessage, wallet: selectedWallet, connect, connecting } = useWallet();
  const { connection } = useConnection();
  const { setVisible } = useWalletModal();
  const wallet = publicKey?.toBase58();
  const identity = useRef(wallet);
  useEffect(() => { identity.current = wallet; }, [wallet]);
  const [run, setRun] = useState(restoreRun);
  const [providers, setProviders] = useState([]);
  const [providerId, setProviderId] = useState(() => run?.quote?.workload?.parameters?.offer?.id || preferredProviderId || '');
  const [prompt, setPrompt] = useState(() => run?.quote?.workload?.parameters?.inference?.messages?.[0]?.content || 'Explain how a spending limit helps an autonomous AI agent.');
  const [maxTokens, setMaxTokens] = useState(() => String(run?.quote?.workload?.parameters?.inference?.max_tokens || 128));
  const [budget, setBudget] = useState(() => String(run?.quote?.max_cost_lamports || 100000));
  const [runtime, setRuntime] = useState(() => String(run?.quote?.max_runtime_seconds || 30));
  const [quote, setQuote] = useState(null);
  const [result, setResult] = useState(null);
  const [notice, setNotice] = useState('');
  const [providerError, setProviderError] = useState('');
  const [working, setWorking] = useState(false);
  const [loading, setLoading] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const [liveOutput, setLiveOutput] = useState('');
  const action = useRef(false);
  const appliedSentinelDraft = useRef("");
  const appliedSentinelProvider = useRef("");
  const provider = providers.find(item => item.id === providerId);
  const active = Boolean(run && !run.terminal);
  const locked = working || active || externalBusy;
  const localGateway = isLocalGatewayUrl(apiUrl);
  const sentinelPromptMatchesSource = Boolean(sentinelDraft && prompt === sentinelDraft.prompt);
  const linkedSentinelRun = Boolean(sentinelDraft && run?.sentinelDraftId === sentinelDraft.id
    && run?.sentinelSource === sentinelDraft.source);

  const refresh = useCallback(async () => {
    setLoading(true);
    setProviderError('');
    try {
      const { data } = await axios.get(apiUrl + '/inference/providers', { timeout: 10000 });
      const catalog = publicInferenceProviders(data?.providers);
      const available = sentinelDraft ? sentinelGeminiProviders(catalog) : catalog;
      setProviders(available);
      setProviderId(current => available.some(item => item.id === current) ? current : available[0]?.id || '');
    } catch (error) {
      setProviders([]);
      setProviderId('');
      setProviderError(requestErrorMessage(error));
    }
    finally { setLoading(false); }
  }, [apiUrl, sentinelDraft]);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (!run && preferredProviderId && providers.some(item => item.id === preferredProviderId)) setProviderId(preferredProviderId);
  }, [preferredProviderId, providers, run]);
  useEffect(() => {
    if (!sentinelDraft?.id || !sentinelDraft.prompt || appliedSentinelDraft.current === sentinelDraft.id || active) return;
    appliedSentinelDraft.current = sentinelDraft.id;
    setPrompt(sentinelDraft.prompt);
    setQuote(null);
    setResult(null);
    setLiveOutput('');
    setNotice('Source loaded into AI Sentinel. Review the provider and limits; the prompt is not sent until you approve and sign.');
  }, [sentinelDraft, active]);
  useEffect(() => {
    if (!sentinelDraft?.id || !providers.length || run || appliedSentinelProvider.current === sentinelDraft.id) return;
    appliedSentinelProvider.current = sentinelDraft.id;
    const gemini = sentinelGeminiProviders(providers)[0];
    if (gemini) setProviderId(gemini.id);
  }, [sentinelDraft, providers, run]);
  useEffect(() => { onBusyChange(working || active); return () => onBusyChange(false); }, [working, active, onBusyChange]);
  useEffect(() => { if (!active) return; const timer = setInterval(() => setElapsed(Math.floor((Date.now() - run.started) / 1000)), 1000); return () => clearInterval(timer); }, [active, run?.started]);

  const saveRun = next => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    setRun(next);
  };
  const persistObservedRun = next => {
    // An admitted task must remain visible even if tab storage becomes unavailable.
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next)); }
    catch { setNotice('Tab storage is unavailable. Keep this page open until the task finishes.'); }
    setRun(next);
  };
  useEffect(() => {
    if (!run?.id || run.terminal) return;
    const controller = new AbortController();
    let timer;
    let offset = 0;
    let streamed = '';
    const poll = async () => {
      try {
        const headers = { 'X-Aperture-Task-Token': run.token };
        const { data } = await axios.get(apiUrl + '/result/' + run.id, { headers, signal: controller.signal, timeout: 10000 });
        if (data.status === 'completed') {
          const raw = await axios.get(apiUrl + '/download/' + run.id, { headers, responseType: 'text', signal: controller.signal, timeout: 10000 });
          let verification = await verifyGatewayReceipt(data.receipt, run.quote, run.id, raw.data);
          if (verification.verified && data.receipt.settlement_type === 'DEVNET') verification = await verifyDevnetSettlement(connection, data.receipt, run.quote, run.id);
          if (controller.signal.aborted) return;
          setResult({ output: verification.verified ? raw.data : '', receipt: data.receipt, verification });
          if (verification.verified && run.sentinelDraftId && typeof run.sentinelSource === 'string') {
            onSentinelResult?.({ draftId: run.sentinelDraftId, source: run.sentinelSource, report: parseSentinelReport(raw.data), taskId: run.id,
              owner: run.quote.wallet, gatewayPubkey: run.quote.gateway_pubkey, receiptSha256: data.receipt.receipt_sha256 });
          }
          persistObservedRun({ ...run, terminal: true });
          onRecord({ id: run.id, name: (run.sentinelDraftId ? 'AI Sentinel · ' : 'Inference · ') + run.quote.workload.parameters.offer.model, mode: 'gateway', status: data.receipt.execution_status, started: run.started });
          return;
        }
        const stream = await axios.get(apiUrl + '/stream_log/' + run.id, { headers, params: { offset }, signal: controller.signal, timeout: 10000 });
        if (!controller.signal.aborted) {
          offset = stream.data.next_offset;
          streamed = (streamed + stream.data.lines.join('')).slice(-1000000);
          setLiveOutput(streamed);
        }
      } catch (error) { if (!controller.signal.aborted) setNotice('Result recovery: ' + requestErrorMessage(error)); }
      if (!controller.signal.aborted) timer = setTimeout(poll, 1500);
    };
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [apiUrl, run, connection, onRecord, onSentinelResult]);

  const change = setter => event => { setter(event.target.value); setQuote(null); };
  const review = async event => {
    event.preventDefault();
    if (sentinelDraft && provider?.protocol !== 'gemini_generate_content') {
      setNotice('AI Sentinel requires the original Gemini API route. No request was sent.');
      return;
    }
    if (!hasMatchingInferenceWorker(provider)) {
      setNotice('No active worker matches this model offer. Refresh providers after its worker connects; no quote or request was sent.');
      return;
    }
    if (!wallet) {
      try { if (selectedWallet) await connect(); else setVisible(true); }
      catch (error) { setNotice(requestErrorMessage(error)); }
      return;
    }
    if (!provider || action.current || locked) return;
    action.current = true; setWorking(true); setNotice(''); setResult(null); setQuote(null); setLiveOutput('');
    const owner = wallet;
    try {
      const limits = { maxTokens: Number(maxTokens), budget: Number(budget), runtime: Number(runtime) };
      if (![limits.maxTokens, limits.budget, limits.runtime].every(Number.isSafeInteger)) throw new Error('Limits must be whole numbers.');
      const messages = [{ role: 'user', content: prompt }];
      const { data } = await axios.post(apiUrl + '/inference/quotes', { wallet: owner, provider_id: provider.id, messages,
        max_tokens: limits.maxTokens, max_cost_lamports: limits.budget, max_runtime_seconds: limits.runtime }, { timeout: 15000 });
      await verifyInferenceQuote(data, { wallet: owner, provider, messages, ...limits, health: gatewayHealth });
      if (identity.current !== owner) throw new Error('Wallet changed. Review a new quote.');
      setQuote(data);
    } catch (error) { setNotice(requestErrorMessage(error)); }
    finally { action.current = false; setWorking(false); }
  };
  const submit = async () => {
    if (action.current || working || externalBusy) return;
    action.current = true; setWorking(true); setNotice('');
    try {
      let pending = run?.pending && !run.terminal ? run : null;
      if (!pending) {
        if (!quote || !signMessage || wallet !== quote.wallet || quote.expires_at * 1000 <= Date.now()) throw new Error('Connect the quoted wallet and review a fresh quote before signing.');
        const { data: catalogData } = await axios.get(apiUrl + '/inference/providers', { timeout: 10000 });
        const catalog = publicInferenceProviders(catalogData?.providers);
        const available = sentinelDraft ? sentinelGeminiProviders(catalog) : catalog;
        const currentProvider = available.find(item => item.id === provider?.id);
        if (!hasMatchingInferenceWorker(currentProvider)) throw new Error('No active worker matches this model offer. Refresh providers; no signature was requested.');
        if (canonicalJson(publicOffer(currentProvider)) !== canonicalJson(quote.workload?.parameters?.offer)) {
          throw new Error('The model offer changed after this quote. Review a fresh quote before signing.');
        }
        if (sentinelDraft && (provider?.protocol !== 'gemini_generate_content'
            || quote.workload?.parameters?.offer?.protocol !== 'gemini_generate_content')) {
          throw new Error('AI Sentinel requires a Gemini quote. Review the provider again before signing.');
        }
        const signature = await signMessage(new TextEncoder().encode(quote.message));
        if (identity.current !== quote.wallet) throw new Error('Wallet changed before admission.');
        const linkedSentinel = sentinelDraft && prompt === sentinelDraft.prompt ? sentinelDraft : null;
        pending = { pending: true, started: Date.now(), quote, body: { ...quote.execution_request,
          wallet: quote.wallet, quote_id: quote.quote_id, message: quote.message, signature: Array.from(signature) } };
        if (linkedSentinel) Object.assign(pending, { sentinelDraftId: linkedSentinel.id, sentinelSource: linkedSentinel.source });
        saveRun(pending);
      }
      if (wallet !== pending.quote.wallet || pending.body.message !== canonicalQuoteMessage(pending.quote)
          || await sha256Hex(pending.body.code) !== pending.quote.code_sha256) throw new Error('Restore the original wallet and authorization before retrying admission.');
      const { data } = await axios.post(apiUrl + '/execute', pending.body, { timeout: 15000 });
      if (data.quote_id !== pending.quote.quote_id || !/^task-[0-9a-f]{32}$/.test(data.task_id) || typeof data.task_access_token !== 'string') throw new Error('Admission returned an invalid task identity.');
      persistObservedRun({ ...pending, pending: false, id: data.task_id, token: data.task_access_token });
    } catch (error) {
      if ([400, 401, 403, 404, 409, 422].includes(error.response?.status)) {
        persistObservedRun({ ...(run || {}), terminal: true, rejected: true });
        setQuote(null);
        setNotice(requestErrorMessage(error) + ' Admission was rejected; review a new quote.');
      } else setNotice(requestErrorMessage(error) + ' If admission is uncertain, retry the saved authorization to recover the same task.');
    }
    finally { action.current = false; setWorking(false); }
  };
  const stop = async () => {
    try { await axios.post(apiUrl + '/stop/' + run.id, {}, { headers: { 'X-Aperture-Task-Token': run.token }, timeout: 10000 }); setNotice('Cancellation requested. Waiting for the final receipt.'); }
    catch (error) { setNotice(requestErrorMessage(error)); }
  };
  const sentinelReport = linkedSentinelRun && result?.verification?.verified ? parseSentinelReport(result.output) : null;

  return <div className="inference-page">
        <section className="inference-intro"><h2>{sentinelDraft ? 'AI Sentinel review' : 'Model inference'}</h2><p>{sentinelDraft ? sentinelPromptMatchesSource ? 'Review the current Python source with a configured model. Keep this advisory beside the editor; source policy and compute approval remain separate.' : 'This prompt was edited. Its response will not be attached to the Python source in Studio.' : 'Choose a configured model, set request limits and sign the quote before sending your prompt.'}</p>{sentinelDraft && <button className="console-text-button inference-return" onClick={onReturnToStudio}><Icon name="arrow" size={16} />Close AI Sentinel</button>}</section>
    <div className="inference-layout">
      <section className="console-panel inference-request"><div className="console-section-heading"><h3>Inference request</h3><button className="console-text-button" onClick={refresh} disabled={loading || active}><Icon name="refresh" size={16} />Refresh providers</button></div>
        {loading ? (
          <p role="status">Loading configured providers…</p>
        ) : providerError ? (
          <div className="inference-setup">
            <h3>{sentinelDraft ? 'Could not load the Gemini route' : 'Could not load model providers'}</h3>
            <p>{providerError}</p>
            <p>No inference request was sent. Check the gateway, then refresh providers.</p>
          </div>
        ) : !providers.length ? (
          <div className="inference-setup">
            <h3>{sentinelDraft ? 'Gemini is not connected to this gateway' : 'Connect the Gemini route'}</h3>
            <p>{sentinelDraft ? 'AI Sentinel needs a connected Gemini provider and an authenticated inference worker. Your source stays here until you approve a model request.' : 'Connect a Gemini provider and an authenticated inference worker to send model requests through this workspace.'}</p>
            <p>{localGateway ? 'Configure Gemini for this local gateway in the setup guide.' : 'The gateway operator manages model access and worker configuration.'} Python compute remains available.</p>
            {onOpenSetup && <button className="console-button secondary" onClick={onOpenSetup}>Open Gemini setup</button>}

          </div>
        ) : <form onSubmit={review}>
          <label>Provider and model<select value={providerId} onChange={change(setProviderId)} disabled={locked}>{providers.map(item => <option key={item.id} value={item.id}>{item.name} · {item.model}</option>)}</select></label>
          {provider && <p className="inference-provider-status">{provider.protocol === 'gemini_generate_content' ? 'Google Gemini API' : 'Operator-hosted model server'} · {provider.available_workers} matching worker{provider.available_workers === 1 ? '' : 's'} registered · {provider.rate_lamports_sec.toLocaleString()} lamports / second</p>}
          {provider && !hasMatchingInferenceWorker(provider) && <p className="inference-disclosure" role="status">No active worker matches this offer. Refresh after its worker connects; you cannot request a quote while it is offline.</p>}
          <label>{sentinelDraft ? 'AI Sentinel review prompt' : 'Prompt'}<textarea aria-label={sentinelDraft ? 'AI Sentinel review prompt' : 'Prompt'} value={prompt} onChange={change(setPrompt)} rows={7} maxLength={16000} required disabled={locked} /></label>
          {sentinelDraft && !sentinelPromptMatchesSource && <p className="inference-disclosure" role="status">Custom prompt: this response will remain a model result and will not be linked to the source in Studio.</p>}
          <div className="inference-limits"><label>Output token limit<input type="number" min="1" max={provider?.max_output_tokens || 4096} value={maxTokens} onChange={change(setMaxTokens)} required disabled={locked} /></label><label>Task budget · lamports<input type="number" min="1" max="1000000000" value={budget} onChange={change(setBudget)} required disabled={locked} /></label><label>Runtime limit · seconds<input type="number" min="1" max="180" value={runtime} onChange={change(setRuntime)} required disabled={locked} /></label></div>
          <p className="inference-disclosure">Your prompt is sent to the selected model operator after approval. Pricing uses elapsed time, including provider waiting. The output token limit is sent to the provider; token metering is not independently verified.</p>
          <button className="console-button primary" disabled={locked || connecting || !gatewayHealth || !hasMatchingInferenceWorker(provider)}>{working ? 'Preparing…' : connecting ? 'Connecting…' : wallet ? 'Review quote' : 'Connect wallet to review'}<Icon name="arrow" size={17} /></button>
        </form>}
      </section>
      <aside className="inference-evidence"><section className="console-panel"><h3>Authorization & result</h3><p className="inference-network">{gatewayHealth?.demo_mode ? 'OFF_CHAIN · no Solana payment' : gatewayHealth ? 'Solana Devnet · funded channel required' : 'Gateway connection required'}</p>
        {onOpenFunding && <button className="console-text-button" disabled={locked} onClick={onOpenFunding}>{gatewayHealth?.demo_mode ? 'Inspect signing identity' : 'Manage shared payment channel'}<Icon name="arrow" size={15} /></button>}
        {quote && !active && !result && <div className="inference-quote"><dl><div><dt>Model</dt><dd>{quote.workload.parameters.offer.model}</dd></div><div><dt>Tariff</dt><dd>{quote.rate_lamports} lamports / second</dd></div><div><dt>Maximum authorized cost</dt><dd>{quote.max_cost_lamports} lamports</dd></div><div><dt>Budgeted runtime</dt><dd>{quote.effective_runtime_seconds} seconds</dd></div></dl><button className="console-button primary" onClick={submit} disabled={locked || !signMessage}>Sign & run inference</button></div>}
        {active && <div role="status"><p>{run.pending ? 'Admission awaiting confirmation' : 'Inference running or awaiting settlement'} · {elapsed}s</p>{run.pending ? <button className="console-button" onClick={submit} disabled={working}>Retry saved authorization</button> : <button className="console-button" onClick={stop}>Stop request</button>}<p>Recovery stays in this browser tab. An interrupted provider request is never automatically re-executed.</p>{liveOutput && <div className="inference-result"><p>Live output · awaiting signed receipt</p><pre>{liveOutput}</pre></div>}</div>}
        {result && <div className="inference-result"><p className="console-tag">{result.verification.verified ? 'Receipt integrity verified' : 'Receipt verification failed'}</p><p>{result.verification.reason}</p>{result.verification.verified && <p>Signatures and output bytes match the approved task. Model identity and answer quality are not evaluated.</p>}<p>Execution: {result.receipt.execution_status} · Settlement: {result.receipt.settlement_type}</p>{result.verification.verified && <>{linkedSentinelRun && <div className="sentinel-report"><strong>AI Sentinel advisory{sentinelReport ? ` · ${sentinelReport.security}` : ' · manual review required'}</strong><p>This model output is not an execution approval or a guarantee of safety. Confirm findings against the source and gateway policy.</p>{sentinelReport?.reason && <p>{sentinelReport.reason}</p>}{sentinelReport && <dl><div><dt>CPU estimate</dt><dd>{sentinelReport.cpu ?? 'Unknown'}</dd></div><div><dt>RAM estimate</dt><dd>{sentinelReport.ram ?? 'Unknown'}</dd></div><div><dt>Network estimate</dt><dd>{sentinelReport.network ?? 'Unknown'}</dd></div><div><dt>Runtime estimate</dt><dd>{sentinelReport.predicted_sec == null ? 'Unknown' : `${sentinelReport.predicted_sec}s`}</dd></div></dl>}{sentinelReport?.findings?.length > 0 && <ul>{sentinelReport.findings.map((finding, index) => <li key={index}><strong>{finding.severity}{finding.line ? ` · line ${finding.line}` : ''}</strong> — {finding.issue}{finding.evidence && <small>{finding.evidence}</small>}</li>)}</ul>}</div>}<pre>{inferenceText(result.output)}</pre><details><summary>Raw output & signed task receipt</summary><pre>{result.output}</pre><pre>{JSON.stringify(result.receipt, null, 2)}</pre></details></>}</div>}
        {!quote && !active && !result && <p>Review a quote to inspect the exact provider, spending ceiling and runtime before signing.</p>}
      </section><details className="inference-boundary"><summary>Pricing and receipt details</summary><p className="inference-disclosure">Offers are configured by the gateway operator. On confirmed Devnet settlement, 100% of the measured task charge goes to the assigned worker key; local OFF_CHAIN runs make no Solana payment. Upstream model API bills are paid outside Aperture. Receipts identify signing keys but do not prove model identity or answer correctness.</p></details></aside>
    </div>
    {notice && <p className="inference-notice" role="status">{notice}</p>}
  </div>;
}
