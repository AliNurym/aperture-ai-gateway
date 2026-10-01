import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import Icon from './components/Icon';
import { canonicalJson } from './utils/protocol';
import { requestErrorMessage } from './utils/requestError';
import { objectReference, releaseStorageObject, requestStorageUsage, storageContext } from './utils/storage';
import './Storage.css';

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' KiB';
  return (bytes / (1024 * 1024)).toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' MiB';
}

function releaseError(error) {
  const detail = requestErrorMessage(error);
  if (error.response?.status === 409) {
    const reason = detail.toLowerCase();
    if (reason.includes('quote')) return 'This file is bound to an unused quote. Wait for the quote to expire, then refresh storage and try again.';
    if (reason.includes('active task')) return 'An active job still needs this file. Wait until the job finishes, then refresh storage and try again.';
    if (reason.includes('upload')) return 'This file is still uploading. Wait for the upload to finish, then refresh storage.';
    return 'The gateway protected this file from release: ' + detail;
  }
  if (!axios.isAxiosError(error)) return 'Could not release the selected file: ' + detail;
  if (!error.response || error.response.status >= 500) return 'The release response was not confirmed. Refresh storage to check the file, or retry release for this same selected object.';
  return 'Could not release the selected file: ' + detail;
}

const STATE_LABELS = { authorized: 'Reserved', uploading: 'Uploading', ready: 'Ready', deleting: 'Releasing' };

