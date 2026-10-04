import { useEffect, useState } from 'react';
import Icon from './components/Icon';
import ResultFiles from './components/ResultFiles';
import { validateObject } from './utils/jobs';
import { requestErrorMessage } from './utils/requestError';
import './WorkflowRun.css';

const ACTION_PHASES = new Set(['preparing', 'quoting', 'signing', 'submitting', 'running', 'verifying']);
const TERMINAL_PHASES = new Set(['completed', 'failed', 'stopped']);
const PHASE_LABELS = {
  draft: 'Prepare a useful chain', preparing: 'Saving your plan', ready: 'Ready for the next step',
  quoting: 'Reviewing the next step', quoted: 'Your next step is priced', signing: 'Waiting for your signature',
  submitting: 'Submitting the exact step', running: 'A step is running', verifying: 'Verifying the saved result',
  attention: 'Your workflow needs attention', completed: 'Workflow completed', failed: 'A step could not finish',
  stopped: 'Workflow stopped',
};
const STEP_LABELS = { pending: 'Planned', quoted: 'Awaiting signature', admitting: 'Admission pending', running: 'Running', verifying: 'Verifying', completed: 'Verified', failed: 'Failed' };

function sol(lamports) {
  return Number.isSafeInteger(lamports) && lamports >= 0
    ? (lamports / 1e9).toLocaleString('en-US', { maximumFractionDigits: 9 }) + ' SOL' : 'Unavailable';
}

function resultFiles(step) {
  if (step.state !== 'completed') return [];
  const files = step.artifacts ?? step.receipt?.artifacts ?? [];
  try {
    if (!Array.isArray(files) || files.length > 16) return [];
    files.forEach(item => validateObject(item, 8 * 1024 * 1024));
    if (new Set(files.map(item => item.name.toLowerCase())).size !== files.length || files.reduce((sum, item) => sum + item.size_bytes, 0) > 16 * 1024 * 1024) return [];
    return files;
  } catch { return []; }
}

