import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import Icon from './components/Icon';
import { requestErrorMessage } from './utils/requestError';
import './ProviderWorkspace.css';

const number = value => Number.isFinite(value) ? value.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—';
const sol = value => Number.isSafeInteger(value) ? (value / 1e9).toLocaleString('en-US', { maximumFractionDigits: 9 }) : '—';
const when = value => Number.isFinite(value) ? new Date(value * 1000).toLocaleString() : '—';
const headers = session => ({ 'X-Aperture-Worker-Id': session.id, 'X-Aperture-Worker-Token': session.token });

export default function ProviderWorkspace({ apiUrl, health, onOpenGuide, onOpenNetwork }) {
  const [workerId, setWorkerId] = useState('');
  const [token, setToken] = useState('');
  const [session, setSession] = useState(null);
  const [worker, setWorker] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [changing, setChanging] = useState(false);
  const [updated, setUpdated] = useState(null);
  const currentSession = useRef(session);
  const requestVersion = useRef(0);
  const modePending = useRef(false);

  useEffect(() => {
    currentSession.current = session;
    return () => { currentSession.current = null; };
  }, [session]);

  const refresh = useCallback(async signal => {
    if (!session || modePending.current) return;
    const version = ++requestVersion.current;
    try {
      const { data } = await axios.get(apiUrl + '/workers/me', { headers: headers(session), signal, timeout: 10000 });
      if (currentSession.current !== session || signal?.aborted || version !== requestVersion.current) return;
      if (data.node_id !== session.id || typeof data.accepting_tasks !== 'boolean' || !data.totals || !Array.isArray(data.recent_tasks)) throw new Error('The gateway returned an invalid worker record.');
      setWorker(data); setUpdated(new Date()); setError('');
    } catch (err) {
      if (signal?.aborted || currentSession.current !== session || version !== requestVersion.current) return;
      setError(requestErrorMessage(err));
      // A failed refresh must not leave old capacity presented as live.
      setWorker(null);
    } finally {
      if (!signal?.aborted && currentSession.current === session) setLoading(false);
    }
  }, [apiUrl, session]);

  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    refresh(controller.signal);
    const timer = setInterval(() => refresh(controller.signal), 10000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [refresh, session]);

  const connect = event => {
    event.preventDefault();
    if (!/^[!-~]{1,64}$/.test(workerId) || !/^[!-~]{16,}$/.test(token)) {
      setError('Enter the registered worker ID and its operator credential.'); return;
    }
    setWorker(null); setError(''); setLoading(true);
    setSession({ id: workerId, token }); setToken('');
  };

  const changeMode = async () => {
    if (!worker || changing) return;
    const original = session;
    modePending.current = true; requestVersion.current += 1;
    setChanging(true); setError('');
    try {
      const { data } = await axios.post(apiUrl + '/workers/me/mode', { accepting_tasks: !worker.accepting_tasks }, { headers: headers(session), timeout: 10000 });
      if (currentSession.current !== original) return;
      setWorker(data); setUpdated(new Date());
    } catch (err) {
      if (currentSession.current === original) { modePending.current = false; await refresh(); setError(requestErrorMessage(err)); }
    } finally {
      modePending.current = false;
      if (currentSession.current === original) setChanging(false);
    }
  };

  const disconnect = () => { currentSession.current = null; modePending.current = false; requestVersion.current += 1; setSession(null); setWorker(null); setToken(''); setError(''); setChanging(false); setLoading(false); };
  const totals = worker?.totals;
  return <div className="provider-workspace">
    <section className="console-panel provider-intro">
      <div><h2>Worker operations</h2><p>Inspect assigned tasks, control new admissions, and track charges paid to the worker’s signing address.</p></div>
      <div className="provider-actions"><button className="console-button secondary" onClick={onOpenNetwork}>Browse capacity</button><button className="console-button secondary" onClick={onOpenGuide}>Connect a worker <Icon name="arrow" size={16} /></button></div>
    </section>

    {!session ? <section className="console-panel provider-connect">
      <div><Icon name="chip" size={28} /><h3>Connect your running worker</h3><p>Enter your worker ID and operator token to manage admissions and inspect its task history.</p><button className="console-text-button" onClick={onOpenGuide}>Set up a new worker <Icon name="arrow" size={15} /></button><details className="provider-connection-help"><summary>Where to find your credentials</summary><p>Use the ID and token from your worker configuration. Credentials stay in memory until you disconnect or leave this page.</p>{health?.demo_mode && <p>The local preview prints the path to <code>worker-access.json</code>, containing its CPU worker ID and temporary token.</p>}</details></div>
      <form onSubmit={connect}>
        <label htmlFor="operator-worker-id">Registered worker ID<input id="operator-worker-id" autoComplete="off" value={workerId} onChange={event => setWorkerId(event.target.value)} required maxLength={64} placeholder="my-worker" /></label>
        <label htmlFor="operator-worker-token">Worker token<input id="operator-worker-token" type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} required placeholder="Paste your operator token" /></label>
        <button className="console-button primary" type="submit">Open worker workspace <Icon name="arrow" size={16} /></button>
      </form>
    </section> : <div className="provider-session"><span><Icon name="shield" size={16} /> Operator · {session.id}</span><div><button className="console-button secondary" onClick={() => { setLoading(true); refresh(); }} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button><button className="console-button secondary" onClick={disconnect}>Disconnect</button></div></div>}
    {error && <div className="console-notice error" role="alert">{error}</div>}
    {session && loading && !worker && <p role="status">Reading the registered worker and retained execution history…</p>}

    {worker && <>
      <section className="console-panel provider-identity">
        <div><span className={'console-tag ' + (!worker.online ? 'neutral' : '')}>{worker.status}</span><h2>{worker.node_id}</h2><p>{worker.gpu_name || 'Hardware not reported'} · {worker.execution_mode}</p><code>{worker.worker_pubkey}</code><small>Execution signing identity and task payout destination</small></div>
        <div className="provider-admission"><strong>{worker.accepting_tasks ? 'Accepting new tasks' : 'Draining worker'}</strong><p>{worker.accepting_tasks ? 'Compatible queued tasks may be assigned to this node.' : 'Existing leases can finish. No new tasks will be assigned until you resume.'}</p><button className="console-button primary" onClick={changeMode} disabled={changing}>{changing ? 'Saving…' : worker.accepting_tasks ? 'Drain worker' : 'Resume admissions'}</button><small>Last heartbeat · {when(worker.last_seen)}</small></div>
      </section>

      <section className="provider-totals" aria-label="Worker totals">
        <div><span>Confirmed Devnet earnings</span><strong>{sol(totals.paid_lamports)} <small>SOL</small></strong><p>{number(totals.paid_lamports)} lamports attributed to this worker</p></div>
        <div><span>Completed / finished tasks</span><strong>{number(totals.tasks_completed)} <small>/ {number(totals.tasks_finished)}</small></strong><p>{worker.active_tasks} currently assigned</p></div>
        <div><span>Compute delivered</span><strong>{number(totals.total_compute_seconds)} <small>sec</small></strong><p>Measured execution time from task receipts</p></div>
        <div><span>OFF_CHAIN activity</span><strong>{number(totals.off_chain_tasks)} <small>tasks</small></strong><p>{number(totals.off_chain_estimated_lamports)} estimated lamports · no transfer</p></div>
      </section>
      <section className="console-panel provider-history">
        <div className="console-section-heading"><div><span className="console-eyebrow">EXECUTOR ACTIVITY</span><h2>Recent assigned tasks</h2></div><small>{updated && 'Updated ' + updated.toLocaleTimeString()}</small></div>
        {worker.recent_tasks.length ? <div className="provider-table-scroll"><table><thead><tr><th>Task</th><th>Runtime</th><th>State</th><th>Execution</th><th>Worker payment</th></tr></thead><tbody>{worker.recent_tasks.map(task => <tr key={task.task_id}><td><code title={task.task_id}>{task.task_id.slice(0, 18)}…</code><small>{when(task.completed_at || task.created_at)}</small></td><td>{task.runtime}</td><td><span className="console-tag neutral">{task.state}</span></td><td>{task.execution_seconds == null ? '—' : number(task.execution_seconds) + ' sec'}</td><td>{task.settlement_type === 'DEVNET' && task.paid_lamports != null ? number(task.paid_lamports) + ' lamports' : task.settlement_type === 'OFF_CHAIN' ? 'OFF_CHAIN · no transfer' : task.settlement_type === 'NOT_STARTED' ? 'Not started · no charge' : 'Pending'}</td></tr>)}</tbody></table></div> : <div className="provider-empty"><Icon name="clock" size={24} /><h3>No assigned tasks yet</h3><p>{worker.accepting_tasks ? 'This node is ready to claim compatible work when its worker process is connected.' : 'Resume admissions when this node is ready for new work.'}</p></div>}
        <p className="provider-history-scope">Totals persist after history pruning. Tracking began {when(totals.tracked_since)}; {totals.baseline_finished} retained tasks were included as the baseline. Recent history contains up to 20 retained tasks.</p>
      </section>
      <section className="console-panel provider-capabilities"><h3>Published capacity</h3><dl><div><dt>Runtimes</dt><dd>{(worker.runtimes || ['python']).join(' · ')}</dd></div><div><dt>Source policy</dt><dd>{worker.source_policy || 'Not reported'}{worker.approved_source_count ? ' · ' + worker.approved_source_count + ' reviewed sources' : ''}</dd></div><div><dt>Model offers</dt><dd>{worker.inference_offers.length ? worker.inference_offers.map(offer => offer.name || offer.model).join(' · ') : 'None registered'}</dd></div><div><dt>Settlement mode</dt><dd>{health?.demo_mode ? 'OFF_CHAIN · no SOL transfers' : 'Solana Devnet'}</dd></div></dl><p>Updated contract source assigns the full confirmed task charge to the executing worker. A live payout requires the compatible program deployment and a confirmed Devnet task receipt. Hosted model provider charges are paid separately by the operator.</p></section>
    </>}
  </div>;
}
