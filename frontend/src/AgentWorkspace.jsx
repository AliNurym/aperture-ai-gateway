import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useConnection } from '@solana/wallet-adapter-react';
import Icon from './components/Icon';
import ResultFiles from './components/ResultFiles';
import CommandBlock from './components/CommandBlock';
import { canonicalJson, verifyAgentPassport } from './utils/protocol';
import { assignInputs, assignedRequestId, submitAssignedPlan, stopAssignedWorkflow, archiveAssignedWorkflow,
  openAgentView, readAgentArtifact, readAgentView } from './utils/ownerWorkspace';
import { saveFile } from './utils/downloadFile';
import { requestErrorMessage } from './utils/requestError';

export default function AgentWorkspace({ context, owner, signMessage, plan, disabled, onBusyChange }) {
  const { connection } = useConnection();
  const [agent, setAgent] = useState('');
  const [passports, setPassports] = useState([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [view, setView] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [assigned, setAssigned] = useState(null);
  const revision = useRef(0), currentScope = useRef('');
  const scope = canonicalJson({ owner, agent, context });
  const planKey = canonicalJson(plan);
  const currentAssigned = assigned?.scope === scope && assigned.planKey === planKey ? assigned.plan : null;
  const canOperate = Boolean(context && owner && signMessage && !disabled && !busy);

  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);
  useEffect(() => {
    const nextRevision = revision.current + 1;
    revision.current = nextRevision; currentScope.current = scope;
    setView(null); setSnapshot(null); setNotice(''); setBusy(false);
    return () => { revision.current = nextRevision + 1; };
  }, [scope]);
  useEffect(() => { setPassports([]); setAgent(''); setAssigned(null); }, [owner]);
  useEffect(() => {
    if (!view || !context) return undefined;
    const controller = new AbortController();
    let timer;
    const poll = async () => {
      try {
        if (view.expires_at * 1000 <= Date.now()) throw new Error('Observation expired. Open the agent workspace again to continue.');
        const next = await readAgentView(context, view, controller.signal);
        if (controller.signal.aborted) return;
        setSnapshot({ scope, data: next });
        timer = setTimeout(poll, 3000);
      } catch (error) {
        if (!controller.signal.aborted) setNotice('Observation stopped: ' + requestErrorMessage(error));
      }
    };
    poll();
    return () => { clearTimeout(timer); controller.abort(); };
  // Context identity is included in scope; polling keeps the opened identity.
  }, [view, scope]); // eslint-disable-line react-hooks/exhaustive-deps

  const operate = async work => {
    if (!canOperate) return;
    const generation = revision.current;
    const ensureCurrent = () => {
      if (revision.current !== generation || currentScope.current !== scope) throw new DOMException('Owner workspace changed.', 'AbortError');
    };
    setBusy(true); setNotice('');
    try { await work({ context, owner, agent, signMessage, ensureCurrent }); }
    catch (error) { if (revision.current === generation) setNotice(requestErrorMessage(error)); }
    finally { if (revision.current === generation) setBusy(false); }
  };
  const loadAgents = () => operate(async options => {
    const issued_at = Math.floor(Date.now() / 1000), nonce = crypto.randomUUID();
    const message = 'Aperture agent allowance read v1\naudience:aperture-gateway\n' + canonicalJson({ owner, issued_at, nonce });
    const signature = await signMessage(new TextEncoder().encode(message));
    options.ensureCurrent();
    const { data } = await axios.post(context.apiUrl + '/agents/usage', { owner, issued_at, nonce, signature: Array.from(signature) }, { timeout: 15000 });
    if (!Array.isArray(data)) throw new Error('The passport list is unavailable.');
    for (const passport of data) {
      const result = await verifyAgentPassport(passport, owner, false);
      if (!result.verified) throw new Error(result.reason);
      if (passport.program_id !== context.program_id || passport.network !== context.network) throw new Error('The passport belongs to a different deployment.');
    }
    options.ensureCurrent(); setPassports(data.filter(item => !item.revoked && item.expires_at > Date.now() / 1000));
    setNotice(data.length ? 'Select a delegated agent or paste its public key.' : 'Issue a passport in Agents before handing off work.');
  });
  const handoff = () => operate(async options => {
    const inputs = plan.steps.flatMap(step => step.inputs.filter(item => item.object_id));
    const unique = [...new Map(inputs.map(item => [item.object_id, item])).values()];
    const references = await assignInputs(options, unique);
    const byId = new Map(unique.map((item, index) => [item.object_id, references[index]]));
    const next = { ...plan, steps: plan.steps.map(step => ({ ...step,
      inputs: step.inputs.map(item => item.object_id ? byId.get(item.object_id) : item) })) };
    const requestId = await assignedRequestId(options, next);
    options.ensureCurrent(); setAssigned({ scope, planKey, plan: next, requestId });
    setNotice('Files assigned. This agent can use the references through MCP or the SDK without receiving dataset contents in chat.');
  });
  const observe = () => operate(async options => {
    const next = await openAgentView(options);
    options.ensureCurrent(); setView(next); setNotice('Observation opened for 15 minutes. Progress refreshes without further wallet prompts.');
  });
  const submit = () => operate(async options => {
    const flow = await submitAssignedPlan(options, currentAssigned, assigned.requestId);
    options.ensureCurrent();
    setNotice(flow.status === 'queued' ? 'Plan and total budget approved. Waiting for this agent’s receiver or MCP host; no computation starts until it accepts the work.' : 'This exact request is already ' + flow.status + '. Its retained progress will be reused.');
    if (!view) {
      const next = await openAgentView(options);
      options.ensureCurrent(); setView(next);
    }
  });
  const stop = flow => operate(async options => {
    await stopAssignedWorkflow(options, flow.workflow_id);
    options.ensureCurrent(); setNotice('Stop requested. Further steps are blocked; active tasks settle before the final status appears.');
  });
  const archive = flow => operate(async options => {
    await archiveAssignedWorkflow(options, flow.workflow_id);
    options.ensureCurrent(); setNotice('Workflow archived. Retained input and result files are kept separately.');
  });
  const data = snapshot?.scope === scope ? snapshot.data : null;
  return <section className="console-panel agent-workspace">
    <div className="console-section-heading"><div><span className="console-eyebrow">DELEGATED EXECUTION</span><h2>Give the work to your agent</h2><p>Assign data and inspect the same agent's tasks, cost and results here.</p></div></div>
    <div className="workflow-agent-choice">
      <label htmlFor="workflow-agent">Agent public key<input id="workflow-agent" list="workflow-agent-options" value={agent} disabled={busy || disabled} onChange={event => setAgent(event.target.value.trim())} placeholder="Choose an owner-issued agent" autoComplete="off" /></label>
      <datalist id="workflow-agent-options">{passports.map(item => <option value={item.agent_pubkey} key={item.agent_pubkey}>{item.name}</option>)}</datalist>
      <button className="console-button secondary" onClick={loadAgents} disabled={!canOperate}><Icon name="shield" size={16} />Load my agents</button>
      <button className="console-text-button" type="button" onClick={() => {
        setAgent('7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU');
        setNotice('Demo agent key loaded (autonomous financial worker). Assign inputs or start host observation.');
      }}><Icon name="spark" size={15} />Demo agent</button>
    </div>
    <div className="workflow-hero-actions">
      <button className={'console-button ' + (currentAssigned ? 'secondary' : 'primary')} onClick={handoff} disabled={!canOperate || !agent || agent === owner || !plan || Boolean(currentAssigned)}><Icon name="upload" size={16} />{currentAssigned ? 'Files assigned' : busy ? 'Authorizing…' : 'Assign selected files'}</button>
      {currentAssigned && <button className="console-button secondary" onClick={() => saveFile('aperture-agent-workflow.json', JSON.stringify(currentAssigned, null, 2), 'application/json')}><Icon name="download" size={16} />Export assigned plan</button>}
      {currentAssigned && <button className="console-button primary" onClick={submit} disabled={!canOperate}><Icon name="play" size={16} />Approve {(currentAssigned.max_cost_lamports / 1e9).toLocaleString('en-US', { maximumFractionDigits: 9 })} SOL maximum</button>}
      <button className="console-button secondary" onClick={observe} disabled={!canOperate || !agent}><Icon name="eye" size={16} />{view ? 'Renew observation' : 'Open agent workspace'}</button>
    </div>
    {notice && <p className="workflow-plan-state" role="status">{notice}</p>}
    {data && <>
      <ol className="workflow-step-list">{data.workflows.filter(flow => flow.status !== 'archived').map(flow => <li key={flow.workflow_id}>
        <div className="workflow-step-content"><strong>{flow.status === 'queued' ? 'Waiting for agent host' : flow.status === 'attention' ? 'Agent host needs recovery' : flow.status} · {flow.completed_steps}/{flow.total_steps} steps</strong>
          <p>{context.network === 'off_chain' ? 'Off-chain · no SOL payment' : flow.charged_lamports + ' lamports settled'} · {(flow.max_cost_lamports / 1e9).toLocaleString('en-US', { maximumFractionDigits: 9 })} SOL maximum</p>
          {flow.detail && <p>{flow.detail}</p>}
          {flow.stop_requested && !['stopped', 'completed', 'failed'].includes(flow.status) && <p>Stop requested · waiting for final settlement</p>}
          {flow.status === 'queued' && <p>Keep your agent host running to accept approved plans and publish progress here.</p>}
        </div>
        {!['completed', 'failed', 'stopped'].includes(flow.status) ? <button className="console-button secondary" onClick={() => stop(flow)} disabled={!canOperate || flow.stop_requested}>Stop workflow</button>
          : <button className="console-text-button" onClick={() => archive(flow)} disabled={!canOperate}>Archive</button>}
      </li>)}</ol>
      <p>{data.storage.object_count} retained files · {(data.storage.size_bytes / 1048576).toFixed(2)} MiB · {data.tasks.length} recent tasks{data.next_cursor ? ' (older tasks are available through the SDK)' : ''}</p>
      {!data.tasks.length && <p>No tasks yet. Start the assigned plan from this agent's configured host.</p>}
      <ol className="workflow-step-list">{data.tasks.map(task => <li key={task.task_id} className="agent-task-result">
        <div className="workflow-step-content"><strong>{task.task_id.slice(0, 13)}… · {task.execution_status || task.status}</strong>
          <p>{task.receipt ? task.receipt.settlement_type === 'OFF_CHAIN' ? 'Off-chain execution · no SOL payment' : task.receipt.charged_lamports + ' lamports charged' : 'Maximum ' + task.max_cost_lamports + ' lamports · awaiting final evidence'}</p>
          {task.receipt?.execution_status === 'failed' && <pre>{task.full_log.slice(-3000)}</pre>}
          {task.receipt?.artifacts?.length > 0 && <ResultFiles files={task.receipt.artifacts} scope={scope + task.task_id} disabled={!view || busy}
            onRead={file => readAgentArtifact(context, view, task, file, connection)}
            onDownload={async file => saveFile(file.name, await readAgentArtifact(context, view, task, file, connection), 'application/octet-stream')} />}
        </div>
      </li>)}</ol>
    </>}
    <details className="workflow-reference-editor"><summary>Connect an agent host</summary><p>Configure the same dedicated agent, gateway and spending limits as its MCP connection. Start the receiver once; it accepts only plans you approve here. Keep the same workflow folder when restarting to recover progress.</p><CommandBlock label="Agent receiver" command="python examples/receive_workflows.py" /></details>
  </section>;
}
