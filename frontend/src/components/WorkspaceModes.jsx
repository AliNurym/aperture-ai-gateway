import Icon from './Icon';

export default function WorkspaceModes({ mode, onPython, onInference, onWorkflows, inferenceBusy = false }) {
  return <div className="console-studio-switcher" role="group" aria-label="Workload type">
    <button id="studio-python-tab" type="button" className={mode === 'python' ? 'selected' : ''}
      aria-pressed={mode === 'python'} aria-controls="studio-python-panel" onClick={onPython}>
      <Icon name="code" size={16} />Python compute
    </button>
    <button id="studio-inference-tab" type="button" className={mode === 'inference' ? 'selected' : ''}
      aria-pressed={mode === 'inference'} aria-controls="studio-inference-panel" onClick={onInference}>
      <Icon name="spark" size={16} />Model inference
      {inferenceBusy && <i className="console-running-dot" aria-label="Inference running" />}
    </button>
    <button type="button" className={mode === 'workflows' ? 'selected' : ''}
      aria-pressed={mode === 'workflows'} onClick={onWorkflows}>
      <Icon name="network" size={16} />Agent workflows
    </button>
  </div>;
}
