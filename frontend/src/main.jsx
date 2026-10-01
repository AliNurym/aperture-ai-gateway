// 🔥 ШАГ 1: РУЧНЫЕ ПОЛИФИЛЛЫ (ДОЛЖНЫ БЫТЬ ПЕРВЫМИ!)
import { Buffer } from 'buffer';
import process from 'process';

window.Buffer = Buffer;
window.process = process;
window.global = window;

// Теперь всё остальное
import React, { useMemo } from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import ErrorBoundary from './components/ErrorBoundary';
import SessionKeyAdapter from './utils/SessionKeyAdapter';

// Импорты Соланы
import { ConnectionProvider, WalletProvider } from '@solana/wallet-adapter-react';
import { WalletModalProvider } from '@solana/wallet-adapter-react-ui';
import { PhantomWalletAdapter } from '@solana/wallet-adapter-phantom';
import { SolflareWalletAdapter } from '@solana/wallet-adapter-solflare';
import { clusterApiUrl } from '@solana/web3.js';

// ВАЖНО: Дефолтные стили для модального окна
import '@solana/wallet-adapter-react-ui/styles.css';
import './index.css';

function Root() {
  const endpoint = useMemo(() => clusterApiUrl('devnet'), []);

  const wallets = useMemo(() => [
    ...(import.meta.env.DEV && import.meta.env.VITE_ENABLE_SESSION_KEY === 'true' ? [new SessionKeyAdapter()] : []),
    new PhantomWalletAdapter(),
    new SolflareWalletAdapter(),
  ], []);

  return (
    <ConnectionProvider endpoint={endpoint}>
      <WalletProvider wallets={wallets} autoConnect={false}>
        <WalletModalProvider>
          <ErrorBoundary><App /></ErrorBoundary>
        </WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}

const root = import.meta.hot?.data.root ?? ReactDOM.createRoot(document.getElementById('root'));
if (import.meta.hot) import.meta.hot.data.root = root;

root.render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
