import { BaseMessageSignerWalletAdapter, WalletReadyState, WalletNotConnectedError, WalletConnectionError } from '@solana/wallet-adapter-base';
import { PublicKey } from '@solana/web3.js';
import { Buffer } from 'buffer';

// Development only. A real, non-extractable Ed25519 key, created on explicit
// connection. No preset address, persisted private key or simulated signature.
export default class SessionKeyAdapter extends BaseMessageSignerWalletAdapter {
  name = 'Temporary key';
  url = 'https://solana.com/docs/core/accounts';
  icon = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIzMiIgaGVpZ2h0PSIzMiIgdmlld0JveD0iMCAwIDMyIDMyIj48cmVjdCB3aWR0aD0iMzIiIGhlaWdodD0iMzIiIHJ4PSI5IiBmaWxsPSIjZTJkN2YxIi8+PHBhdGggZD0iTTE5IDlhNSA1IDAgMSAwIDMgOWwzIDNoM2wtMS0zLTMtM2E1IDUgMCAwIDAtNS02Wm0tMSAzYTIgMiAwIDEgMSAwIDQgMiAyIDAgMCAxIDAtNFoiIGZpbGw9IiM2NzUwYTQiLz48L3N2Zz4=';
  supportedTransactionVersions = new Set(['legacy', 0]);
  _key = null;
  _publicKey = null;
  _connecting = false;

  get publicKey() { return this._publicKey; }
  get connecting() { return this._connecting; }
  get readyState() { return WalletReadyState.Loadable; }

  async connect() {
    if (this.connected || this._connecting) return;
    this._connecting = true;
    try {
      const pair = await crypto.subtle.generateKey('Ed25519', false, ['sign', 'verify']);
      this._publicKey = new PublicKey(new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey)));
      this._key = pair.privateKey;
      this.emit('connect', this._publicKey);
    } catch (cause) {
      const error = new WalletConnectionError('This browser cannot create an Ed25519 key. Use Phantom or Solflare.', cause);
      this.emit('error', error);
      throw error;
    } finally { this._connecting = false; }
  }

  async disconnect() {
    this._key = null;
    this._publicKey = null;
    this.emit('disconnect');
  }

  async signMessage(message) {
    if (!this._key) throw new WalletNotConnectedError();
    return new Uint8Array(await crypto.subtle.sign('Ed25519', this._key, message));
  }

  async signTransaction(transaction) {
    if (!this.publicKey) throw new WalletNotConnectedError();
    if ('version' in transaction) {
      const index = transaction.message.staticAccountKeys
        .slice(0, transaction.message.header.numRequiredSignatures)
        .findIndex(key => key.equals(this.publicKey));
      if (index < 0) throw new Error('This transaction does not require the temporary key.');
      transaction.signatures[index] = await this.signMessage(transaction.message.serialize());
    } else {
      transaction.addSignature(this.publicKey, Buffer.from(await this.signMessage(transaction.serializeMessage())));
    }
    return transaction;
  }
}