export default function WorkflowRun({ controller, plan, connected, onConnect, gatewayReady, gatewayOnline = false, externalBusy = false }) {
  const { run, quote, phase = 'draft', notice = '' } = controller || {};
  const [localNotice, setLocalNotice] = useState('');
  const [readingFile, setReadingFile] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const steps = Array.isArray(run?.steps) ? run.steps : [];
  const plannedSteps = Array.isArray(run?.plan?.steps) ? run.plan.steps : [];
  const verified = steps.filter(step => step.state === 'completed').length;
  const admitted = steps.filter(step => typeof step.task_id === 'string').length;
  const admitting = steps.some(step => step.state === 'admitting');
  const running = steps.some(step => step.state === 'running');
  const verifying = steps.some(step => step.state === 'verifying');
  const inFlight = ACTION_PHASES.has(phase);
  const stopped = Boolean(run?.stop_requested);
  const total = Number.isSafeInteger(run?.total_steps) ? run.total_steps : steps.length;
  const nextStep = steps.find(step => ['pending', 'quoted'].includes(step.state));
  const approvedStep = plannedSteps.find(step => step.id === (quote?.step_id || nextStep?.id));
  const expiredQuote = Boolean(quote && Number.isSafeInteger(quote.expires_at) && quote.expires_at * 1000 <= now);
  const verifiedTerminal = (total > 0 && steps.length === total && steps.every(step => step.state === 'completed'))
    || steps.some(step => step.state === 'failed' && step.receipt);
  const canClear = Boolean(run && !inFlight && !admitting && !running && !verifying && !readingFile
    && (admitted === 0 || TERMINAL_PHASES.has(phase) || verifiedTerminal || stopped));
  const canStartStep = Boolean(run && nextStep && !stopped && !externalBusy && !inFlight && !admitting && !running && !verifying && !readingFile && connected && gatewayReady);
  const canStop = Boolean(run && !stopped && !TERMINAL_PHASES.has(phase));
  const displayedNotice = typeof notice === 'string' ? notice : notice?.message || '';
  const needsAttention = Boolean(localNotice) || ['failed', 'attention'].includes(phase);
  const inputFiles = Array.isArray(quote?.workload?.inputs) ? quote.workload.inputs : [];
  const filesCount = steps.reduce((sum, step) => sum + resultFiles(step).length, 0);
  const consumedSteps = new Set(plannedSteps.flatMap(step => (step.inputs || []).map(input => input.from_step).filter(Boolean)));
  const finalSteps = steps.filter(step => step.state === 'completed' && !consumedSteps.has(step.id) && resultFiles(step).length);

  useEffect(() => {
    if (phase !== 'quoted' || !quote) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [phase, quote]);
  useEffect(() => { setLocalNotice(''); }, [run?.id]);

  const act = async (name, ...args) => {
    setLocalNotice('');
    try {
      if (typeof controller?.[name] !== 'function') throw new Error('The workflow controller is not ready.');
      await controller[name](...args);
    } catch (error) { setLocalNotice(requestErrorMessage(error)); }
  };
  const fileAction = async (name, stepId, artifact) => {
    setReadingFile(true);
    try { return await controller[name](stepId, artifact); }
    finally { setReadingFile(false); }
  };

  return <section className="console-panel workflow-run" aria-labelledby="workflow-run-title" aria-busy={inFlight}>
    <div className="workflow-run-heading"><div><span className="console-eyebrow"><Icon name="network" size={16} /> BROWSER EXECUTION</span><h2 id="workflow-run-title">From a plan to useful files.</h2><p>Review and sign each step here. Verified outputs feed the next job in your saved chain.</p></div><span className={'console-tag ' + (phase === 'failed' || phase === 'attention' ? 'error' : 'neutral')}>{run ? run.network === 'devnet' ? 'Devnet' : run.network === 'off_chain' ? 'Off-chain' : 'Configured gateway' : 'Per-step approval'}</span></div>
    {(displayedNotice || localNotice) && <div className={'workflow-run-notice' + (needsAttention ? ' error' : '')} role={needsAttention ? 'alert' : 'status'}><Icon name={needsAttention ? 'shield' : phase === 'completed' ? 'check' : 'book'} size={18} /><p>{localNotice || displayedNotice}</p></div>}
    {externalBusy && <p className="workflow-run-hint" role="status">Another workspace operation is using the execution slot. Finish it before admitting another workflow step.</p>}
    {!run ? <div className="workflow-run-start"><div className="workflow-run-start-icon"><Icon name="network" size={28} /></div><div><h3>Prepare the current plan</h3><p>{plan ? plan.steps.length + ' planned steps · total maximum ' + sol(plan.max_cost_lamports) : 'Add uploaded batch references above to build a plan.'}</p><small>The prepared chain keeps its exact source, inputs and limits.</small></div><button className="console-button primary" disabled={!plan || externalBusy || inFlight || Boolean(connected && !controller)} onClick={() => connected ? act('prepare', plan) : onConnect?.()}><Icon name={connected ? 'shield' : 'wallet'} size={16} />{connected ? 'Prepare this plan' : 'Connect wallet'}</button></div>
      : <>
        <div className="workflow-run-state"><div><span className={'workflow-run-state-icon ' + (phase === 'completed' ? 'complete' : '')} data-busy={inFlight && phase !== 'signing'}><Icon name={phase === 'completed' ? 'check' : phase === 'attention' || phase === 'failed' ? 'shield' : inFlight && phase !== 'signing' ? 'refresh' : 'network'} spinning={inFlight && phase !== 'signing'} size={22} /></span><div><h3 aria-live="polite">{PHASE_LABELS[phase] || 'Workflow saved'}</h3><p>{verified} verified / {total} planned steps · {filesCount} verified result {filesCount === 1 ? 'file' : 'files'}</p></div></div><span className="workflow-run-owner" title={run.owner}>{run.owner ? run.owner.slice(0, 6) + '…' + run.owner.slice(-6) : 'Signing identity unavailable'}</span></div>
        {admitted > 0 ? <div className="workflow-run-progress"><progress max={Math.max(1, total)} value={verified} aria-label="Verified workflow steps" /><span>{admitted} admitted {admitted === 1 ? 'task' : 'tasks'}{admitting ? ' · admission still unresolved' : ''}</span></div> : <p className="workflow-run-no-admissions">{admitting ? 'An admission response is unresolved. Recover the exact signed request before creating another task.' : 'No tasks admitted. Preparing a plan and reviewing a quote do not execute its source.'}</p>}
        {stopped && <p className="workflow-run-hint" role="status">Stop requested. Further steps will not be admitted. {admitting ? 'Recover the exact request so the gateway can confirm the original task and its cancellation.' : running ? 'Monitoring continues until the active task returns a final receipt.' : 'Inspect the saved results below.'}</p>}
        {phase === 'failed' && <p className="workflow-run-hint">The chain stopped at the failed step. Its dependent work has not been admitted; verified results from earlier steps remain available.</p>}
        {quote && phase === 'quoted' && <section className="workflow-run-quote" aria-labelledby="workflow-step-quote"><div><span className="console-eyebrow">REVIEW THIS STEP</span><h3 id="workflow-step-quote">{quote.step_id || nextStep?.id || 'Next workload'}</h3></div><dl className="workflow-run-quote-bounds"><div><dt>{quote.analysis?.pricing === 'published_cpu_tariff_v1' ? 'Operator CPU tariff' : 'Source analysis rate'}</dt><dd>{sol(quote.rate_lamports)}/s</dd></div><div><dt>Maximum cost</dt><dd>{sol(quote.max_cost_lamports)}</dd></div><div><dt>Execution limit</dt><dd>{quote.effective_runtime_seconds}s</dd></div><div><dt>Quote expires</dt><dd>{expiredQuote ? 'Expired' : new Date(quote.expires_at * 1000).toLocaleTimeString()}</dd></div></dl><details><summary>Source, inputs and parameter evidence</summary><dl className="workflow-run-evidence"><div><dt>Source SHA-256</dt><dd>{quote.code_sha256}</dd></div><div><dt>Job manifest SHA-256</dt><dd>{quote.workload_sha256}</dd></div></dl>{inputFiles.length ? <ul className="workflow-run-inputs">{inputFiles.map(item => <li key={item.object_id}><strong>{item.name}</strong><span>{item.size_bytes.toLocaleString()} bytes</span><code>{item.sha256}</code></li>)}</ul> : <p>This step has no file inputs.</p>}<h4>Approved source · Python</h4><pre aria-label="Approved Python source for this step">{approvedStep?.source || 'Saved source unavailable. Reprepare the plan before approving a step.'}</pre><h4>Approved parameters</h4><pre>{JSON.stringify(quote.workload?.parameters || {}, null, 2)}</pre></details><p>Signing binds this step’s exact source, inputs, parameters and spending limit. Every subsequent step needs a separate wallet approval.</p></section>}
        <div className="workflow-run-actions">
          {!connected && !TERMINAL_PHASES.has(phase) && (nextStep || admitting) && <button className="console-button primary" onClick={onConnect}><Icon name="wallet" size={16} />Reconnect signing wallet</button>}
          {connected && phase === 'quoted' && !expiredQuote && <button className="console-button primary" disabled={!canStartStep || !approvedStep?.source} onClick={() => act('signNext')}><Icon name="play" size={16} />Sign & run this step</button>}
          {connected && (phase === 'ready' || phase === 'quoted' && expiredQuote) && <button className="console-button primary" disabled={!canStartStep} onClick={() => act('reviewNext')}><Icon name="shield" size={16} />{expiredQuote ? 'Review fresh quote' : verified > 0 ? 'Review next step' : 'Review first step'}</button>}
          {phase === 'attention' && admitting && <button className="console-button primary" disabled={externalBusy || inFlight || !connected || !gatewayOnline} onClick={() => act('recover')}><Icon name="refresh" size={16} />Recover exact signed request</button>}
          {phase === 'attention' && (running || verifying) && <button className="console-button secondary" disabled={inFlight || !gatewayOnline} onClick={() => act('resumeMonitoring')}><Icon name="refresh" size={16} />{verifying ? 'Verify saved results' : 'Resume task monitoring'}</button>}
          {phase === 'attention' && !admitting && !running && !verifying && nextStep && !stopped && <button className="console-button secondary" disabled={!canStartStep} onClick={() => act('reviewNext')}><Icon name="refresh" size={16} />Review next step again</button>}
          {inFlight && <span className="workflow-run-waiting" role="status"><Icon name={phase === 'signing' ? 'wallet' : 'refresh'} spinning={phase !== 'signing'} size={16} />{PHASE_LABELS[phase]}</span>}
          {canStop && <button className="console-button secondary" onClick={() => act('stop')}><Icon name="stop" size={16} />Stop workflow</button>}
          {canClear && <button className="console-text-button" onClick={() => act('clear')}><Icon name="close" size={15} />{admitted ? 'Clear finished journal' : 'Clear prepared plan'}</button>}
        </div>
        {!gatewayReady && !TERMINAL_PHASES.has(phase) && <p className="workflow-run-hint">Starting a new step needs a configured gateway and an authenticated worker. The current plan stays saved in this tab.</p>}
        {phase === 'completed' && finalSteps.length > 0 && <div className="workflow-run-results"><div><span className="console-eyebrow">YOUR RESULTS</span><h3>Ready to use.</h3><p>Open the report or download the verified files.</p></div>{finalSteps.map(step => <ResultFiles key={step.id} files={resultFiles(step)} scope={run.id + ':' + step.id} onRead={artifact => fileAction('readArtifact', step.id, artifact)} onDownload={artifact => fileAction('download', step.id, artifact)} />)}</div>}
        <details className="workflow-run-step-evidence" open={phase !== 'completed'}><summary>{phase === 'completed' ? 'Inspect ' + verified + ' verified steps and their receipts' : 'Workflow steps and result files'}</summary><ol className="workflow-run-steps" aria-label="Workflow step status">{steps.map((step, index) => {
          const source = plannedSteps.find(item => item.id === step.id);
          const artifacts = resultFiles(step);
          return <li key={step.id} className={'workflow-run-step ' + step.state}><div className="workflow-run-step-number">{step.state === 'completed' ? <Icon name="check" size={16} /> : index + 1}</div><div className="workflow-run-step-content"><div className="workflow-run-step-title"><h4>{step.id}</h4><span className={'console-tag ' + (step.state === 'failed' ? 'error' : step.state === 'completed' ? '' : 'neutral')}>{STEP_LABELS[step.state] || 'Saved'}</span></div><p>{source ? 'Maximum ' + sol(source.max_cost_lamports) + ' · ' + source.max_runtime_seconds + 's runtime cap' : 'Workload bounds retained in the saved plan'}{step.task_id && <span>Task · {step.task_id}</span>}</p>{artifacts.length > 0 && <ResultFiles files={artifacts} scope={run.id + ':' + step.id} disabled={inFlight} onRead={artifact => fileAction('readArtifact', step.id, artifact)} onDownload={artifact => fileAction('download', step.id, artifact)} />}{step.state === 'failed' && step.receipt?.execution_status && <p className="workflow-run-step-failure">Gateway receipt outcome: {step.receipt.execution_status}.</p>}</div></li>;
        })}</ol></details>
      </>}
    <details className="workflow-run-journal"><summary>This tab keeps the workflow journal</summary><p>Reloading this tab can restore its saved progress. Closing the tab clears its local journal; already admitted jobs continue on the gateway. Keep the tab open until you have downloaded the files you need.</p><p>Clearing a finished journal removes its browser recovery and download handles. It does not release stored files or cancel a gateway task. Each wallet approval applies to one step; this page never signs later steps automatically.</p>{run?.id && <p className="workflow-run-journal-id">Journal · {run.id}</p>}</details>
  </section>;
}
