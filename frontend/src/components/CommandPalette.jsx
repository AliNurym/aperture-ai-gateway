import { useState, useEffect, useRef } from 'react';
import Icon from './Icon';
import './CommandPalette.css';

export default function CommandPalette({
  isOpen,
  onClose,
  onNavigate,
  onOpenSample,
  onOpenReceiptGuide,
  onRefresh,
  onToggleTheme,
}) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef(null);

  const COMMANDS = [
    {
      id: 'nav-overview',
      category: 'Navigation',
      title: 'Go to Workspace Overview',
      subtitle: 'Worker status, illustrative workflow preview, bounded data workflow',
      icon: 'grid',
      shortcut: 'Alt+1',
      action: () => { onNavigate('overview'); onClose(); },
    },
    {
      id: 'nav-workflows',
      category: 'Navigation',
      title: 'View Agent Workflows',
      subtitle: 'DAG batch execution, CSV partitioning, spend limits',
      icon: 'network',
      shortcut: 'Alt+2',
      action: () => { onNavigate('workflows'); onClose(); },
    },
    {
      id: 'nav-studio',
      category: 'Navigation',
      title: 'Open Compute Studio',
      subtitle: 'Python editor, live streaming log terminal, tariffs',
      icon: 'code',
      shortcut: 'Alt+3',
      action: () => { onNavigate('studio'); onClose(); },
    },
    {
      id: 'nav-storage',
      category: 'Navigation',
      title: 'Browse Private Storage',
      subtitle: 'Owner-authorized inputs, signed file release, quota tracking',
      icon: 'download',
      shortcut: 'Alt+4',
      action: () => { onNavigate('storage'); onClose(); },
    },
    {
      id: 'nav-agents',
      category: 'Navigation',
      title: 'Manage Agent Passports',
      subtitle: 'Delegated capabilities, budget caps, owner inbox',
      icon: 'shield',
      shortcut: 'Alt+5',
      action: () => { onNavigate('agents'); onClose(); },
    },
    {
      id: 'nav-network',
      category: 'Navigation',
      title: 'Inspect Worker Network',
      subtitle: 'The available capacity and node states behind your workloads',
      icon: 'network',
      shortcut: 'Alt+6',
      action: () => { onNavigate('network'); onClose(); },
    },
    {
      id: 'nav-guide',
      category: 'Navigation',
      title: 'Getting Started Guide',
      subtitle: 'Connect execution and prepare your first workload',
      icon: 'book',
      shortcut: 'Alt+7',
      action: () => { onNavigate('guide'); onClose(); },
    },
    {
      id: 'sample-17k',
      category: 'Workload Samples',
      title: 'Load 17k Resilient CSV Pipeline',
      subtitle: 'Open the 17,280 record partitioned batch benchmark with auto-resume',
      icon: 'network',
      action: () => { onNavigate('workflows'); onClose(); },
    },
    {
      id: 'sample-risk',
      category: 'Workload Samples',
      title: 'Load Monte Carlo Risk Sample',
      subtitle: 'Open the reviewed workload in Compute Studio',
      icon: 'spark',
      action: () => { onOpenSample('risk'); onClose(); },
    },
    {
      id: 'sample-dataset',
      category: 'Workload Samples',
      title: 'Load Dataset Aggregation Sample',
      subtitle: 'Open the reviewed CSV workflow in Compute Studio',
      icon: 'spark',
      action: () => { onOpenSample('dataset'); onClose(); },
    },
    {
      id: 'sample-policy',
      category: 'Workload Samples',
      title: 'Load Policy Rejection Sample',
      subtitle: 'Open the source that the gateway policy should reject',
      icon: 'shield',
      action: () => { onOpenSample('policy'); onClose(); },
    },
    {
      id: 'proof-verify',
      category: 'Cryptographic Security',
      title: 'Open Receipt Verification Guide',
      subtitle: 'What gateway and worker signatures prove, and what they do not',
      icon: 'shield',
      action: () => { onOpenReceiptGuide(); onClose(); },
    },
    {
      id: 'doc-presentation',
      category: 'Documentation',
      title: 'Open Interactive Pitch Deck',
      subtitle: 'Launch the full Aperture architecture presentation slide deck',
      icon: 'book',
      action: () => { window.open('/presentation.html', '_blank'); onClose(); },
    },
    {
      id: 'theme-toggle',
      category: 'Preferences',
      title: 'Toggle Color Theme',
      subtitle: 'Switch between dark cyber and clean light appearance',
      icon: 'sun',
      shortcut: 'Alt+T',
      action: () => { onToggleTheme?.(); onClose(); },
    },
    {
      id: 'system-refresh',
      category: 'System',
      title: 'Refresh Gateway Telemetry',
      subtitle: 'Re-query worker nodes and health endpoint',
      icon: 'refresh',
      action: () => { onRefresh(); onClose(); },
    },
  ];

  const filtered = COMMANDS.filter(cmd => {
    const q = query.toLowerCase().trim();
    if (!q) return true;
    return cmd.title.toLowerCase().includes(q) ||
           cmd.subtitle.toLowerCase().includes(q) ||
           cmd.category.toLowerCase().includes(q);
  });

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => (prev + 1) % (filtered.length || 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => (prev - 1 + (filtered.length || 1)) % (filtered.length || 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filtered[selectedIndex]) {
        filtered[selectedIndex].action();
      }
    } else if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      let shortcut = null;
      if (/^(?:Digit|Numpad)[1-5]$/.test(e.code)) {
        shortcut = 'Alt+' + e.code.slice(-1);
      } else if (e.code === 'KeyT' || e.key.toLowerCase() === 't') {
        shortcut = 'Alt+T';
      }
      if (shortcut) {
        const command = COMMANDS.find(item => item.shortcut === shortcut);
        if (command) {
          e.preventDefault();
          command.action();
        }
      }
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette-dialog" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="palette-input-wrap">
          <Icon name="search" size={18} className="palette-search-icon" />
          <input
            ref={inputRef}
            type="text"
            className="palette-input"
            placeholder="Type a command or search workloads... (Esc to close)"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <kbd className="palette-esc-badge">Esc</kbd>
        </div>

        <div className="palette-list" role="listbox">
          {filtered.length > 0 ? (
            filtered.map((cmd, idx) => (
              <button
                key={cmd.id}
                className={`palette-item ${idx === selectedIndex ? 'selected' : ''}`}
                onClick={cmd.action}
                onMouseEnter={() => setSelectedIndex(idx)}
                role="option"
                aria-selected={idx === selectedIndex}
              >
                <span className="palette-item-icon">
                  <Icon name={cmd.icon} size={17} />
                </span>
                <div className="palette-item-text">
                  <span className="palette-item-title">{cmd.title}</span>
                  <span className="palette-item-sub">{cmd.subtitle}</span>
                </div>
                {cmd.shortcut && <kbd className="palette-item-shortcut">{cmd.shortcut}</kbd>}
              </button>
            ))
          ) : (
            <div className="palette-empty">
              <Icon name="search" size={24} />
              <p>No matching commands found for "{query}"</p>
            </div>
          )}
        </div>

        <footer className="palette-footer">
          <div className="palette-hints">
            <span><kbd>↑</kbd> <kbd>↓</kbd> navigate</span>
            <span><kbd>↵</kbd> select</span>
            <span><kbd>esc</kbd> close</span>
          </div>
          <span className="palette-branding">Aperture Command Grid</span>
        </footer>
      </div>
    </div>
  );
}
