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
import './index.css';

// Импорты Соланы
import { ConnectionProvider, WalletProvider } from '@solana/wallet-adapter-react';
import { WalletModalProvider } from '@solana/wallet-adapter-react-ui';
import { 
  PhantomWalletAdapter, 
  SolflareWalletAdapter, 
  TorusWalletAdapter 
} from '@solana/wallet-adapter-wallets';
import { clusterApiUrl } from '@solana/web3.js';

// ВАЖНО: Дефолтные стили для модального окна
import '@solana/wallet-adapter-react-ui/styles.css';

function Root() {
  const endpoint = useMemo(() => clusterApiUrl('devnet'), []);

  const wallets = useMemo(() => [
    new PhantomWalletAdapter(),
    new SolflareWalletAdapter(),
    new TorusWalletAdapter(),
  ], []);

  return (
    <ConnectionProvider endpoint={endpoint}>
      <WalletProvider wallets={wallets} autoConnect={false}>
        <WalletModalProvider>
          <App />
        </WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);