import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import { PublicKey, SystemProgram, Transaction, TransactionInstruction } from '@solana/web3.js';
import Icon from './components/Icon';
import { APERTURE_PROGRAM_ID, agentInstructionData, canonicalJson, sha256Hex } from './utils/protocol';
import './Agents.css';

const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const localDate = value => new Date(value - new Date(value).getTimezoneOffset() * 60000).toISOString().slice(0, 16);
const defaults = () => ({ agent_pubkey: '', name: 'Research agent', maxCost: '0.001', maxRuntime: '30', totalBudget: '0.01', expires: localDate(Date.now() + 7 * 86400000) });
const errorText = error => typeof error.response?.data?.detail === 'string' ? error.response.data.detail : error.message;
const bytesEqual = (left, right) => left.length === right.length && left.every((value, index) => value === right[index]);
const decodeBase64 = value => Uint8Array.from(atob(value), character => character.charCodeAt(0));
const lamports = value => {
  const amount = Number(value) * 1e9;
  if (!Number.isSafeInteger(Math.round(amount)) || amount <= 0) throw new Error('Enter a positive SOL amount with up to nine decimal places.');
  return Math.round(amount);
};
function expectedAgentAccounts(action, owner, agent) {
  const programId = new PublicKey(APERTURE_PROGRAM_ID);
  const [passport] = PublicKey.findProgramAddressSync([new TextEncoder().encode('agent'), new PublicKey(agent).toBytes()], programId);
  const accounts = [
    { pubkey: passport.toBase58(), is_signer: false, is_writable: true },
    { pubkey: owner, is_signer: true, is_writable: true },
  ];
  if (action === 'register') accounts.push(
    { pubkey: agent, is_signer: false, is_writable: false },
    { pubkey: SystemProgram.programId.toBase58(), is_signer: false, is_writable: false },
  );
  return accounts;
}
async function verifyAgentChallenge(challenge, selectedPolicy, expectedNetwork) {
  const passport = challenge?.passport;
  if (!passport || !['register', 'update', 'revoke'].includes(challenge.action)
      || !challenge.nonce || challenge.nonce.length < 16 || challenge.nonce.length > 128
      || !Number.isSafeInteger(challenge.expires_at) || challenge.expires_at * 1000 <= Date.now()
      || challenge.expires_at * 1000 > Date.now() + 120_000) throw new Error('The gateway returned an invalid or expired owner challenge.');
  if (challenge.action !== selectedPolicy.action || passport.owner !== selectedPolicy.owner
      || passport.agent_pubkey !== selectedPolicy.agent_pubkey || passport.program_id !== APERTURE_PROGRAM_ID
      || passport.network !== expectedNetwork) throw new Error('The returned passport belongs to a different owner, agent, program or network.');
  if (['name', 'max_cost_lamports', 'max_runtime_seconds', 'total_budget_lamports', 'expires_at'].some(key => passport[key] !== selectedPolicy[key])
      || !Array.isArray(passport.capabilities) || passport.capabilities.length !== 1 || passport.capabilities[0] !== 'python.execute'
      || !Number.isSafeInteger(passport.version) || passport.version < 1) throw new Error('The returned delegation limits differ from your selected policy.');
  const { metadata_hash: metadataHash, ...metadata } = passport;
  if (await sha256Hex(canonicalJson(metadata)) !== metadataHash) throw new Error('The passport metadata hash does not match its policy.');
  const expectedMessage = 'Aperture agent delegation v1\naudience:aperture-gateway\n' + canonicalJson({
    action: challenge.action, passport, nonce: challenge.nonce, challenge_expires_at: challenge.expires_at,
  });
  if (challenge.message !== expectedMessage) throw new Error('The owner signature request is not the canonical passport policy.');
}