export default function Storage({ apiUrl, gatewayHealth, gatewayOnline, onOpenStudio, onObjectReleased }) {
  const { publicKey, signMessage, wallet, connect, connecting } = useWallet();
  const { setVisible } = useWalletModal();
  const owner = publicKey?.toBase58() || null;
  let context = null;
  let contextError = '';
  try { if (gatewayOnline) context = storageContext(apiUrl, gatewayHealth); }
  catch (error) { contextError = error.message; }
  const scope = canonicalJson({
    owner, apiUrl: apiUrl || '', online: Boolean(gatewayOnline),
    program_id: gatewayHealth?.program_id ?? null,
    gateway_pubkey: gatewayHealth?.gateway_pubkey ?? null,
    network: gatewayHealth?.demo_mode === true ? 'off_chain' : gatewayHealth?.demo_mode === false ? 'devnet' : null,
  });
  const [snapshot, setSnapshot] = useState(null);
  const [selected, setSelected] = useState(null);
  const [operation, setOperation] = useState(null);
  const [notice, setNotice] = useState(null);
  const [filter, setFilter] = useState('all');
  const controller = useRef(null);
  const generation = useRef(0);
  const currentScope = useRef(scope);
  const confirmationHeading = useRef(null);
  const usage = snapshot?.scope === scope ? snapshot.usage : null;
  const selection = selected?.scope === scope ? selected.reference : null;
  const busy = operation?.scope === scope;
  const currentNotice = notice?.scope === scope ? notice : null;
  const canSign = Boolean(owner && signMessage && context && gatewayOnline);
  const files = usage?.objects.filter(item => filter === 'all' || (item.task_id ? 'outputs' : 'inputs') === filter) || [];

  useLayoutEffect(() => {
    currentScope.current = scope;
    generation.current += 1;
    controller.current?.abort();
    controller.current = null;
    setSnapshot(null); setSelected(null); setOperation(null); setNotice(null);
    return () => { controller.current?.abort(); controller.current = null; };
  }, [scope]);

  useEffect(() => {
    if (selection) confirmationHeading.current?.focus();
  }, [selection]);

  const showNotice = (message, kind = 'error') => setNotice({ scope, message, kind });
  const connectWallet = async () => {
    if (!wallet) { setVisible(true); return; }
    try { await connect(); }
    catch (error) { showNotice('Wallet connection failed: ' + requestErrorMessage(error)); }
  };
  const begin = phase => {
    if (controller.current || !canSign) return null;
    const attempt = new AbortController();
    const revision = ++generation.current;
    controller.current = attempt;
    setOperation({ scope, phase }); setNotice(null);
    const ensureCurrent = () => {
      if (attempt.signal.aborted || generation.current !== revision || currentScope.current !== scope) throw new DOMException('Private storage request was cancelled.', 'AbortError');
    };
    return { attempt, ensureCurrent };
  };
  const finish = attempt => {
    if (controller.current === attempt) { controller.current = null; setOperation(null); }
  };
  const refresh = async () => {
    if (!owner) { await connectWallet(); return; }
    if (!canSign) { showNotice(contextError || 'Connect the gateway and a wallet that supports message signing.'); return; }
    const request = begin('reading');
    if (!request) return;
    const { attempt, ensureCurrent } = request;
    try {
      const next = await requestStorageUsage({ context, owner, signMessage, signal: attempt.signal, ensureCurrent });
      ensureCurrent();
      setSnapshot({ scope, usage: next, updated: new Date() });
      setSelected(null);
    } catch (error) {
      if (!attempt.signal.aborted && currentScope.current === scope && !axios.isCancel(error) && error.name !== 'AbortError') showNotice('Could not read private storage: ' + requestErrorMessage(error));
    } finally { finish(attempt); }
  };
  const release = async () => {
    if (!selection || busy || !canSign) return;
    const retained = usage?.objects.find(item => item.object_id === selection.object_id);
    if (!retained || canonicalJson(objectReference(retained)) !== canonicalJson(selection)) {
      showNotice('The selected file changed. Refresh storage before choosing it again.'); return;
    }
    const request = begin('releasing');
    if (!request) return;
    const { attempt, ensureCurrent } = request;
    try {
      await releaseStorageObject({ context, owner, signMessage, reference: selection, signal: attempt.signal, ensureCurrent });
      ensureCurrent();
      setSnapshot(previous => {
        if (previous?.scope !== scope) return previous;
        const objects = previous.usage.objects.filter(item => item.object_id !== selection.object_id);
        return { ...previous, usage: { ...previous.usage, objects, object_count: objects.length, size_bytes: objects.reduce((sum, item) => sum + item.size_bytes, 0) } };
      });
      setSelected(null);
      showNotice(selection.name + ' was released. Refresh to retrieve the latest usage from the gateway.', 'success');
      onObjectReleased?.({ owner, object_id: selection.object_id, api_url: context.apiUrl,
        gateway_pubkey: context.gateway_pubkey, program_id: context.program_id, network: context.network });
    } catch (error) {
      if (!attempt.signal.aborted && currentScope.current === scope && !axios.isCancel(error) && error.name !== 'AbortError') showNotice(releaseError(error));
    } finally { finish(attempt); }
  };

  return <div className="storage">
    <section className="storage-intro">
      <div><span className="console-eyebrow"><Icon name="shield" size={16} /> PRIVATE WORKSPACE</span><h2>Your data.<br /><span>Room to grow.</span></h2><p>Keep reusable inputs and result files together. Inspect your allowance and release the files you no longer need.</p></div>
      <div className="storage-identity"><Icon name="wallet" size={22} /><span>Signing identity<strong>{owner ? owner.slice(0, 6) + '…' + owner.slice(-6) : 'Wallet not connected'}</strong><small>{context ? context.network === 'off_chain' ? 'Off-chain gateway' : 'Solana Devnet gateway' : 'Gateway unavailable'}</small></span></div>
    </section>
    {currentNotice && <div className={'storage-notice ' + currentNotice.kind} role={currentNotice.kind === 'error' ? 'alert' : 'status'}><Icon name={currentNotice.kind === 'success' ? 'check' : 'shield'} size={18} /><p>{currentNotice.message}</p></div>}
    {!gatewayOnline && <div className="storage-notice" role="status"><Icon name="network" size={18} /><p>Reconnect the gateway to inspect or release retained files.</p></div>}
    {contextError && <div className="storage-notice error" role="alert"><Icon name="shield" size={18} /><p>{contextError}</p></div>}
    <section className="console-panel storage-capacity" aria-busy={busy}>
      <div className="console-section-heading"><div><h2>Storage allowance</h2><p>Private files for your current signing identity.</p></div><button className="console-button secondary" onClick={refresh} disabled={busy || connecting || Boolean(owner && !canSign)} aria-busy={busy}><Icon name={owner ? 'refresh' : 'wallet'} size={17} />{connecting ? 'Connecting…' : busy ? operation.phase === 'releasing' ? 'Releasing…' : 'Reading storage…' : !owner ? 'Connect wallet' : usage ? 'Refresh storage' : 'Open private storage'}</button></div>
      {usage ? <>
        <div className="storage-capacity-grid"><div className="storage-quota"><div><span>Retained and reserved bytes</span><strong>{formatBytes(usage.size_bytes)}<small> / {formatBytes(usage.max_size_bytes)}</small></strong></div><progress max={usage.max_size_bytes} value={usage.size_bytes} aria-label="Storage bytes used" /><p>{formatBytes(usage.max_size_bytes - usage.size_bytes)} available</p></div><div className="storage-quota storage-object-quota"><span>File slots</span><strong>{usage.object_count}<small> / {usage.max_object_count}</small></strong><progress max={usage.max_object_count} value={usage.object_count} aria-label="File slots used" /><p>Ready files and upload reservations count toward your allowance.</p></div></div>
        <p className="storage-last-update">Last gateway read: {snapshot.updated.toLocaleTimeString()}. Refresh requests a wallet signature.</p>
      </> : <div className="storage-locked"><span><Icon name="shield" size={26} /></span><div><h3>{owner ? 'Open your private file list' : 'Connect your signing wallet'}</h3><p>{owner && !signMessage ? 'This wallet cannot sign messages. Choose a compatible wallet to access private files.' : 'A short-lived signed request opens this identity’s storage. No files are listed until the gateway responds.'}</p></div></div>}
    </section>
    {selection && <section className="console-panel storage-release-review" aria-labelledby="storage-release-title"><div className="console-section-heading"><div><span className="console-eyebrow">SELECTED FILE</span><h2 id="storage-release-title" tabIndex={-1} ref={confirmationHeading}>Release {selection.name}?</h2></div><Icon name="shield" size={22} /></div><p>Releases {formatBytes(selection.size_bytes)} of retained storage. Download any needed result first. Released bytes cannot be restored; historical receipts retain their signed metadata.</p><dl><div><dt>Object</dt><dd>{selection.object_id}</dd></div><div><dt>SHA-256</dt><dd>{selection.sha256}</dd></div></dl><p className="storage-protection">Active jobs, ongoing uploads and unexpired unused quotes protect their files from release.</p><div className="storage-release-actions"><button className="console-button secondary" disabled={busy} onClick={() => setSelected(null)}>Keep file</button><button className="console-button storage-release-button" disabled={busy || !canSign} onClick={release} aria-busy={busy}><Icon name="close" size={16} />{busy ? 'Waiting for release…' : 'Sign & release this file'}</button></div></section>}
    {usage && <section className="console-panel storage-files"><div className="console-section-heading"><div><h2>Retained files</h2><p>{files.length} {filter === 'all' ? 'files' : filter} shown</p></div><div className="storage-filters" role="group" aria-label="Filter retained files">{[['all', 'All files'], ['inputs', 'Inputs'], ['outputs', 'Outputs']].map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)} disabled={busy}>{label}</button>)}</div></div>
      {files.length ? <div className="storage-table-scroll"><table><thead><tr><th scope="col">File</th><th scope="col">State</th><th scope="col">Size</th><th scope="col"><span className="storage-sr-only">File action</span></th></tr></thead><tbody>{files.map(item => <tr key={item.object_id}><td><div className="storage-file-name"><Icon name={item.task_id ? 'download' : 'upload'} size={18} /><div><strong>{item.name}</strong><span>{item.task_id ? 'Output' : 'Input'} · {item.object_id.slice(0, 12)}…</span></div></div><details className="storage-file-details"><summary>File identity</summary><dl><div><dt>Object</dt><dd>{item.object_id}</dd></div><div><dt>SHA-256</dt><dd>{item.sha256}</dd></div>{item.task_id && <div><dt>Task</dt><dd>{item.task_id}</dd></div>}</dl></details></td><td><span className={'console-tag ' + (item.state === 'ready' ? '' : 'neutral')}>{STATE_LABELS[item.state]}</span></td><td className="storage-file-size">{formatBytes(item.size_bytes)}</td><td><button className="console-text-button" disabled={busy || item.state === 'uploading' || item.state === 'deleting'} aria-label={'Review release of ' + item.name + ', object ' + item.object_id} aria-pressed={selection?.object_id === item.object_id} onClick={() => { setSelected({ scope, reference: objectReference(item) }); setNotice(null); }}>Review release<Icon name="arrow" size={15} /></button></td></tr>)}</tbody></table></div>
        : <div className="storage-empty"><Icon name={filter === 'outputs' ? 'download' : 'upload'} size={28} /><h3>{usage.object_count === 0 ? 'Your storage is clear' : 'No ' + filter + ' in this file list'}</h3><p>{usage.object_count === 0 ? 'Upload an input in Compute Studio. Result files will appear after a data job publishes them.' : 'Choose another filter to see your retained files.'}</p>{usage.object_count === 0 && onOpenStudio && <button className="console-button secondary" onClick={onOpenStudio}>Open Compute Studio<Icon name="arrow" size={16} /></button>}</div>}
      <p className="storage-scope-note">This list covers uploads and outputs signed by this wallet. A delegated agent has its own private storage; inspect it through that agent’s configured SDK or MCP tools.</p>
    </section>}
  </div>;
}
