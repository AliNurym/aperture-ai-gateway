import { useEffect, useRef, useState } from 'react';
import Icon from './components/Icon';
import { matchingInferenceWorkers, publicInferenceProviders, publicOffer } from './utils/inference';
import { createModelPlan } from './utils/modelWorkflowPlan';
import { canBuildMixedWorkflow, mixedWorkflowCapacityNotice, mixedWorkflowWorkerCapacity, workflowPlanNeedsModelOffer, workflowPlanNeedsPythonWorker } from './utils/mixedWorkflowStatus';
import { parseStepCost } from './utils/workflowPlan';
import { validateBrowserPlan } from './utils/browserWorkflows';

const EMPTY = [];
export default function MixedWorkflowBuilder({ apiUrl, disabled, onPlan, onOpenSetup }) {
  const [directory, setDirectory] = useState({ providers: EMPTY, workers: EMPTY });
  const [directoryState, setDirectoryState] = useState('loading');
  const [providerId, setProviderId] = useState('');
  const [modelWorker, setModelWorker] = useState('');
  const [cpuWorker, setCpuWorker] = useState('');
  const [prompt, setPrompt] = useState('Explain how a spending limit helps an autonomous AI agent.');
  const [cost, setCost] = useState('0.0001');
  const [runtime, setRuntime] = useState('30');
  const [tokens, setTokens] = useState('256');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [importedPlan, setImportedPlan] = useState(null);
  const planFile = useRef(null);
  useEffect(() => {
    const controller = new AbortController();
    setDirectoryState('loading');
    Promise.all(['/inference/providers', '/workers'].map(async path => {
      const response = await fetch(apiUrl + path, { signal: controller.signal, credentials: 'omit', redirect: 'error' });
      if (!response.ok) throw new Error('Could not read model and worker capacity.');
      return response.json();
    })).then(([models, nodes]) => {
      if (controller.signal.aborted) return;
      const providers = publicInferenceProviders(models.providers);
      setDirectory({ providers, workers: nodes.workers || [] });
      setProviderId(current => current || providers[0]?.id || '');
      setDirectoryState('ready');
    }).catch(() => { if (!controller.signal.aborted) setDirectoryState('unavailable'); });
    return () => controller.abort();
  }, [apiUrl, revision]);
  const provider = directory.providers.find(item => item.id === providerId);
  const modelCapacity = mixedWorkflowWorkerCapacity(
    provider ? matchingInferenceWorkers(directory.workers, provider, Date.now() / 1000, { includeStale: true }) : EMPTY, 'inference.chat');
  const pythonCapacity = mixedWorkflowWorkerCapacity(directory.workers, 'python');
  const modelWorkers = modelCapacity.eligible;
  const cpuWorkers = pythonCapacity.eligible;
  const importedUsesModelOffer = workflowPlanNeedsModelOffer(importedPlan);
  const importedNeedsPythonWorker = workflowPlanNeedsPythonWorker(importedPlan);
  const capacityNotice = mixedWorkflowCapacityNotice({
    directoryState,
    providerCount: directory.providers.length,
    modelWorkerCount: modelWorkers.length,
    pythonWorkerCount: cpuWorkers.length,
    needsModel: importedPlan ? importedUsesModelOffer : true,
    needsPython: importedPlan ? importedNeedsPythonWorker : true,
    modelRateLimitedCount: modelCapacity.rateLimited.length,
    pythonRateLimitedCount: pythonCapacity.rateLimited.length,
    pythonUnpricedCount: pythonCapacity.unpricedCount,
    modelStaleCount: modelCapacity.staleCount,
    pythonStaleCount: pythonCapacity.staleCount,
  });
  useEffect(() => {
    let cancelled = false;
    if (importedPlan) { onPlan(importedPlan); return undefined; }
    onPlan(null);
    if (!canBuildMixedWorkflow({
      directoryState,
      providerCount: directory.providers.length,
      modelWorkerCount: modelWorkers.length,
      pythonWorkerCount: cpuWorkers.length,
    })) {
      setNotice('');
      return undefined;
    }
    (async () => {
      const findTarget = (id, workers) => {
        if (!id) return undefined;
        const worker = workers.find(item => item.node_id === id);
        if (!worker) throw new Error('The selected executor is unavailable. Choose a worker explicitly.');
        return { node_id: worker.node_id, worker_pubkey: worker.worker_pubkey };
      };
      const parameters = { inference: { provider_id: provider.id, messages: [{ role: 'user', content: prompt }], max_tokens: Number(tokens) }, offer: publicOffer(provider) };
      return createModelPlan(parameters, parseStepCost(cost), Number(runtime), {
        model: findTarget(modelWorker, modelWorkers), cpu: findTarget(cpuWorker, cpuWorkers),
      });
    })().then(plan => { if (!cancelled) { onPlan(plan); setNotice('Three bounded steps. You approve each step before it starts.'); } })
      .catch(error => { if (!cancelled) setNotice(error.message); });
    return () => { cancelled = true; };
    // Directory arrays change only after an explicit refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, directory, directoryState, modelWorker, cpuWorker, prompt, cost, runtime, tokens, onPlan, importedPlan]);
  const importPlan = async event => {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file || disabled) return;
    try {
      if (file.size > 2000000) throw new Error('Choose a workflow JSON plan up to 2 MB.');
      const plan = await validateBrowserPlan(JSON.parse(await file.text()));
      setImportedPlan(plan); setNotice('Imported ' + plan.steps.length + ' validated steps. Inspect the source, explicit context files and limits before each approval.');
    } catch (error) { setNotice(error.message); }
  };
  const workerOptions = (workers, selected) => <>{selected && !workers.some(item => item.node_id === selected) && <option value={selected}>{selected} · unavailable</option>}{workers.map(worker => <option key={worker.node_id} value={worker.node_id}>{worker.node_id} · {worker.rate_lamports_sec.toLocaleString('en-US')} lamports/s</option>)}</>;
  return <section className="console-panel mixed-workflow" aria-labelledby="mixed-workflow-title">
    <div className="console-section-heading"><div><h2 id="mixed-workflow-title">{importedPlan ? 'Imported workflow plan' : 'Model → Python → model'}</h2><p>{importedPlan ? importedUsesModelOffer && importedNeedsPythonWorker ? 'Review the model requests, Python steps, dependencies and limits before approval.' : importedUsesModelOffer ? 'Review each model request and its spending limit before approval.' : 'Review the Python sources, input files, dependencies and limits before preparation.' : 'Generate text, measure it in Python, then interpret verified statistics.'}</p></div><button className="console-text-button mixed-workflow-refresh" disabled={disabled} onClick={() => setRevision(value => value + 1)} aria-label="Refresh capacity" title="Refresh capacity"><Icon name="refresh" size={16} /><span className="mixed-workflow-refresh-label">Refresh capacity</span></button></div>
    <div className="mixed-workflow-export"><button className="console-text-button" disabled={disabled} onClick={() => planFile.current.click()}><Icon name="upload" size={16} />Import workflow plan</button><input ref={planFile} type="file" accept=".json,application/json" hidden onChange={importPlan} />{importedPlan && <button className="console-text-button" disabled={disabled} onClick={() => setImportedPlan(null)}>Use three-step builder</button>}</div>
    {capacityNotice && <div className="mixed-workflow-capacity-layout"><div className="mixed-workflow-capacity-state" data-state={capacityNotice.state} role="status" aria-live="polite" aria-busy={capacityNotice.state === 'loading' ? 'true' : undefined}><Icon name={capacityNotice.state === 'loading' ? 'refresh' : 'network'} size={18} spinning={capacityNotice.state === 'loading'} /><div><strong>{capacityNotice.title}</strong><p>{capacityNotice.message}</p></div></div>{capacityNotice.action && onOpenSetup && <button className="console-button primary mixed-workflow-capacity-action" disabled={disabled} onClick={onOpenSetup}>{capacityNotice.action}<Icon name="arrow" size={16} /></button>}</div>}
    {!importedPlan && <fieldset disabled={disabled}><div className="mixed-workflow-fields">
      <label>Model offer<select value={providerId} onChange={event => setProviderId(event.target.value)}><option value="">Choose a configured model</option>{directory.providers.map(item => <option key={item.id} value={item.id}>{item.name} · {item.model}</option>)}</select></label>
      <label>Model executor<select value={modelWorker} onChange={event => setModelWorker(event.target.value)}><option value="">Automatic · lowest compatible rate</option>{workerOptions(modelWorkers, modelWorker)}</select></label>
      <label>Python executor<select value={cpuWorker} onChange={event => setCpuWorker(event.target.value)}><option value="">Automatic · lowest compatible rate</option>{workerOptions(cpuWorkers, cpuWorker)}</select></label>
      <label>Spend cap per step · SOL<input value={cost} onChange={event => setCost(event.target.value)} inputMode="decimal" /></label>
      <label>Runtime per step · seconds<input type="number" min="1" max="180" value={runtime} onChange={event => setRuntime(event.target.value)} /></label>
      <label>Maximum output tokens<input type="number" min="1" max={provider?.max_output_tokens || 4096} value={tokens} onChange={event => setTokens(event.target.value)} /></label>
    </div><label className="mixed-workflow-prompt">First model request<textarea aria-label="First model request" value={prompt} onChange={event => setPrompt(event.target.value)} maxLength={12000} rows={3} /></label></fieldset>}
    {!importedPlan && <p className="mixed-workflow-rate-note">Your SOL value is the maximum you approve per step, not the worker’s price. Each worker owner publishes a rate in lamports per second; automatic routing picks the lowest compatible live rate. The exact rate and time limit appear in the signed quote before you approve each step.</p>}
    {importedPlan ? <details className="workflow-plan-details"><summary>Inspect {importedPlan.steps.length} imported steps</summary>{importedPlan.steps.map(step => <div key={step.id}><h3>{step.id} · {step.source.startsWith('# Aperture inference request v1\n') ? 'Model inference' : 'Python compute'}</h3><p>{step.worker_target?.node_id || 'Automatic routing'} · {step.max_cost_lamports} lamports maximum · {step.max_runtime_seconds}s</p><pre>{JSON.stringify(step, null, 2)}</pre></div>)}</details> : <ol className="mixed-workflow-path" aria-label="Three-step model and compute flow">
      <li><span className="mixed-workflow-step-number" aria-hidden="true">01</span><div className="mixed-workflow-step-copy"><strong>Model · Generate</strong><span>Signed model response</span><code>response.txt</code></div></li>
      <li><span className="mixed-workflow-step-number" aria-hidden="true">02</span><div className="mixed-workflow-step-copy"><strong>Python · Measure</strong><span>Exact response bytes</span><code>analysis.json</code></div></li>
      <li><span className="mixed-workflow-step-number" aria-hidden="true">03</span><div className="mixed-workflow-step-copy"><strong>Model · Interpret</strong><span>Explicit statistics context</span><code>response.txt</code></div></li>
    </ol>}
    <p className="workflow-description">{importedPlan ? importedUsesModelOffer && importedNeedsPythonWorker ? 'Model context files are named explicitly and verified before use. Python treats model output as data; inspect every step before approval.' : importedUsesModelOffer ? 'The imported model requests and per-step limits are listed above. Inspect each before approval; model answers are advisory.' : 'The imported plan lists exact Python sources, input files and dependencies. Inspect each step and its spending limit before preparation.' : 'The plan explicitly lists each result file sent to a model, up to 16,000 UTF-8 bytes per file. Python treats model output as data. The model’s answer is advisory; receipts verify identities and file hashes.'}</p>
    <p className="workflow-plan-state" role="status">{notice}</p>
  </section>;
}
