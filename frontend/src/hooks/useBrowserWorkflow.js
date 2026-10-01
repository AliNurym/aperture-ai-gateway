import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { canonicalJson, sha256Hex } from '../utils/protocol';
import { saveFile } from '../utils/downloadFile';
import { WORKFLOW_STORAGE_KEY, TASK_ID, check, clone, same, workflowContext,
  validateBrowserPlan, verifyWorkflowQuote, verifyUserSignature, resolveStepManifest, workflowRequest,
  verifyCompletedStep, downloadWorkflowArtifact, publicWorkflow } from '../utils/browserWorkflows';

const ACTIVE = new Set(['admitting', 'running']);
const STATES = new Set(['pending', 'quoted', 'admitting', 'running', 'completed', 'failed']);
const TERMINAL = new Set(['completed', 'failed', 'stopped']);

export default function useBrowserWorkflow({ apiUrl, gatewayHealth, gatewayOnline, publicKey, signMessage,
  connection, externalBusy = false, onBusyChange }) {
  const [run, setRun] = useState(null);
  const [quote, setQuote] = useState(null);
  const [phase, setPhase] = useState('draft');
  const [notice, setNotice] = useState('');
  const [journalBlocked, setJournalBlocked] = useState(false);
  const live = useRef({ apiUrl, gatewayHealth, gatewayOnline, publicKey, signMessage, connection, externalBusy });
  const journal = useRef(null);
  const loaded = useRef(false);
  const blocked = useRef(false);
  const mounted = useRef(false);
  const operation = useRef(false);
  const stopOperation = useRef(false);
  const phaseRef = useRef('draft');
  const heldLock = useRef(null);
  const monitorRef = useRef(null);
  const timer = useRef(null);
  const needsRestore = useRef(false);
  useLayoutEffect(() => { live.current = { apiUrl, gatewayHealth, gatewayOnline, publicKey, signMessage, connection, externalBusy }; },
    [apiUrl, gatewayHealth, gatewayOnline, publicKey, signMessage, connection, externalBusy]);

  function showPhase(value, message = '') {
    phaseRef.current = value;
    if (mounted.current) { setPhase(value); setNotice(message); }
  }
  function present(value) { if (mounted.current) setRun(publicWorkflow(value)); }
  function persist(value) {
    const previous = journal.current;
    const storedText = sessionStorage.getItem(WORKFLOW_STORAGE_KEY);
    if (previous) {
      const stored = storedText ? JSON.parse(storedText) : null;
      check(stored?.id === previous.id && stored.revision === previous.revision, 'Workflow journal changed in this tab; reload it before another action.');
    } else check(!storedText, 'Another private workflow journal is retained. Recover or clear it first.');
    const next = { ...value, revision: (previous?.revision ?? 0) + 1 };
    const text = JSON.stringify(next);
    check(new TextEncoder().encode(text).length <= 4000000, 'This workflow exceeds private tab storage. Use the durable SDK/MCP runner.');
    try { sessionStorage.setItem(WORKFLOW_STORAGE_KEY, text); }
    catch { throw new Error('Private tab storage could not save the checkpoint. An existing admission may still be active; retain and recover the current journal before further approvals.'); }
    journal.current = next; present(next);
    return next;
  }
  function updateStep(id, changes) {
    const current = journal.current;
    return persist({ ...current, steps: current.steps.map(step => step.id === id ? { ...step, ...changes } : step) });
  }
  function ensureContext(current, signing = false) {
    check(mounted.current && current && !blocked.current, 'No valid private workflow journal is available.');
    const props = live.current;
    check(props.gatewayOnline && props.gatewayHealth, 'The configured gateway is unavailable. Resume when its identity can be checked.');
    const expected = workflowContext(props.apiUrl, current.context.owner, props.gatewayHealth);
    check(same(expected, current.context), 'The gateway, network or deployment pins changed. Restore the original configuration before continuing.');
    if (signing) {
      check(props.publicKey?.toBase58() === current.context.owner && props.signMessage, 'Reconnect the original signing wallet to continue this workflow.');
      check(!props.externalBusy, 'Compute Studio or a channel operation is currently active.');
    }
  }
  function ensureCurrent(id, signing = false) {
    const current = journal.current;
    check(current?.id === id, 'The active workflow changed.');
    ensureContext(current, signing);
    return current;
  }
  async function acquire(current) {
    const name = 'aperture-browser-channel:' + await sha256Hex(canonicalJson(current.context));
    if (heldLock.current?.name === name) return;
    check(navigator.locks?.request, 'This browser cannot coordinate safe workflow admission across tabs. Use the SDK/MCP runner.');
    check(!heldLock.current, 'Another workflow context still holds this tab channel.');
    await new Promise((resolve, reject) => {
      navigator.locks.request(name, { mode: 'exclusive', ifAvailable: true }, async lock => {
        if (!lock) { reject(new Error('Another browser tab owns this wallet workflow. Continue there or close its workflow first.')); return; }
        let release;
        const completion = new Promise(done => { release = done; });
        heldLock.current = { name, release }; resolve();
        await completion;
      }).catch(reject);
    });
  }
  function releaseLock() { heldLock.current?.release(); heldLock.current = null; }
  function stopMonitor() {
    clearTimeout(timer.current);
    timer.current = null;
    monitorRef.current?.controller.abort(); monitorRef.current = null;
  }
  function nextStep(current) {
    return current.plan.steps.find(step => current.steps.find(saved => saved.id === step.id).state !== 'completed');
  }
  async function healthAndChannel(current, maximumCost = null) {
    ensureContext(current);
    const health = await workflowRequest(current.context, '/health');
    check(same(workflowContext(current.context.api_url, current.context.owner, health), current.context), 'Gateway identity changed during this operation.');
    ensureCurrent(current.id);
    if (maximumCost !== null) check(health.status === 'ready' && health.worker_auth_configured && health.data_job_version === 1, 'An authenticated data-job worker must be ready before approval.');
    if (current.context.network === 'devnet' && maximumCost !== null) {
      const [config, channel] = await Promise.all([
        workflowRequest(current.context, '/channel-config'),
        workflowRequest(current.context, '/balance/' + current.context.owner),
      ]);
      ensureCurrent(current.id);
      check(config.initialized && config.version === 2 && config.program_id === current.context.program_id
        && config.oracle === current.context.gateway_pubkey && config.treasury === current.context.treasury, 'The Devnet protocol configuration differs from the pinned deployment.');
      check(channel.wallet === current.context.owner && channel.initialized && Number.isSafeInteger(channel.lamports)
        && channel.lamports >= (maximumCost || 0) && channel.burn_rate_lamports === 0, 'Fund an idle compatible channel before approving this step.');
      check(live.current.connection && await live.current.connection.getGenesisHash() === 'GH7ome3EiwEr7tu9JuTh2dpYWBJK3z69Xm1ZE3MEE6JC', 'The independent RPC is not Solana Devnet.');
    }
    ensureCurrent(current.id);
  }
  async function verifyDependencies(current, step) {
    for (const dependency of step.depends_on) {
      const saved = journal.current.steps.find(item => item.id === dependency);
      check(saved?.state === 'completed', 'A dependency has not completed successfully.');
      const approved = current.plan.steps.find(item => item.id === dependency);
      const spec = await resolveStepManifest(journal.current, approved);
      await verifyWorkflowQuote(saved.quote, approved, spec, current.context, true);
      await verifyCompletedStep(current.context, saved, live.current.connection);
      ensureCurrent(current.id);
      check(saved.receipt.execution_status === 'completed', 'A dependency did not complete successfully.');
      updateStep(dependency, { verified: true, artifacts: clone(saved.receipt.artifacts || []) });
    }
  }
  function finishPhase() {
    const current = journal.current;
    if (current.steps.some(step => ACTIVE.has(step.state))) return;
    if (current.steps.some(step => step.state === 'failed')) showPhase(current.stop_requested ? 'stopped' : 'failed', 'The current step did not complete; downstream approvals are withheld.');
    else if (current.steps.every(step => step.state === 'completed' && step.verified)) showPhase('completed', 'Every step and result receipt has been verified.');
    else if (current.stop_requested) showPhase('stopped', 'This workflow is stopped. Completed results remain available.');
    else showPhase('ready', 'Review the next step before approving another wallet signature.');
    if (TERMINAL.has(phaseRef.current)) releaseLock();
  }
  async function cancelActive(current, saved) {
    ensureCurrent(current.id);
    await workflowRequest(current.context, '/stop/' + saved.task_id, { method: 'POST', token: saved.token });
    ensureCurrent(current.id);
  }
  function monitor(current) {
    if (monitorRef.current || !mounted.current) return;
    const saved = current.steps.find(step => step.state === 'running');
    if (!saved) { finishPhase(); return; }
    const owner = { id: current.id, stepId: saved.id, controller: new AbortController(), cancelled: false };
    monitorRef.current = owner;
    const tick = async () => {
      if (monitorRef.current !== owner) return;
      try {
        const latest = ensureCurrent(owner.id);
        const item = latest.steps.find(step => step.id === owner.stepId);
        if (latest.stop_requested && !owner.cancelled) { await cancelActive(latest, item); owner.cancelled = true; }
        const result = await workflowRequest(latest.context, '/result/' + item.task_id,
          // JSON escapes can expand a bounded one-megabyte UTF-8 log sixfold.
          { token: item.token, signal: owner.controller.signal, maximum: 6500000 });
        ensureCurrent(owner.id);
        check(['queued', 'starting', 'running', 'settlement_pending', 'completed'].includes(result?.status), 'Gateway returned an invalid task status.');
        if (result.status === 'completed') {
          showPhase('verifying', 'Checking the gateway, worker and settlement evidence.');
          const candidate = { ...item, receipt: result.receipt };
          const approved = latest.plan.steps.find(step => step.id === item.id);
          await verifyWorkflowQuote(item.quote, approved, await resolveStepManifest(journal.current, approved), latest.context, true);
          await verifyCompletedStep(latest.context, candidate, live.current.connection, owner.controller.signal);
          ensureCurrent(owner.id);
          updateStep(item.id, { state: result.receipt.execution_status === 'completed' ? 'completed' : 'failed',
            receipt: clone(result.receipt), artifacts: clone(result.receipt.artifacts || []), verified: true });
          stopMonitor(); finishPhase();
          return;
        }
        showPhase('running', latest.stop_requested ? 'Cancellation requested; waiting for the verified final receipt.' : 'The approved step is ' + result.status.replaceAll('_', ' ') + '.');
        timer.current = setTimeout(tick, 1500);
      } catch (error) {
        if (monitorRef.current !== owner) return;
        stopMonitor(); showPhase('attention', error.message || 'Monitoring paused. Keep the private workflow journal.');
      }
    };
    showPhase('running'); tick();
  }
  async function action(callback, preservePhase = false, reportError = false) {
    if (operation.current) {
      if (reportError) throw new Error('Wait for the current workflow operation to finish, then open the file again.');
      return;
    }
    operation.current = true;
    try { check(loaded.current && !blocked.current, 'Wait for the retained workflow journal to load.'); return await callback(); }
    catch (error) {
      const message = error.message || 'Workflow action paused. Retain the journal.';
      if (preservePhase) { if (mounted.current) setNotice(message); }
      else showPhase(journal.current?.stop_requested && !journal.current.steps.some(step => ACTIVE.has(step.state)) ? 'stopped' : 'attention', message);
      if (reportError) throw error;
    }
    finally { operation.current = false; if (!journal.current) releaseLock(); }
  }
  async function verifySavedAdmission(current, saved, step, spec) {
    const body = saved.signedBody;
    check(Array.isArray(body?.signature) && body.signature.length === 64
      && body.signature.every(byte => Number.isInteger(byte) && byte >= 0 && byte <= 255), 'Saved admission signature is invalid.');
    check(same(body, { quote_id: saved.quote.quote_id, code: step.source, wallet: current.context.owner,
      agent_pubkey: current.context.owner, signature: body.signature, message: saved.quote.message,
      job_version: 1, inputs: spec.inputs, parameters: spec.parameters }), 'Saved admission body differs from the approved plan.');
    await verifyUserSignature(current.context.owner, Uint8Array.from(body.signature), saved.quote.message);
  }
  async function restoreEvidence() {
    const current = journal.current;
    ensureContext(current);
    await acquire(current);
    for (const saved of current.steps) {
      if (!saved.quote) continue;
      const step = current.plan.steps.find(item => item.id === saved.id);
      const spec = await resolveStepManifest(journal.current, step);
      await verifyWorkflowQuote(saved.quote, step, spec, current.context, true);
      ensureCurrent(current.id);
      if (saved.signedBody) await verifySavedAdmission(current, saved, step, spec);
      if (saved.state === 'completed' || saved.state === 'failed') {
        await verifyCompletedStep(current.context, saved, live.current.connection);
        ensureCurrent(current.id);
        updateStep(saved.id, { state: saved.receipt.execution_status === 'completed' ? 'completed' : 'failed',
          verified: true, artifacts: clone(saved.receipt.artifacts || []) });
      }
    }
    needsRestore.current = false;
    if (journal.current.steps.some(step => step.state === 'admitting')) showPhase('attention', 'A signed admission is retained. Recover that exact authorization before another step.');
    else if (journal.current.steps.some(step => step.state === 'running')) monitor(journal.current);
    else {
      const quoted = journal.current.steps.find(step => step.state === 'quoted');
      if (quoted && !journal.current.stop_requested) { if (mounted.current) setQuote({ ...clone(quoted.quote), step_id: quoted.id }); showPhase('quoted'); }
      else finishPhase();
    }
  }
  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    (async () => {
      try {
        const text = sessionStorage.getItem(WORKFLOW_STORAGE_KEY);
        if (!text) { loaded.current = true; showPhase('draft'); return; }
        showPhase('preparing', 'Loading the private workflow checkpoint.');
        const value = JSON.parse(text);
        check(value.version === 1 && value.context && Number.isSafeInteger(value.revision) && value.revision > 0, 'Retained workflow journal is invalid.');
        const plan = await validateBrowserPlan(value.plan);
        check(same(plan, value.plan) && value.id === await sha256Hex(canonicalJson({ context: value.context, plan })), 'Retained workflow fingerprint differs from its plan or deployment.');
        check(Array.isArray(value.steps) && value.steps.length === plan.steps.length
          && value.steps.every((step, index) => step.id === plan.steps[index].id && STATES.has(step.state))
          && value.steps.filter(step => ACTIVE.has(step.state)).length <= 1, 'Retained workflow step states are invalid.');
        const unfinished = value.steps.findIndex(step => step.state !== 'completed');
        check(unfinished < 0 || value.steps.slice(unfinished + 1).every(step => step.state === 'pending'), 'Retained workflow violates serial approval order.');
        for (const saved of value.steps) {
          if (saved.state !== 'pending') check(saved.quote, 'Retained step authorization is unavailable.');
          if (saved.state === 'admitting') check(saved.signedBody, 'Uncertain admission has no saved signed body.');
          if (['running', 'completed', 'failed'].includes(saved.state)) check(TASK_ID.test(saved.task_id)
            && typeof saved.token === 'string' && /^[A-Za-z0-9_-]{32,128}$/.test(saved.token), 'Retained task capability is invalid.');
          saved.verified = false;
        }
        if (cancelled) return;
        journal.current = value; present(value); loaded.current = true; needsRestore.current = true;
        showPhase('attention', 'Retained workflow loaded. Its task evidence will be checked against the original gateway.');
      } catch (error) {
        if (cancelled) return;
        blocked.current = true; loaded.current = true; setJournalBlocked(true);
        showPhase('attention', error.message + ' The private checkpoint was preserved.');
      }
    })();
    return () => { cancelled = true; mounted.current = false; stopMonitor(); releaseLock(); };
    // One hydration per mounted controller; live props are checked before every network operation.
  }, []);
  useEffect(() => {
    if (needsRestore.current && loaded.current && journal.current && gatewayOnline && gatewayHealth && !operation.current) action(restoreEvidence);
    // Restoring evidence never admits a task; action uses checked live refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gatewayOnline, gatewayHealth, run?.id]);

  const busy = journalBlocked || Boolean(run && (!TERMINAL.has(phase) || run.steps.some(step => ACTIVE.has(step.state))));
  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);

  const prepare = plan => action(async () => {
    check(!journal.current, 'Clear the current safe workflow before preparing another plan.');
    check(!live.current.externalBusy, 'Compute Studio or an upload is active.');
    showPhase('preparing');
    const validated = await validateBrowserPlan(plan);
    check(live.current.publicKey && live.current.gatewayOnline, 'Connect your wallet and a configured gateway first.');
    const context = workflowContext(live.current.apiUrl, live.current.publicKey.toBase58(), live.current.gatewayHealth);
    const current = { version: 1, context, plan: validated, id: await sha256Hex(canonicalJson({ context, plan: validated })),
      started: Date.now(), stop_requested: false, steps: validated.steps.map(step => ({ id: step.id, state: 'pending', artifacts: [] })) };
    await acquire(current);
    ensureContext(current, true);
    persist(current); showPhase('ready', 'Plan bounds and dependencies are validated. Review the first step.');
  });
  const reviewNext = () => action(async () => {
    const current = journal.current;
    ensureContext(current, true);
    check(!current.stop_requested && !current.steps.some(step => ACTIVE.has(step.state) || step.state === 'failed'), 'Recover the active task or retain the stopped/failed workflow before another quote.');
    await acquire(current); showPhase('quoting');
    const step = nextStep(current); check(step, 'Every workflow step is already completed.');
    await verifyDependencies(current, step);
    const spec = await resolveStepManifest(journal.current, step);
    ensureCurrent(current.id, true); check(!journal.current.stop_requested, 'Workflow was stopped before approval.');
    await healthAndChannel(current, step.max_cost_lamports);
    ensureCurrent(current.id, true);
    const approved = await workflowRequest(current.context, '/quotes', { method: 'POST', body: {
      wallet: current.context.owner, agent_pubkey: current.context.owner, code: step.source,
      max_cost_lamports: step.max_cost_lamports, max_runtime_seconds: step.max_runtime_seconds,
      job_version: 1, inputs: spec.inputs, parameters: spec.parameters } });
    await verifyWorkflowQuote(approved, step, spec, current.context);
    ensureCurrent(current.id, true); check(!journal.current.stop_requested, 'Workflow was stopped before approval.');
    updateStep(step.id, { state: 'quoted', quote: clone(approved) });
    if (mounted.current) setQuote({ ...clone(approved), step_id: step.id });
    showPhase('quoted', 'Review this step, its rate and maximum cost. Signing approves only this step.');
  });
  async function accept(current, saved, data) {
    check(TASK_ID.test(data?.task_id) && /^[A-Za-z0-9_-]{32,128}$/.test(data?.task_access_token || '')
      && data.quote_id === saved.quote.quote_id && data.code_sha256 === saved.quote.code_sha256,
    'Admission response is incomplete; retain the exact saved request.');
    ensureCurrent(current.id);
    updateStep(saved.id, { state: 'running', task_id: data.task_id, token: data.task_access_token, signedBody: null });
    if (mounted.current) setQuote(null);
    monitor(journal.current);
  }
  const signNext = () => action(async () => {
    const current = journal.current;
    ensureContext(current, true); await acquire(current);
    check(!current.stop_requested && !current.steps.some(step => ACTIVE.has(step.state)), 'Current admission must be recovered before another signature.');
    const step = nextStep(current), saved = current.steps.find(item => item.id === step?.id);
    check(saved?.state === 'quoted', 'Review the next step before signing.');
    const spec = await resolveStepManifest(current, step);
    await verifyDependencies(current, step);
    await verifyWorkflowQuote(saved.quote, step, spec, current.context);
    await healthAndChannel(current, step.max_cost_lamports);
    ensureCurrent(current.id, true); check(!journal.current.stop_requested, 'Workflow was stopped before signing.');
    showPhase('signing', 'Approve this one step in your wallet.');
    const signature = await live.current.signMessage(new TextEncoder().encode(saved.quote.message));
    ensureCurrent(current.id, true); check(!journal.current.stop_requested, 'Workflow was stopped; no admission was submitted.');
    await verifyWorkflowQuote(saved.quote, step, spec, current.context);
    await verifyUserSignature(current.context.owner, signature, saved.quote.message);
    ensureCurrent(current.id, true); check(!journal.current.stop_requested, 'Workflow was stopped; no admission was submitted.');
    const signedBody = { quote_id: saved.quote.quote_id, wallet: current.context.owner, agent_pubkey: current.context.owner,
      code: step.source, message: saved.quote.message, signature: Array.from(signature), job_version: 1,
      inputs: spec.inputs, parameters: spec.parameters };
    updateStep(step.id, { state: 'admitting', signedBody });
    showPhase('submitting', 'The signed request is saved before admission.');
    const data = await workflowRequest(current.context, '/execute', { method: 'POST', body: signedBody });
    await accept(current, journal.current.steps.find(item => item.id === step.id), data);
  });
  async function historyRequest(current, actionName, taskId = null, cursor = null) {
    ensureCurrent(current.id, true);
    const issued_at = Math.floor(Date.now() / 1000), nonce = crypto.randomUUID().replaceAll('-', '');
    const message = 'Aperture agent task access v1\naudience:aperture-gateway\n' + canonicalJson({ action: actionName,
      owner: current.context.owner, agent_pubkey: current.context.owner, issued_at, nonce, task_id: taskId,
      limit: actionName === 'list' ? 50 : null, cursor, program_id: current.context.program_id,
      gateway_pubkey: current.context.gateway_pubkey, network: current.context.network });
    showPhase('signing', 'Approve task-history access to recover the original authorization.');
    const signature = await live.current.signMessage(new TextEncoder().encode(message));
    ensureCurrent(current.id, true); await verifyUserSignature(current.context.owner, signature, message);
    const body = { owner: current.context.owner, agent_pubkey: current.context.owner, issued_at, nonce,
      signature: Array.from(signature), ...(actionName === 'list' ? { limit: 50, cursor } : { task_id: taskId }) };
    return workflowRequest(current.context, '/agents/tasks/' + actionName, { method: 'POST', body });
  }
  const recover = () => action(async () => {
    const current = journal.current; ensureContext(current); showPhase('preparing', 'Checking the original retained admission.'); await acquire(current);
    const saved = current.steps.find(step => step.state === 'admitting');
    check(saved?.signedBody, 'There is no saved uncertain admission to recover.');
    const step = current.plan.steps.find(item => item.id === saved.id);
    const spec = await resolveStepManifest(current, step);
    await verifyWorkflowQuote(saved.quote, step, spec, current.context, true);
    await verifySavedAdmission(current, saved, step, spec);
    await healthAndChannel(current);
    if (ensureCurrent(current.id).stop_requested || saved.quote.expires_at * 1000 <= Date.now()) {
      const seen = new Set(); let cursor = null, match = null;
      for (let page = 0; page < 200; page += 1) {
        const result = await historyRequest(current, 'list', null, cursor);
        check(Array.isArray(result.tasks) && result.tasks.length <= 50, 'Task history response is invalid.');
        match = result.tasks.find(item => item.quote_id === saved.quote.quote_id);
        if (match || result.next_cursor === null) break;
        check(TASK_ID.test(result.next_cursor) && !seen.has(result.next_cursor), 'Task history cursor is invalid.');
        cursor = result.next_cursor; seen.add(cursor);
      }
      check(match && TASK_ID.test(match.task_id), 'The original admission is still unconfirmed. Its journal is retained; no replacement task was submitted.');
      const response = await historyRequest(current, 'resume', match.task_id);
      check(response.task_id === match.task_id && same(response.quote, saved.quote), 'Recovered task differs from the saved authorization.');
      await accept(current, saved, response);
      return;
    }
    showPhase('submitting', 'Recovering only the exact saved signed authorization.');
    check(!ensureCurrent(current.id).stop_requested, 'Stop intent was saved; use history-only recovery to locate the original task.');
    const response = await workflowRequest(current.context, '/execute', { method: 'POST', body: saved.signedBody });
    await accept(current, saved, response);
  });
  const stop = async () => {
    if (stopOperation.current) return;
    stopOperation.current = true;
    try {
      const current = journal.current; check(current, 'No workflow is prepared.');
      let checkpointError = null;
      try { persist({ ...current, stop_requested: true }); }
      catch (error) {
        // Even if storage is unavailable, an in-flight signature must never admit
        // more work after the user stops. Keep the previous durable revision.
        journal.current = { ...journal.current, stop_requested: true }; present(journal.current);
        checkpointError = error;
      }
      showPhase('preparing', 'Stopping further approvals and locating the active task.');
      await acquire(current);
      const latest = ensureCurrent(current.id);
      if (mounted.current) setQuote(null);
      const saved = latest.steps.find(step => step.state === 'running');
      if (saved) {
        await cancelActive(latest, saved);
        if (!monitorRef.current) monitor(journal.current);
        showPhase('running', 'Cancellation requested; waiting for the verified terminal receipt.');
      } else if (journal.current.steps.some(step => step.state === 'admitting')) showPhase('attention', 'Stop intent is saved. Recover the original task through signed history, then cancellation will be sent.');
      else { showPhase('stopped', 'Stop intent is saved. No later step will be signed or submitted.'); releaseLock(); }
      if (checkpointError) showPhase('attention', 'Stop intent could not be saved in private storage. This tab has halted further approvals and attempted cancellation; keep it open and recover the active task.');
    } catch (error) { showPhase('attention', error.message || 'Cancellation could not be confirmed. Keep the checkpoint.'); }
    finally { stopOperation.current = false; }
  };
  const resumeMonitoring = () => action(async () => {
    const current = journal.current; ensureContext(current); await acquire(current);
    if (needsRestore.current) await restoreEvidence();
    else { stopMonitor(); check(current.steps.some(step => step.state === 'running'), 'No retained task needs monitoring.'); monitor(journal.current); }
  });
  const readArtifact = (stepId, artifact) => action(async () => {
    const current = journal.current; ensureContext(current);
    const saved = current.steps.find(step => step.id === stepId);
    check(saved?.state === 'completed' && saved.verified, 'Verify the completed step before downloading its results.');
    const bytes = await downloadWorkflowArtifact(current.context, saved, artifact, live.current.connection);
    ensureCurrent(current.id);
    return bytes;
  }, true, true);
  const download = async (stepId, artifact) => {
    const bytes = await readArtifact(stepId, artifact);
    saveFile(stepId + '-' + artifact.name, bytes, 'application/octet-stream');
    if (mounted.current) setNotice('The verified file is ready to save. Its bytes match the signed receipt and SHA-256.');
  };
  const clear = () => {
    try {
      check(!operation.current && !stopOperation.current && !blocked.current && loaded.current, 'An active operation or retained invalid journal cannot be cleared safely.');
      check(!journal.current?.steps.some(step => ACTIVE.has(step.state)), 'Recover and conclude the admitted task before clearing its capability.');
      const stored = sessionStorage.getItem(WORKFLOW_STORAGE_KEY);
      check(!journal.current || JSON.parse(stored)?.id === journal.current.id, 'The stored workflow changed. Reload it before clearing.');
      sessionStorage.removeItem(WORKFLOW_STORAGE_KEY);
      stopMonitor(); releaseLock(); journal.current = null; needsRestore.current = false;
      if (mounted.current) { setRun(null); setQuote(null); }
      showPhase('draft');
    } catch (error) { showPhase('attention', error.message); }
  };
  return { run, quote, phase, busy, notice, prepare, reviewNext, signNext, recover, stop, resumeMonitoring, readArtifact, download, clear };
}
