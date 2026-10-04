import { useLayoutEffect, useRef, useState } from 'react';
import Icon from './Icon';
import { canPreviewFile, previewResult } from '../utils/resultPreview';
import { requestErrorMessage } from '../utils/requestError';
import { revealContent } from '../utils/motion';
import './ResultFiles.css';

export default function ResultFiles({ files, scope, onRead, onDownload, disabled = false }) {
  const [pending, setPending] = useState(null);
  const [opened, setOpened] = useState(null);
  const [copied, setCopied] = useState(false);
  const [notice, setNotice] = useState('');
  const generation = useRef(0);
  const operating = useRef(false);
  const previewRef = useRef(null);
  const previewTrigger = useRef(null);
  const currentPreview = useRef(null);
  useLayoutEffect(() => {
    generation.current += 1; operating.current = false;
    setPending(null); setOpened(null); setNotice(''); setCopied(false);
    previewTrigger.current = null;
    return () => { generation.current += 1; };
  }, [scope, disabled]);
  useLayoutEffect(() => {
    currentPreview.current = opened;
    if (!opened) return undefined;
    const frame = requestAnimationFrame(() => revealContent(previewRef.current,
      { source: previewTrigger.current, focus: opened.keyboard }));
    return () => cancelAnimationFrame(frame);
  }, [opened]);

  const open = async (file, download = false, trigger = null, keyboard = false) => {
    if (disabled || operating.current) return;
    const current = generation.current;
    operating.current = true; setPending(file.object_id); setNotice('');
    try {
      if (download) await onDownload(file);
      else {
        if (!canPreviewFile(file)) throw new Error('Download this file to open it. Preview supports JSON, CSV and text up to 1 MiB.');
        const bytes = await onRead(file);
        if (generation.current !== current) return;
        if (!(bytes instanceof Uint8Array) && !(bytes instanceof ArrayBuffer)) throw new Error('Verified file bytes were not returned. Try again after the current operation finishes.');
        const data = previewResult(file, bytes);
        const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
        previewTrigger.current = trigger;
        setCopied(false);
        setOpened({ file, data, text, keyboard });
      }
    } catch (error) {
      if (generation.current === current) setNotice(requestErrorMessage(error));
    } finally {
      if (generation.current === current) { operating.current = false; setPending(null); }
    }
  };
  const closePreview = event => {
    revealContent(previewTrigger.current, { source: event.currentTarget, focus: true });
    previewTrigger.current = null;
    setOpened(null);
  };
  const copyText = async () => {
    const current = generation.current;
    try {
      await navigator.clipboard.writeText(opened.text);
      if (generation.current === current && currentPreview.current === opened) setCopied(true);
    } catch { if (generation.current === current && currentPreview.current === opened) setNotice('Clipboard unavailable. Download the verified file instead.'); }
  };

  return <div className="result-files">
    <ul className="result-files-list" aria-label="Verified result files">{files.map(file => <li key={file.object_id}>
      <div className="result-file-label"><Icon name="book" size={18} /><span>{file.name}<small>{(file.size_bytes / 1024).toLocaleString('en-US', { maximumFractionDigits: 1 })} KiB</small></span></div>
      <div className="result-file-actions">
        {canPreviewFile(file) && <button className="console-button secondary" disabled={disabled} aria-disabled={disabled || Boolean(pending)} onClick={event => open(file, false, event.currentTarget, event.detail === 0)} aria-label={'Open verified ' + file.name}><Icon name="eye" size={16} />Open</button>}
        <button className="console-text-button" disabled={disabled} aria-disabled={disabled || Boolean(pending)} onClick={() => open(file, true)} aria-label={'Download verified ' + file.name}><Icon name="download" size={16} />Download</button>
      </div>
      {pending === file.object_id && <span className="result-file-loading" role="status"><Icon name="refresh" spinning size={14} />Verifying receipt and file…</span>}
    </li>)}</ul>
    {notice && <p className="result-file-notice" role="alert">{notice}</p>}
    {opened && <section ref={previewRef} className="result-preview" tabIndex={-1} aria-label={'Preview of ' + opened.file.name}>
      <div className="result-preview-heading"><div><span className="console-eyebrow">VERIFIED FILE</span><h4>{opened.file.name}</h4></div><div className="result-preview-actions"><button className="console-text-button" onClick={copyText} aria-label={'Copy verified text from ' + opened.file.name}><Icon name={copied ? 'check' : 'copy'} size={16} />{copied ? 'Copied' : 'Copy text'}</button><button className="console-text-button" aria-label="Close file preview" onClick={closePreview}><Icon name="close" size={18} />Close</button></div></div>
      {opened.data.metrics && <dl className="result-preview-metrics">{opened.data.metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value.toLocaleString('en-US')}</dd></div>)}</dl>}
      {opened.data.note && <p className="result-preview-note">{opened.data.note}</p>}
      {opened.data.quality && <div className="result-preview-quality"><h4>Data quality</h4>
        {opened.data.quality.reasons.length > 0 ? <ul>{opened.data.quality.reasons.map(([reason, count]) => <li key={reason}>{reason.replaceAll('_', ' ')}: {count.toLocaleString('en-US')}</li>)}</ul> : <p>No excluded records.</p>}
        {opened.data.quality.missingGroups > 0 && <p>{opened.data.quality.missingGroups.toLocaleString('en-US')} records included as uncategorized.</p>}
        {!opened.data.quality.duplicatesChecked && <p>Duplicates were not checked or removed. All accepted records contribute to totals.</p>}
      </div>}
      {opened.data.rows ? <><div className="result-preview-table" tabIndex={0} role="region" aria-label="Result table"><table><thead><tr>{opened.data.columns.map((label, index) => <th key={index} scope="col">{label || 'Column ' + (index + 1)}</th>)}</tr></thead><tbody>{opened.data.rows.map((row, index) => <tr key={index}>{row.map((value, column) => <td key={column}>{value}</td>)}</tr>)}</tbody></table></div><p className="result-preview-footnote">Showing {opened.data.rows.length.toLocaleString('en-US')} of {opened.data.count.toLocaleString('en-US')} rows. Download for the complete file.</p></> : <><pre className="result-preview-text">{opened.data.text || '(Empty file)'}</pre>{opened.data.truncated && <p className="result-preview-footnote">Text preview is shortened. Download for the complete file.</p>}</>}
    </section>}
  </div>;
}
