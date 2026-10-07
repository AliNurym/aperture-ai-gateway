import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import Icon from './components/Icon';
import CommandBlock from './components/CommandBlock';
import WorkflowRun from './WorkflowRun';
import AgentWorkspace from './AgentWorkspace';
import useBrowserWorkflow from './hooks/useBrowserWorkflow';
import { createBatchPlan, parseStepCost } from './utils/workflowPlan';
import { DEFAULT_CSV_MAPPING, inspectCsv, validateCsvMapping } from './utils/csvSchema';
import { MAX_INPUT_BYTES, uploadInput, validateObject } from './utils/jobs';
import { canonicalJson, isPortableFilename } from './utils/protocol';
import { storageContext } from './utils/storage';
import { requestErrorMessage } from './utils/requestError';
import { saveFile } from './utils/downloadFile';
import { revealContent } from './utils/motion';
import { WORKLOADS } from './utils/workloads';
import './Workflows.css';

const formatSol = value => (value / 1e9).toLocaleString('en-US', { maximumFractionDigits: 9 });
const formatBytes = value => value < 1024 ? value + ' B' : value < 1024 * 1024 ? (value / 1024).toFixed(1) + ' KiB' : (value / 1024 / 1024).toFixed(1) + ' MiB';

const BLUEPRINTS = [
  {
    id: 'csv-resilient',
    title: 'Resilient CSV Pipeline',
    subtitle: '3 parallel batches (17,000 rows) + merge aggregator',
    tag: '17k Rows · Auto-Resume',
    icon: 'network',
    advantage: 'Crash-resilient state journal guarantees 0 duplicate charges if a worker drops.',
    batches: [
      {
        name: 'batch-sales-west.csv',
        object_id: 'obj-00000000000000000000000000000001',
        sha256: 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
        size_bytes: 215040
      },
      {
        name: 'batch-sales-east.csv',
        object_id: 'obj-00000000000000000000000000000002',
        sha256: 'b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1',
        size_bytes: 240640
      },
      {
        name: 'batch-sales-central.csv',
        object_id: 'obj-00000000000000000000000000000003',
        sha256: 'c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2',
        size_bytes: 198400
      }
    ],
    mapping: {
      category_column: 'category',
      amount_column: 'amount',
      delimiter: ',',
      decimal_separator: '.',
      thousands_separator: '',
      missing_category: 'uncategorized'
    },
    cost: '0.0001',
    runtime: '45'
  },
  {
    id: 'financial-audit',
    title: 'Financial Spend Cap',
    subtitle: 'Micro-budget audit with strict 0.00005 SOL barrier',
    tag: 'Hard Ceiling · Zero Runaway',
    icon: 'shield',
    advantage: 'Enforces hard spending limits; rogue AI loops cannot drain wallet funds.',
    batches: [
      {
        name: 'treasury-ledger-2026.csv',
        object_id: 'obj-10000000000000000000000000000001',
        sha256: 'd4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3',
        size_bytes: 491520
      },
      {
        name: 'disbursements-q1.csv',
        object_id: 'obj-10000000000000000000000000000002',
        sha256: 'e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4',
        size_bytes: 317440
      }
    ],
    mapping: {
      category_column: 'department',
      amount_column: 'total',
      delimiter: ',',
      decimal_separator: '.',
      thousands_separator: '',
      missing_category: 'reject'
    },
    cost: '0.00005',
    runtime: '30'
  },
  {
    id: 'mcp-delegation',
    title: 'MCP Agent Delegation',
    subtitle: 'Confidential pipeline without prompt context leakage',
    tag: 'Zero Prompt Leaks · Privacy',
    icon: 'code',
    advantage: 'Processes sensitive tables in private sandbox; agent receives only signed artifacts.',
    batches: [
      {
        name: 'confidential-customer-metrics.csv',
        object_id: 'obj-20000000000000000000000000000001',
        sha256: 'f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5',
        size_bytes: 532480
      }
    ],
    mapping: {
      category_column: 'region',
      amount_column: 'revenue',
      delimiter: ',',
      decimal_separator: '.',
      thousands_separator: '',
      missing_category: 'uncategorized'
    },
    cost: '0.0001',
    runtime: '60'
  }
];