export default function Agents() {
  const { publicKey, signMessage, sendTransaction } = useWallet();
  const { connection } = useConnection();
  const { setVisible } = useWalletModal();
  const owner = publicKey?.toBase58();
  const [agents, setAgents] = useState([]);
  const [form, setForm] = useState(defaults);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const refresh = useCallback(async () => {
    if (!owner) { setAgents([]); return; }
    setLoading(true);
    try {
      const { data } = await axios.get(API_URL + '/agents', { params: { owner }, timeout: 10000 });
      setAgents(Array.isArray(data) ? data : []);
    } catch (error) { setNotice('Cannot load agent passports: ' + errorText(error)); }
    finally { setLoading(false); }
  }, [owner]);
  useEffect(() => { refresh(); setEditing(false); setForm(defaults()); }, [refresh]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(timer); }, []);
  const updateField = event => setForm(previous => ({ ...previous, [event.target.name]: event.target.value }));
  const authorize = async (action, source = form) => {
    if (!publicKey) { setVisible(true); return; }
    if (!signMessage) { setNotice('Choose a wallet that supports message signing.'); return; }
    setBusy(true); setNotice('');
    try {
      const agent = new PublicKey(source.agent_pubkey).toBase58();
      if (agent === owner) throw new Error('Use a separate agent public key. Your connected wallet is the owner.');
      const policy = {
        action, owner, agent_pubkey: agent, name: source.name.trim(),
        max_cost_lamports: lamports(source.maxCost), max_runtime_seconds: Number(source.maxRuntime),
        total_budget_lamports: lamports(source.totalBudget),
        expires_at: Math.floor(new Date(source.expires).getTime() / 1000), capabilities: ['python.execute'],
      };
      if (!policy.name || !Number.isInteger(policy.max_runtime_seconds) || policy.max_runtime_seconds < 1 || policy.max_runtime_seconds > 180) throw new Error('Name and a whole runtime from 1 to 180 seconds are required.');
      if (policy.total_budget_lamports < policy.max_cost_lamports) throw new Error('Total allowance must cover at least one maximum-cost task.');
      if (!Number.isFinite(policy.expires_at) || policy.expires_at <= Date.now() / 1000) throw new Error('Choose a future expiration.');
      const { data: health } = await axios.get(API_URL + '/health', { timeout: 10000 });
      const expectedNetwork = health.demo_mode ? 'off_chain' : 'devnet';
      const { data: challenge } = await axios.post(API_URL + '/agents/challenge', policy, { timeout: 15000 });
      await verifyAgentChallenge(challenge, policy, expectedNetwork);
      if (expectedNetwork === 'off_chain' && challenge.chain_instruction) throw new Error('An off-chain passport unexpectedly includes a chain transaction.');
      if (expectedNetwork === 'devnet' && !challenge.chain_instruction && challenge.chain_already_matches !== true) throw new Error('The gateway did not provide a matching Devnet instruction or confirm the existing passport.');
      // Sign the exact canonical owner policy before broadcasting a chain action.
      const signature = await signMessage(new TextEncoder().encode(challenge.message));
      let transactionSignature = null;
      if (challenge.chain_instruction) {
        if (!sendTransaction) throw new Error('This wallet cannot send the required Devnet transaction.');
        const instruction = challenge.chain_instruction;
        if (!['register', 'update', 'revoke'].includes(instruction.kind)
            || (instruction.kind !== action && !(action === 'register' && instruction.kind === 'update'))
            || instruction.program_id !== APERTURE_PROGRAM_ID) throw new Error('Delegation instruction does not match the pinned Devnet program and action.');
        const expectedData = await agentInstructionData(instruction.kind, challenge.passport);
        const expectedAccounts = expectedAgentAccounts(instruction.kind, owner, agent);
        if (!Array.isArray(instruction.data) || instruction.data.some(byte => !Number.isInteger(byte) || byte < 0 || byte > 255)
            || !bytesEqual(instruction.data, expectedData)
            || typeof instruction.data_base64 !== 'string'
            || !bytesEqual(decodeBase64(instruction.data_base64), expectedData)) throw new Error('Delegation instruction data does not match the signed passport policy.');
        if (!Array.isArray(instruction.accounts) || instruction.accounts.length !== expectedAccounts.length
            || instruction.accounts.some((account, index) => account.pubkey !== expectedAccounts[index].pubkey
              || account.is_signer !== expectedAccounts[index].is_signer
              || account.is_writable !== expectedAccounts[index].is_writable)) throw new Error('Delegation instruction accounts do not match the locally derived owner and passport.');
        const transaction = new Transaction().add(new TransactionInstruction({
          programId: new PublicKey(APERTURE_PROGRAM_ID), data: expectedData,
          keys: expectedAccounts.map(account => ({ pubkey: new PublicKey(account.pubkey), isSigner: account.is_signer, isWritable: account.is_writable })),
        }));
        const latest = await connection.getLatestBlockhash('confirmed');
        transaction.feePayer = publicKey; transaction.recentBlockhash = latest.blockhash;
        transactionSignature = await sendTransaction(transaction, connection);
        const result = await connection.confirmTransaction({ ...latest, signature: transactionSignature }, 'confirmed');
        if (result.value.err) throw new Error('Devnet transaction did not succeed.');
      }
      const { data } = await axios.post(API_URL + '/agents', { nonce: challenge.nonce, message: challenge.message, signature: Array.from(signature) }, { timeout: 15000 });
      setNotice((action === 'revoke' ? 'Agent revoked.' : 'Agent policy saved.') + ' ' + (data.attestation === 'SOLANA_DEVNET' ? 'Confirmed on Solana Devnet.' : 'Owner-signed off-chain development policy; no chain transaction.') + (transactionSignature ? ' Transaction: ' + transactionSignature : ''));
      setEditing(false); setForm(defaults()); await refresh();
    } catch (error) { setNotice(errorText(error) || 'Owner authorization was declined.'); }
    finally { setBusy(false); }
  };
  const fieldsFrom = agent => ({
    agent_pubkey: agent.agent_pubkey, name: agent.name,
    maxCost: String(agent.max_cost_lamports / 1e9), maxRuntime: String(agent.max_runtime_seconds),
    totalBudget: String(agent.total_budget_lamports / 1e9),
    expires: localDate(Math.max(agent.expires_at * 1000, now + 3600000)),
  });

  return <div className="agents-page">
    <section className="console-panel agents-intro"><span className="console-eyebrow">KNOW YOUR AGENT</span><h2>Give each agent a clear identity and a spending boundary.</h2><p>Your wallet issues a passport to an agent public key. You control its task budget, runtime, total allowance and expiration. Revocation stops its authorization. This is owner-issued delegation, with no legal identity or KYC claim.</p><p>Generate and keep the agent private key in your SDK environment. This page only accepts its public key.</p></section>
    {notice && <div className="studio-notice" role="status"><Icon name="shield" size={18} /><p>{notice}</p></div>}
    <div className="agents-grid">
      <section className="console-panel agents-form"><div className="console-section-heading"><h2>{editing ? 'Update passport' : 'Issue a passport'}</h2><Icon name="shield" /></div>
        {!owner ? <><p>Connect the owner wallet to issue and manage agent passports.</p><button className="console-button primary" onClick={() => setVisible(true)}>Connect owner wallet</button></> : <form onSubmit={event => { event.preventDefault(); authorize(editing ? 'update' : 'register'); }}>
          <p className="agents-owner">Owner · {owner}</p>
          <label>Agent public key<input name="agent_pubkey" value={form.agent_pubkey} onChange={updateField} disabled={busy || editing} placeholder="Solana / Ed25519 public key" required autoComplete="off" /></label>
          <label>Name<input name="name" value={form.name} onChange={updateField} disabled={busy} maxLength={80} required /></label>
          <div className="agents-fields"><label>Max cost per task · SOL<input name="maxCost" type="number" min="0.000000001" max="1" step="0.000001" value={form.maxCost} onChange={updateField} disabled={busy} required /></label><label>Max runtime · seconds<input name="maxRuntime" type="number" min="1" max="180" step="1" value={form.maxRuntime} onChange={updateField} disabled={busy} required /></label></div>
          <label>Total spending allowance · SOL<input name="totalBudget" type="number" min="0.000000001" max="100" step="0.001" value={form.totalBudget} onChange={updateField} disabled={busy} required /></label>
          <label>Expiration · your local time<input name="expires" type="datetime-local" value={form.expires} onChange={updateField} disabled={busy} required /></label>
          <p>Capability: Python CPU execution. Devnet mode also asks your wallet to confirm an on-chain policy transaction.</p>
          <button className="console-button primary" disabled={busy} aria-busy={busy}><Icon name={busy ? 'refresh' : 'shield'} size={17} />{busy ? 'Authorizing…' : editing ? 'Sign policy update' : 'Sign & issue passport'}</button>
          {editing && <button className="console-text-button" type="button" disabled={busy} onClick={() => { setEditing(false); setForm(defaults()); }}>Cancel update</button>}
        </form>}
      </section>
      <section className="console-panel agents-list"><div className="console-section-heading"><div><h2>Your agents</h2><p>Passports issued by the connected owner wallet.</p></div><button className="console-text-button" onClick={refresh} disabled={loading || busy || !owner} aria-busy={loading}><Icon name="refresh" size={17} />Refresh</button></div>
        {!agents.length ? <div className="console-empty"><Icon name="shield" size={32} /><h3>{loading ? 'Loading passports…' : 'No passports yet'}</h3><p>Issue one to enable an SDK agent to submit budgeted tasks.</p></div> : agents.map(agent => {
          const expired = agent.expires_at * 1000 <= now;
          return <article key={agent.agent_pubkey} className="agent-passport"><div className="console-section-heading"><h3>{agent.name}</h3><span className={'console-tag ' + (agent.revoked || expired ? 'error' : '')}>{agent.revoked ? 'Revoked' : expired ? 'Expired' : 'Active'}</span></div><code>{agent.agent_pubkey}</code><dl><div><dt>Per-task cost</dt><dd>{agent.max_cost_lamports / 1e9} SOL</dd></div><div><dt>Runtime</dt><dd>{agent.max_runtime_seconds}s</dd></div><div><dt>Total allowance</dt><dd>{agent.total_budget_lamports / 1e9} SOL</dd></div><div><dt>Expires</dt><dd>{new Date(agent.expires_at * 1000).toLocaleString()}</dd></div><div><dt>Evidence</dt><dd>{agent.attestation === 'SOLANA_DEVNET' ? 'Solana Devnet' : 'Owner-signed off-chain'}</dd></div><div><dt>Policy version</dt><dd>{agent.version}</dd></div></dl><div className="agents-actions"><button className="console-text-button" disabled={busy} onClick={() => { setForm(fieldsFrom(agent)); setEditing(true); }}>Update limits<Icon name="arrow" size={15} /></button>{!agent.revoked && <button className="console-text-button" disabled={busy} onClick={() => authorize('revoke', fieldsFrom(agent))}>Revoke agent<Icon name="stop" size={15} /></button>}</div></article>;
        })}
      </section>
    </div>
  </div>;
}
