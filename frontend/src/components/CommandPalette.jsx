import { useState, useEffect, useRef } from 'react';
import Icon from './Icon';
import './CommandPalette.css';

export default function CommandPalette({
  isOpen,
  onClose,
  onNavigate,
  onOpenSample,
  onOpenAttestation,
  onRefresh,
}) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef(null);

  const COMMANDS = [
    {
      id: 'nav-overview',
      category: 'Navigation',
      title: 'Go to Workspace Overview',
      subtitle: 'Telemetry grid, live demo simulator, zero-leak pipeline',
      icon: 'grid',
      shortcut: '1',
      action: () => { onNavigate('overview'); onClose(); },
    },
    {
      id: 'nav-studio',
      category: 'Navigation',
      title: 'Open Compute Studio',
      subtitle: 'Python editor, live streaming log terminal, tariffs',
      icon: 'code',
      shortcut: '2',
      action: () => { onNavigate('studio'); onClose(); },
    },
    {
      id: 'nav-workflows',
      category: 'Navigation',
      title: 'View Agent Workflows',
      subtitle: 'DAG batch execution, CSV partitioning, spend limits',
      icon: 'network',
      shortcut: '3',
      action: () => { onNavigate('workflows'); onClose(); },
    },
    {
      id: 'nav-storage',
      category: 'Navigation',
      title: 'Browse Private Storage',
      subtitle: 'Encrypted inputs, signed file release, quota tracking',
      icon: 'book',
      shortcut: '4',
      action: () => { onNavigate('storage'); onClose(); },
    },
    {
      id: 'nav-agents',
      category: 'Navigation',
      title: 'Manage Agent Passports',
      subtitle: 'Delegated capabilities, budget caps, owner inbox',
      icon: 'shield',
      shortcut: '5',
      action: () => { onNavigate('agents'); onClose(); },
    },
    {
      id: 'sample-risk',
      category: 'Live Simulations',
      title: 'Run Monte Carlo Risk Simulation',
      subtitle: '10,000 portfolio scenarios, Value at Risk (VaR 95%)',
      icon: 'spark',
      action: () => { onOpenSample('risk'); onClose(); },
    },
    {
      id: 'sample-dataset',
      category: 'Live Simulations',
      title: 'Process Confidential Dataset',
      subtitle: 'CSV category aggregation with 0 token context leakage',
      icon: 'spark',
      action: () => { onOpenSample('dataset'); onClose(); },
    },
    {
      id: 'sample-policy',
      category: 'Live Simulations',
      title: 'Test Sandbox Policy Rejection',
      subtitle: 'Demonstrate AST security intercept and 403 guardrails',
      icon: 'shield',
      action: () => { onOpenSample('policy'); onClose(); },
    },
    {
      id: 'proof-verify',
      category: 'Cryptographic Security',
      title: 'Inspect Cryptographic Attestation',
      subtitle: 'Ed25519 oracle signature, program ID, and artifact SHA-256',
      icon: 'shield',
      action: () => { onOpenAttestation(); onClose(); },
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