export default function Workflows({ apiUrl, gatewayHealth, gatewayOnline, externalBusy = false, onBusyChange, onRecord, releasedObject, onOpenStudio }) {
  const { publicKey, signMessage, wallet, connect, connecting } = useWallet();
  const { connection } = useConnection();
  const { setVisible } = useWalletModal();
  const owner = publicKey?.toBase58() || null;
  const computeProfile = gatewayHealth?.compute_profiles?.find(item => item.id === 'cpu-csv-v2');
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
  const [delegating, setDelegating] = useState(false);
  const [mapping, setMapping] = useState({ ...DEFAULT_CSV_MAPPING });
  const [columns, setColumns] = useState([]);
  const [schemas, setSchemas] = useState(new Map());
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
    connection, externalBusy: externalBusy || uploading || delegating });
  let context = null;
  let contextError = '';
  try { if (gatewayOnline) context = storageContext(apiUrl, gatewayHealth); }
  catch (error) { contextError = error.message; }
  const editsBlocked = uploading || delegating || externalBusy || controller.busy || Boolean(controller.run);
  useLayoutEffect(() => {
    currentScope.current = scope;
    importSequence.current += 1;
    uploadController.current?.abort();
    uploadController.current = null;
    setImporting(false); setUploading(false); setUploadProgress(null); setNotice('');
    setMapping({ ...DEFAULT_CSV_MAPPING }); setColumns([]); setSchemas(new Map());
    setDraft(previous => {
      draftCache.current.set(previous.scope, previous.text);
      while (draftCache.current.size > 16) draftCache.current.delete(draftCache.current.keys().next().value);
      return { scope, text: draftCache.current.get(scope) || '[]' };
    });
    return () => { uploadController.current?.abort(); uploadController.current = null; };
  }, [scope]);
  useEffect(() => { onBusyChange?.(uploading || delegating || controller.busy); }, [uploading, delegating, controller.busy, onBusyChange]);
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
  try {
    for (const input of selectedInputs) {
      const schema = schemas.get(input.object_id);
      if (schema && [mapping.category_column, mapping.amount_column].some(column => !schema.includes(column))) throw new Error('Selected columns are missing from ' + input.name + '. Choose columns present in every batch.');
    }
    plan = createBatchPlan(JSON.parse(references), parseStepCost(cost), Number(runtime), mapping);
  }
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
      const headers = await Promise.all(files.map(file => inspectCsv(file, mapping.delimiter)));
      ensureCurrent();
      if (!inputs.length && headers.length) {
        setColumns(headers[0]);
        const next = { ...mapping };
        if (!headers[0].includes(next.category_column)) next.category_column = headers[0].find(name => /category|department|region|merchant|group/i.test(name)) || headers[0][0];
        if (!headers[0].includes(next.amount_column)) next.amount_column = headers[0].find(name => /amount|revenue|total|price|value/i.test(name) && name !== next.category_column) || headers[0].find(name => name !== next.category_column) || '';
        validateCsvMapping(next);
        if (headers.some(schema => [next.category_column, next.amount_column].some(column => !schema.includes(column)))) throw new Error('Choose batches with the same grouping and amount columns.');
        setMapping(next);
      } else if (headers.some(schema => [mapping.category_column, mapping.amount_column].some(column => !schema.includes(column)))) throw new Error('The new files do not contain the selected grouping and amount columns.');
      for (let index = 0; index < files.length; index++) {
        ensureCurrent();
        setUploadProgress({ current: index + 1, total: files.length, name: files[index].name });
        const reference = await uploadInput({ apiUrl: context.apiUrl, file: files[index], owner, signMessage,
          health: gatewayHealth, signal: attempt.signal, ensureCurrent });
        ensureCurrent();
        if (inputs.some(item => item.object_id === reference.object_id)) throw new Error('This input already appears in the plan.');
        setSchemas(previous => new Map(previous).set(reference.object_id, headers[index]));
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
  const applyBlueprint = bp => {
    if (editsBlocked) return;
    setReferences(JSON.stringify(bp.batches, null, 2));
    setMapping({ ...bp.mapping });
    setCost(bp.cost);
    setRuntime(bp.runtime);
    setColumns([bp.mapping.category_column, bp.mapping.amount_column]);
    const nextSchemas = new Map();
    bp.batches.forEach(b => {
      nextSchemas.set(b.object_id, [bp.mapping.category_column, bp.mapping.amount_column]);
    });
    setSchemas(nextSchemas);
    setNotice('Loaded blueprint: ' + bp.title + '. Plan validated with ' + bp.batches.length + ' batches.');
    const heading = document.getElementById('workflow-builder-heading');
    heading?.closest('details')?.setAttribute('open', '');
    revealContent(heading, { focus: true, block: 'start' });
  };
  return <div className={'workflows' + (controller.run ? ' has-run' : '')}>
    <section className="workflow-hero">
      <div className="workflow-hero-copy">
        <span className="console-eyebrow"><Icon name="network" size={16} /> AGENT WORKFLOWS</span>
        <h2>Delegate data pipelines<br /><span>without runaway risk.</span></h2>
        <p>Why Aperture instead of a plain script? Deliver large-scale pipelines to your AI agent with deterministic 512 MiB sandboxes, immutable Solana budget caps, and crash-resilient journal recovery.</p>
        <div className="workflow-value-chips">
          <span className="workflow-value-chip"><Icon name="shield" size={13} /> Hard Spend Ceiling</span>
          <span className="workflow-value-chip"><Icon name="refresh" size={13} /> Crash-Resilient Journal</span>
          <span className="workflow-value-chip"><Icon name="chip" size={13} /> 512 MiB Sandboxed CPU</span>
          <span className="workflow-value-chip"><Icon name="code" size={13} /> Zero Prompt Leakage</span>
        </div>
        <div className="workflow-hero-actions">
          <button className="console-button primary" disabled={editsBlocked} onClick={() => {
            const heading = document.getElementById('workflow-builder-heading');
            heading?.closest('details')?.setAttribute('open', '');
            revealContent(heading, { focus: true, block: 'start' });
          }}>Build a workflow<Icon name="arrow" size={18} /></button>
          <button className="console-text-button" onClick={() => applyBlueprint(BLUEPRINTS[0])}><Icon name="spark" size={16} />Quick 17k Demo</button>
          <button className="console-text-button" onClick={downloadSample}><Icon name="download" size={17} />Sample CSV</button>
        </div>
      </div>
      <div className="workflow-graph" role="img" aria-label="Pipeline DAG topology">
        <div className="workflow-graph-input">
          <Icon name="upload" size={18} />
          <span>
            {selectedInputs.length ? `${selectedInputs.length} Batches (${formatBytes(inputBytes)})` : 'Dataset'}
            <small>Immutable cryptographic inputs</small>
          </span>
        </div>
        <div className="workflow-branches">
          {(selectedInputs.length ? selectedInputs.slice(0, 3) : [{ name: 'batch-01' }, { name: 'batch-02' }, { name: 'batch-03' }]).map((b, i) => (
            <div key={i} className="workflow-branch-node">
              <span>0{i + 1}</span>
              <Icon name="chip" size={20} />
              <strong>{b.name ? b.name.replace('.csv', '').slice(0, 12) : 'Batch compute'}</strong>
              <small className="workflow-branch-tag">512 MiB</small>
            </div>
          ))}
          {selectedInputs.length > 3 && (
            <div className="workflow-branch-node more">
              <span>+{selectedInputs.length - 3}</span>
              <small>more</small>
            </div>
          )}
        </div>
        <div className="workflow-graph-merge">
          <Icon name="network" size={22} />
          <span>
            Combine & Deduplicate
            <small>Up to 16 inputs per join · Journal tracked</small>
          </span>
        </div>
        <div className="workflow-graph-output">
          <Icon name="check" size={20} />
          <span>
            report.json
            <small>categories.csv · quality.csv · Signed Receipt</small>
          </span>
        </div>
      </div>
    </section>
    <section className="workflow-blueprints console-panel">
      <div className="console-section-heading">
        <div>
          <span className="console-eyebrow">READY-TO-RUN BLUEPRINTS</span>
          <h2>Load a pre-configured pipeline in 1 click</h2>
          <p>Explore production-grade agent workflows with deterministic cost caps, journal recovery, and zero prompt leakage.</p>
        </div>
      </div>
      <div className="workflow-blueprints-grid">
        {BLUEPRINTS.map(bp => (
          <div key={bp.id} className="workflow-blueprint-card">
            <div className="blueprint-header">
              <span className="blueprint-icon"><Icon name={bp.icon} size={20} /></span>
              <span className="blueprint-badge">{bp.tag}</span>
            </div>
            <h3>{bp.title}</h3>
            <p className="blueprint-sub">{bp.subtitle}</p>
            <p className="blueprint-adv">{bp.advantage}</p>
            <div className="blueprint-specs">
              <span><strong>{bp.batches.length}</strong> batches</span>
              <span><strong>{bp.cost}</strong> SOL/step</span>
              <span><strong>{bp.runtime}s</strong> max/step</span>
            </div>
            <button
              className="console-button primary blueprint-btn"
              disabled={editsBlocked}
              onClick={() => applyBlueprint(bp)}
            >
              <Icon name="play" size={14} />
              Load blueprint
            </button>
          </div>
        ))}
      </div>
    </section>
    <div className="workflow-principles">{[
      ['shield', 'One total budget', 'Every step fits inside the approved cap.'],
      ['refresh', 'Continue the same work', 'The journal retains admissions and results.'],
      ['download', 'Files your agent can reuse', 'Signed outputs become downstream inputs.'],
    ].map(([icon, title, body]) => <div key={title}><Icon name={icon} size={21} /><div><h3>{title}</h3><p>{body}</p></div></div>)}</div>
    {notice && <div className="studio-notice" role="status"><Icon name="book" size={18} /><p>{notice}</p></div>}
    <details className="workflow-configuration" open={!controller.run}><summary>{controller.run ? 'Saved plan · ' + controller.run.total_steps + ' steps · ' + formatSol(controller.run.plan.max_cost_lamports) + ' SOL maximum' : 'Workflow setup'}</summary><section className="workflow-builder console-panel">
      <div className="console-section-heading"><div><span className="console-eyebrow">CSV BATCH → REPORT</span><h2 id="workflow-builder-heading" tabIndex={-1}>Prepare your workflow</h2></div><span className="console-tag neutral">CSV processing</span></div>
      <p className="workflow-description">Use your own CSV exports. Choose a grouping column and numeric amount; get exact totals, averages, minimums and maximums, plus a report explaining excluded records.</p>
      <div className="workflow-builder-grid">
        <div>
          <div className="workflow-upload" aria-busy={uploading}>
            <span className="workflow-upload-icon" data-busy={uploading}><Icon name="upload" size={28} /></span>
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
          <label htmlFor="workflow-delimiter">CSV delimiter<select id="workflow-delimiter" disabled={editsBlocked || selectedInputs.length > 0} value={mapping.delimiter} onChange={event => setMapping({ ...mapping, delimiter: event.target.value })}>{[[',', 'Comma'], [';', 'Semicolon'], ['\t', 'Tab'], ['|', 'Pipe']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label htmlFor="workflow-group-column">Group by column<input id="workflow-group-column" list="workflow-columns" disabled={editsBlocked} value={mapping.category_column} onChange={event => setMapping({ ...mapping, category_column: event.target.value })} /></label>
          <label htmlFor="workflow-amount-column">Amount column<input id="workflow-amount-column" list="workflow-columns" disabled={editsBlocked} value={mapping.amount_column} onChange={event => setMapping({ ...mapping, amount_column: event.target.value })} /></label>
          <datalist id="workflow-columns">{columns.map(column => <option key={column} value={column} />)}</datalist>
          <label htmlFor="workflow-decimal">Decimal separator<select id="workflow-decimal" disabled={editsBlocked} value={mapping.decimal_separator} onChange={event => setMapping({ ...mapping, decimal_separator: event.target.value })}><option value=".">Dot · 1234.56</option><option value=",">Comma · 1234,56</option></select></label>
          <label htmlFor="workflow-thousands">Thousands separator<select id="workflow-thousands" disabled={editsBlocked} value={mapping.thousands_separator} onChange={event => setMapping({ ...mapping, thousands_separator: event.target.value })}>{[['', 'None'], [',', 'Comma'], ['.', 'Dot'], [' ', 'Space']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label htmlFor="workflow-missing">Missing group<select id="workflow-missing" disabled={editsBlocked} value={mapping.missing_category} onChange={event => setMapping({ ...mapping, missing_category: event.target.value })}><option value="uncategorized">Include as uncategorized</option><option value="reject">Exclude and report</option></select></label>
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
          <div className="workflow-step-content"><strong>{step.id === 'report' ? 'Final report' : step.id.startsWith('batch_') ? step.inputs[0].name : 'Combine batch results'}</strong><p>{step.inputs.map(item => item.from_step || item.name).join(' + ')} <span aria-hidden="true">→</span> {step.parameters.output_name}{step.id === 'report' ? ' + categories.csv + quality.csv' : ''}</p><details><summary>Inspect source and parameters</summary><pre>{step.source}</pre><pre>{JSON.stringify(step.parameters, null, 2)}</pre></details></div>
          <span className="workflow-step-limit">{formatSol(step.max_cost_lamports)} SOL<small>{step.max_runtime_seconds}s maximum</small></span>
        </li>)}</ol></details>
        <p className="workflow-description">These are planned steps. No computation or payment starts when you import or export.</p>
      </div>}
    </section></details>
    <AgentWorkspace context={context} owner={owner} signMessage={signMessage} plan={plan}
      disabled={uploading || externalBusy || controller.busy || Boolean(controller.run)} onBusyChange={setDelegating} />
    {computeProfile && <section className="console-panel workflow-compute-profile"><span className="console-eyebrow">CSV COMPUTE</span><h2>Size the job before you approve it.</h2><p>Start with about 5,000 rows per batch and at most 10,000 groups across the report. More columns and longer values increase work; the quote's affordable runtime can be shorter than your requested limit.</p><p>{formatSol(computeProfile.pricing.rate_lamports_sec)} SOL per execution second · operator tariff · {context?.network === 'off_chain' ? 'no payment in this workspace' : 'settled within your approved cap'}. Each step supports 64 MiB of inputs and at most 180 seconds. Configured Docker workers use 1 CPU and 512 MiB; the local preview runs trusted Python on this host.</p><details><summary>Check your worker's batch size</summary><p>The benchmark runs the same CSV sources and records time and peak process memory. Its result applies to that host and dataset; it does not guarantee Docker or remote-provider performance.</p><CommandBlock label="Measure a CSV profile" command="python scripts/benchmark_csv_profile.py --rows 50000 --groups 4 --output .aperture-runs/cpu-profile.json" /></details></section>}
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
