import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import Icon from './components/Icon';
import CommandBlock from './components/CommandBlock';
import WorkflowRun from './WorkflowRun';
import useBrowserWorkflow from './hooks/useBrowserWorkflow';
import { createBatchPlan, parseStepCost } from './utils/workflowPlan';
import { MAX_INPUT_BYTES, uploadInput, validateObject } from './utils/jobs';
import { canonicalJson, isPortableFilename } from './utils/protocol';
import { storageContext } from './utils/storage';
import { requestErrorMessage } from './utils/requestError';
import { saveFile } from './utils/downloadFile';
import { WORKLOADS } from './utils/workloads';
import './Workflows.css';

const formatSol = value => (value / 1e9).toLocaleString('en-US', { maximumFractionDigits: 9 });
const formatBytes = value => value < 1024 ? value + ' B' : value < 1024 * 1024 ? (value / 1024).toFixed(1) + ' KiB' : (value / 1024 / 1024).toFixed(1) + ' MiB';

export default function Workflows({ apiUrl, gatewayHealth, gatewayOnline, externalBusy = false, onBusyChange, onRecord, releasedObject, onOpenStudio }) {
  const { publicKey, signMessage, wallet, connect, connecting } = useWallet();
  const { connection } = useConnection();
  const { setVisible } = useWalletModal();
  const owner = publicKey?.toBase58() || null;
  const scope = canonicalJson({ owner, api_url: apiUrl, gateway_pubkey: gatewayHealth?.gateway_pubkey ?? null,
    program_id: gatewayHealth?.program_id ?? null,
    network: gatewayHealth?.demo_mode === true ? 'off_chain' : gatewayHealth?.demo_mode === false ? 'devnet' : null });
  const [draft, setDraft] = useState({ scope, text: '[]' });
  const references = draft.scope === scope ? draft.text : '[]';
  const setReferences = text => setDraft({ scope, text });
  const [cost, setCost] = useState('0.0001');
  const [runtime, setRuntime] = useState('60');
  const [notice, setNotice] = useState('');
  const [importing, setImporting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(null);
  const importSequence = useRef(0);
  const fileInput = useRef(null);
  const csvInput = useRef(null);
  const uploadController = useRef(null);
  const currentScope = useRef(scope);
  const draftCache = useRef(new Map());
  const handledRelease = useRef(null);
  const recordedTasks = useRef(new Set());
  const controller = useBrowserWorkflow({ apiUrl, gatewayHealth, gatewayOnline, publicKey, signMessage,
    connection, externalBusy: externalBusy || uploading });
  let context = null;
  let contextError = '';
  try { if (gatewayOnline) context = storageContext(apiUrl, gatewayHealth); }
  catch (error) { contextError = error.message; }
  const editsBlocked = uploading || externalBusy || controller.busy || Boolean(controller.run);
  useLayoutEffect(() => {
    currentScope.current = scope;
    importSequence.current += 1;
    uploadController.current?.abort();
    uploadController.current = null;
    setImporting(false); setUploading(false); setUploadProgress(null); setNotice('');
    setDraft(previous => {
      draftCache.current.set(previous.scope, previous.text);
      while (draftCache.current.size > 16) draftCache.current.delete(draftCache.current.keys().next().value);
      return { scope, text: draftCache.current.get(scope) || '[]' };
    });
    return () => { uploadController.current?.abort(); uploadController.current = null; };
  }, [scope]);
  useEffect(() => { onBusyChange?.(uploading || controller.busy); }, [uploading, controller.busy, onBusyChange]);
  useEffect(() => {
    for (const step of controller.run?.steps || []) {
      if (!['completed', 'failed'].includes(step.state) || !step.receipt || !step.task_id || recordedTasks.current.has(step.task_id)) continue;
      recordedTasks.current.add(step.task_id);
      const outcome = step.receipt.execution_status;
      onRecord?.({ id: step.task_id, name: 'Workflow · ' + step.id, mode: 'gateway',
        status: outcome === 'completed' ? 'completed' : outcome === 'cancelled' ? 'cancelled' : 'failed', timestamp: Date.now() });
    }
  }, [controller.run, onRecord]);
  useLayoutEffect(() => {
    if (!releasedObject || handledRelease.current === releasedObject) return;
    handledRelease.current = releasedObject;
    const releasedScope = canonicalJson({ owner: releasedObject.owner, api_url: releasedObject.api_url,
      gateway_pubkey: releasedObject.gateway_pubkey, program_id: releasedObject.program_id, network: releasedObject.network });
    const remove = text => {
      try {
        const items = JSON.parse(text);
        if (!Array.isArray(items)) return text;
        const remaining = items.filter(item => item.object_id !== releasedObject.object_id);
        return remaining.length === items.length ? text : JSON.stringify(remaining, null, 2);
      } catch { return text; }
    };
    if (draftCache.current.has(releasedScope)) draftCache.current.set(releasedScope, remove(draftCache.current.get(releasedScope)));
    if (releasedScope === scope) {
      importSequence.current += 1;
      uploadController.current?.abort(); uploadController.current = null;
      setImporting(false); setUploading(false); setUploadProgress(null);
    }
    setDraft(previous => previous.scope === releasedScope ? { ...previous, text: remove(previous.text) } : previous);
  }, [releasedObject, scope]);
  let plan = null;
  let problem = '';
  let selectedInputs = [];
  try {
    const items = JSON.parse(references);
    if (Array.isArray(items) && items.length <= 200) {
      items.forEach(item => validateObject(item));
      if (new Set(items.map(item => item.object_id)).size === items.length) selectedInputs = items;
    }
  } catch { /* The reference editor retains invalid text for correction. */ }
  try { plan = createBatchPlan(JSON.parse(references), parseStepCost(cost), Number(runtime)); }
  catch (error) { problem = error.message; }
  const mergeSteps = plan?.steps.filter(step => !step.id.startsWith('batch_')) || [];
  const inputBytes = selectedInputs.reduce((sum, item) => sum + item.size_bytes, 0);
  const executionCommand = 'python examples/run_workflow.py aperture-workflow.json --workflow-budget-lamports ' + (plan?.max_cost_lamports || 2000000) + ' --output .aperture-runs/results';
  const exportPlan = () => {
    if (!plan) return;
    saveFile('aperture-workflow.json', JSON.stringify(plan, null, 2), 'application/json');
    setNotice('Plan exported. Run it with the same agent identity that uploaded the files. The command below retains progress.');
  };
  const importReferences = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || editsBlocked) return;
    const sequence = ++importSequence.current;
    if (file.size > 256000) { setNotice('Choose an input reference JSON file up to 256 KB.'); return; }
    setImporting(true);
    try {
      const value = JSON.parse(await file.text());
      const items = Array.isArray(value) ? value : value.inputs;
      if (!Array.isArray(items)) throw new Error('Choose an array of immutable references or a saved inputs plan.');
      createBatchPlan(items, parseStepCost(cost), Number(runtime));
      if (sequence !== importSequence.current) return;
      setReferences(JSON.stringify(items, null, 2));
      setNotice('Input references imported. Review the steps and total cap before exporting.');
    } catch (error) { if (sequence === importSequence.current) setNotice(error.message); }
    finally { if (sequence === importSequence.current) setImporting(false); }
  };
  const updateReferences = event => {
    if (editsBlocked) return;
    importSequence.current += 1;
    setImporting(false);
    setReferences(event.target.value);
    setNotice('');
  };
  const connectWallet = async () => {
    if (!wallet || controller.run && owner !== controller.run.owner) { setVisible(true); return; }
    try { await connect(); }
    catch (error) { setNotice('Wallet connection failed: ' + requestErrorMessage(error)); }
  };
  const uploadBatchFiles = async files => {
    if (!files.length || editsBlocked || uploadController.current) return;
    if (!owner || !signMessage || !context) { setNotice(contextError || 'Connect a wallet that supports message signing and a configured gateway.'); return; }
    let inputs;
    try {
      inputs = JSON.parse(references);
      if (!Array.isArray(inputs)) throw new Error('Replace invalid input references before adding files.');
      if (inputs.length) createBatchPlan(inputs, 100000, 60);
      if (inputs.length + files.length > 200) throw new Error('Use up to 200 CSV batches in one plan.');
      if (files.some(file => !isPortableFilename(file.name) || !file.name.toLowerCase().endsWith('.csv') || file.size < 1 || file.size > MAX_INPUT_BYTES)) throw new Error('Choose non-empty CSV files with portable names, up to 64 MiB each.');
      if (inputs.reduce((sum, item) => sum + item.size_bytes, 0) + files.reduce((sum, file) => sum + file.size, 0) > 256 * 1024 * 1024) throw new Error('The selected inputs exceed 256 MiB. Split this work into separate plans.');
    } catch (error) { setNotice(error.message); return; }
    const attempt = new AbortController();
    const sequence = ++importSequence.current;
    uploadController.current = attempt;
    setImporting(false); setUploading(true); setNotice('');
    const ensureCurrent = () => {
      if (attempt.signal.aborted || currentScope.current !== scope || importSequence.current !== sequence) throw new DOMException('The upload context changed.', 'AbortError');
    };
    try {
      for (let index = 0; index < files.length; index++) {
        ensureCurrent();
        setUploadProgress({ current: index + 1, total: files.length, name: files[index].name });
        const reference = await uploadInput({ apiUrl: context.apiUrl, file: files[index], owner, signMessage,
          health: gatewayHealth, signal: attempt.signal, ensureCurrent });
        ensureCurrent();
        if (inputs.some(item => item.object_id === reference.object_id)) throw new Error('This input already appears in the plan.');
        inputs = [...inputs, reference];
        setReferences(JSON.stringify(inputs, null, 2));
      }
      setNotice(files.length + ' CSV ' + (files.length === 1 ? 'batch uploaded' : 'batches uploaded') + '. Review the plan and limits below.');
    } catch (error) {
      if (!attempt.signal.aborted && currentScope.current === scope) setNotice('Upload stopped: ' + requestErrorMessage(error) + ' Completed uploads remain in the plan; retained files are available in Files & results.');
    } finally {
      if (uploadController.current === attempt) { uploadController.current = null; setUploading(false); setUploadProgress(null); }
    }
  };
  const uploadBatches = event => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    return uploadBatchFiles(files);
  };
  const useExampleData = () => uploadBatchFiles([
    new File(['category,amount\ncompute,12.5\nstorage,8.25\ncompute,7.5\nnetwork,3.75\nstorage,invalid\n'], 'example-a.csv', { type: 'text/csv' }),
    new File(['category,amount\nstorage,4\nsupport,6.5\nnetwork,1.25\ncompute,10\nsupport,invalid\n'], 'example-b.csv', { type: 'text/csv' }),
  ]);
  const removeReference = id => {
    if (editsBlocked) return;
    try { setReferences(JSON.stringify(JSON.parse(references).filter(item => item.object_id !== id), null, 2)); setNotice('Input removed from this plan. Its retained file remains in Files & results.'); }
    catch { setNotice('Repair the input references before removing a batch.'); }
  };
  const downloadSample = () => saveFile('records.csv', 'category,amount\ncompute,12.5\nstorage,8.25\ncompute,7.5\nnetwork,3.75\nstorage,4\nsupport,6.5\n', 'text/csv');
  return <div className={'workflows' + (controller.run ? ' has-run' : '')}>
    <section className="workflow-hero">
      <div className="workflow-hero-copy">
        <span className="console-eyebrow"><Icon name="network" size={16} /> AGENT WORKFLOWS</span>
        <h2>Give your agent<br /><span>room to compute.</span></h2>
        <p>Turn a dataset into a chain of useful results. Separate the work into batches, combine their outputs, and continue from the last saved step.</p>
        <div className="workflow-hero-actions">
          <button className="console-button primary" disabled={editsBlocked} onClick={() => document.getElementById('workflow-builder-heading')?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' })}>Build a workflow<Icon name="arrow" size={18} /></button>
          <button className="console-text-button" onClick={downloadSample}><Icon name="download" size={17} />Sample CSV</button>
        </div>
      </div>
      <div className="workflow-graph" role="img" aria-label="CSV batches feed a merge step that produces JSON and CSV; an example of the pipeline structure">
        <div className="workflow-graph-input"><Icon name="upload" size={18} /><span>Dataset<small>Immutable inputs</small></span></div>
        <div className="workflow-branches">{['01', '02', '03'].map(id => <div key={id}><span>{id}</span><Icon name="chip" size={20} /><strong>Batch compute</strong></div>)}</div>
        <div className="workflow-graph-merge"><Icon name="network" size={22} /><span>Combine results<small>Up to 16 inputs per join</small></span></div>
        <div className="workflow-graph-output"><Icon name="check" size={20} /><span>report.json<small>categories.csv</small></span></div>
      </div>
    </section>
    <div className="workflow-principles">{[
      ['shield', 'One total budget', 'Every step fits inside the approved cap.'],
      ['refresh', 'Continue the same work', 'The journal retains admissions and results.'],
      ['download', 'Files your agent can reuse', 'Signed outputs become downstream inputs.'],
    ].map(([icon, title, body]) => <div key={title}><Icon name={icon} size={21} /><div><h3>{title}</h3><p>{body}</p></div></div>)}</div>
    {notice && <div className="studio-notice" role="status"><Icon name="book" size={18} /><p>{notice}</p></div>}
    <details className="workflow-configuration" open={!controller.run}><summary>{controller.run ? 'Saved plan · ' + controller.run.total_steps + ' steps · ' + formatSol(controller.run.plan.max_cost_lamports) + ' SOL maximum' : 'Workflow setup'}</summary><section className="workflow-builder console-panel">
      <div className="console-section-heading"><div><span className="console-eyebrow">CSV BATCH → REPORT</span><h2 id="workflow-builder-heading">Prepare your workflow</h2></div><span className="console-tag neutral">CSV processing</span></div>
      <p className="workflow-description">Use CSV files with category and amount columns. Each file becomes one batch; their summaries combine into a JSON report and category totals in CSV.</p>
      <div className="workflow-builder-grid">
        <div>
          <div className="workflow-upload" aria-busy={uploading}>
            <span className="workflow-upload-icon"><Icon name="upload" size={28} /></span>
            <h3>{uploadProgress ? 'Uploading batch ' + uploadProgress.current + ' of ' + uploadProgress.total : 'Start with your data'}</h3>
            <p>{uploadProgress ? uploadProgress.name : 'Add CSV batches up to 64 MiB each. Your wallet signs each upload; file contents stay on the configured gateway.'}</p>
            <button className={'console-button ' + (selectedInputs.length ? 'secondary' : 'primary')} disabled={editsBlocked || connecting || Boolean(owner && (!signMessage || !context))} onClick={() => owner ? csvInput.current.click() : connectWallet()}><Icon name={owner ? 'upload' : 'wallet'} size={17} />{uploading ? 'Uploading…' : owner ? 'Choose CSV batches' : 'Connect wallet to add CSV'}</button>
            {!selectedInputs.length && owner && <button className="console-text-button workflow-example-button" disabled={editsBlocked || !signMessage || !context} onClick={useExampleData}><Icon name="spark" size={16} />Use example data</button>}
            {!selectedInputs.length && owner && <small>Two small CSV batches. Real uploads, quotes and worker execution.</small>}
            <input ref={csvInput} type="file" accept=".csv,text/csv" multiple hidden onChange={uploadBatches} />
            {contextError && <small role="alert">{contextError}</small>}
          </div>
          {selectedInputs.length > 0 && <ul className="workflow-input-list" aria-label="Selected CSV batches">{selectedInputs.map(item => <li key={item.object_id}><Icon name="book" size={17} /><span><strong>{item.name}</strong><small>{formatBytes(item.size_bytes)} · hash-bound input</small></span><button className="console-text-button" disabled={editsBlocked} aria-label={'Remove ' + item.name + ' from plan'} onClick={() => removeReference(item.object_id)}>Remove</button></li>)}</ul>}
          <details className="workflow-reference-editor"><summary>Use existing input references</summary>
            <div className="workflow-input-heading"><label htmlFor="workflow-inputs">Uploaded batch references</label><button className="console-text-button" disabled={importing || editsBlocked} onClick={() => fileInput.current.click()}><Icon name="upload" size={16} />{importing ? 'Importing…' : 'Import JSON'}</button></div>
            <textarea id="workflow-inputs" value={references} disabled={editsBlocked} onChange={updateReferences} spellCheck={false} aria-describedby="workflow-reference-help" />
            <input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={importReferences} />
            <small id="workflow-reference-help">Import .inputs.json or object_id, name, sha256 and size_bytes references. Browser execution requires files owned by the connected wallet. SDK execution uses the identity that uploaded them.</small>
          </details>
        </div>
        <aside>
          <label htmlFor="workflow-step-cap">Maximum cost per step · SOL<input id="workflow-step-cap" disabled={editsBlocked} inputMode="decimal" value={cost} onChange={event => setCost(event.target.value)} /></label>
          <label htmlFor="workflow-step-runtime">Runtime per step · seconds<input id="workflow-step-runtime" disabled={editsBlocked} type="number" min="1" max="180" step="1" value={runtime} onChange={event => setRuntime(event.target.value)} /></label>
          <dl><div><dt>Compute batches</dt><dd>{selectedInputs.length || '—'}</dd></div><div><dt>Combine steps</dt><dd>{plan ? mergeSteps.length : '—'}</dd></div><div><dt>Input data</dt><dd>{selectedInputs.length ? formatBytes(inputBytes) : '—'}</dd></div><div><dt>Total maximum</dt><dd>{plan ? formatSol(plan.max_cost_lamports) + ' SOL' : '—'}</dd></div></dl>
          <p className="workflow-plan-state" role="status">{plan ? 'Plan validated. Review the dependencies and total cap below.' : references.trim() === '[]' ? 'Add a CSV batch to prepare your first chain.' : problem}</p>
          <button className="console-button secondary" disabled={!plan || importing} onClick={exportPlan}><Icon name="download" size={17} />Export agent plan</button>
        </aside>
      </div>
      {plan && <div className="workflow-plan-preview">
        <div className="workflow-plan-heading"><div><span className="console-eyebrow">YOUR CHAIN</span><h3>{plan.steps.length} steps, one report.</h3></div><span className="console-tag neutral">{controller.run ? 'Plan retained' : 'Ready to prepare'}</span></div>
        <details className="workflow-plan-details"><summary>Inspect planned steps, source and parameters</summary><ol className="workflow-step-list">{plan.steps.map((step, index) => <li key={step.id}>
          <span className="workflow-step-number">{String(index + 1).padStart(2, '0')}</span>
          <div className="workflow-step-content"><strong>{step.id === 'report' ? 'Final report' : step.id.startsWith('batch_') ? step.inputs[0].name : 'Combine batch results'}</strong><p>{step.inputs.map(item => item.from_step || item.name).join(' + ')} <span aria-hidden="true">→</span> {step.parameters.output_name}{step.id === 'report' ? ' + categories.csv' : ''}</p><details><summary>Inspect source and parameters</summary><pre>{step.source}</pre><pre>{JSON.stringify(step.parameters, null, 2)}</pre></details></div>
          <span className="workflow-step-limit">{formatSol(step.max_cost_lamports)} SOL<small>{step.max_runtime_seconds}s maximum</small></span>
        </li>)}</ol></details>
        <p className="workflow-description">These are planned steps. No computation or payment starts when you import or export.</p>
      </div>}
    </section></details>
    <WorkflowRun controller={controller} plan={plan} connected={Boolean(owner && (!controller.run || owner === controller.run.owner))} onConnect={connectWallet}
      gatewayOnline={gatewayOnline} gatewayReady={gatewayOnline && gatewayHealth?.status === 'ready'} externalBusy={externalBusy || uploading} />
    <section className="workflow-how console-panel">
      <div><span className="console-eyebrow">FROM DATA TO RESULTS</span><h2>A useful pipeline in one command.</h2><p>Start from a CSV. The SDK splits it into batches, stages files, runs summaries and merges a report. Rerun with the same journal to recover progress.</p></div>
      <CommandBlock label="Batch processing" command="python examples/batch_data_workflow.py records.csv --batch-rows 5000 --workflow-budget-lamports 2000000" />
      <button className="console-text-button" disabled={editsBlocked} onClick={() => onOpenStudio(WORKLOADS.find(item => item.id === 'dataset'))}>Open a single data job in Studio<Icon name="arrow" size={16} /></button>
      <details open={Boolean(plan)}><summary>Run your exported plan</summary><p>Save aperture-workflow.json in the project directory. Configure the same agent identity that uploaded its inputs, then run this command. The journal records each accepted task and verified result; final files are saved under the output directory.</p><CommandBlock label="Execute an exported plan" command={executionCommand} /><p>For an MCP agent, pass the exported JSON to prepare_compute_workflow, review its workflow ID and budget, then call start_compute_workflow. Use get_compute_workflow for progress and read_compute_artifact for verified files.</p></details>
      <details><summary>Agent setup and execution limits</summary><p>Configure the gateway, a dedicated agent key and an owner-issued passport. Set the workflow directory and total spending ceiling in your MCP host. Steps execute serially on one payment channel. Each job supports up to 64 MiB of input and 180 seconds; outputs are bounded to 16 MiB total. Docker and Devnet execution require the corresponding deployment configuration.</p><CommandBlock label="MCP workflow settings · PowerShell" command={'$env:APERTURE_MCP_WORKFLOW_DIRECTORY = "C:\\aperture-agent\\workflows"\n$env:APERTURE_MCP_MAX_WORKFLOW_COST_LAMPORTS = "2000000"'} /></details>
    </section>
  </div>;
}
