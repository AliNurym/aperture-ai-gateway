import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useConnection, useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import { PublicKey, SystemProgram, Transaction, TransactionInstruction } from '@solana/web3.js';
import Icon from './components/Icon';
import { APERTURE_PROGRAM_ID, agentInstructionData, canonicalJson, sha256Hex, verifyAgentPassport } from './utils/protocol';
import { requestErrorMessage as errorText } from './utils/requestError';
import './Agents.css';

const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const localDate = value => new Date(value - new Date(value).getTimezoneOffset() * 60000).toISOString().slice(0, 16);
const defaults = () => ({ agent_pubkey: '', name: 'Research agent', maxCost: '0.001', maxRuntime: '30', totalBudget: '0.01', expires: localDate(Date.now() + 7 * 86400000) });
const formatSol = value => (value / 1e9).toFixed(9).replace(/\.?0+$/, '');
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
  const { publicKey, signMessage, sendTransaction, wallet, connect, connecting } = useWallet();
  const { connection } = useConnection();
  const { setVisible } = useWalletModal();
  const owner = publicKey?.toBase58();
  const [agents, setAgents] = useState([]);
  const [form, setForm] = useState(defaults);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const readSequence = useRef(0);
  const currentOwner = useRef(owner);
  const refresh = useCallback(async () => {
    if (!owner) { setAgents([]); setLoaded(false); return; }
    const requestId = ++readSequence.current;
    setLoading(true);
    setNotice('');
    try {
      if (!signMessage) throw new Error('Choose a wallet that supports message signing to view your passports.');
      const issuedAt = Math.floor(Date.now() / 1000);
      const nonce = crypto.randomUUID();
      const message = 'Aperture agent allowance read v1\naudience:aperture-gateway\n' + canonicalJson({ owner, issued_at: issuedAt, nonce });
      const signature = await signMessage(new TextEncoder().encode(message));
      if (readSequence.current !== requestId) return;
      const { data } = await axios.post(API_URL + '/agents/usage', {
        owner, issued_at: issuedAt, nonce, signature: Array.from(signature),
      }, { timeout: 15000 });
      if (readSequence.current !== requestId) return;
      if (!Array.isArray(data)) throw new Error('Gateway returned an invalid passport list.');
      for (const passport of data) {
        const verification = await verifyAgentPassport(passport, owner);
        if (!verification.verified) throw new Error(verification.reason);
      }
      if (readSequence.current !== requestId) return;
      setAgents(data);
      setLoaded(true);
    } catch (error) {
      if (readSequence.current !== requestId) return;
      setAgents(current => current.map(agent => ({
        ...agent, allowance_status: 'unavailable', spent_lamports: null,
        reserved_lamports: null, remaining_lamports: null,
      })));
      setNotice('Cannot load agent passports: ' + errorText(error));
    }
    finally { if (readSequence.current === requestId) setLoading(false); }
  }, [owner, signMessage]);
  const upsertPassport = passport => {
    if (currentOwner.current !== passport.owner || !loaded) return;
    const item = {
      ...passport, allowance_status: 'requires_signature', allowance_source: null,
      spent_lamports: null, reserved_lamports: null, remaining_lamports: null,
    };
    setAgents(current => current.some(existing => existing.agent_pubkey === item.agent_pubkey)
      ? current.map(existing => existing.agent_pubkey === item.agent_pubkey ? item : existing)
      : [...current, item]);
  };
  useEffect(() => {
    currentOwner.current = owner;
    readSequence.current += 1;
    setAgents([]); setLoaded(false); setEditing(false); setForm(defaults()); setNotice('');
  }, [owner]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(timer); }, []);
  const updateField = event => setForm(previous => ({ ...previous, [event.target.name]: event.target.value }));
  const connectWallet = async () => {
    if (!wallet) { setVisible(true); return; }
    try { await connect(); }
    catch (error) { setNotice('Wallet connection failed: ' + errorText(error)); }
  };
  const authorize = async (action, source = form) => {
    if (!publicKey) { await connectWallet(); return; }
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
      if (currentOwner.current !== owner) throw new Error('The connected owner wallet changed. Retry with the intended wallet.');
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
      if (currentOwner.current !== owner) return;
      const passportVerification = await verifyAgentPassport(data, owner, false);
      if (!passportVerification.verified) throw new Error(passportVerification.reason);
      setNotice((action === 'revoke' ? 'Agent revoked.' : 'Agent policy saved.') + ' ' + (data.attestation === 'SOLANA_DEVNET' ? 'Confirmed on Solana Devnet.' : 'Owner-signed off-chain development policy; no chain transaction.') + (transactionSignature ? ' Transaction: ' + transactionSignature : '') + (!loaded ? ' Sign to view your complete passport list.' : ''));
      upsertPassport(data); setEditing(false); setForm(defaults());
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
    <section className={'console-panel agents-intro ' + (!owner ? 'agents-onboarding' : '')}>
      <div className="agents-intro-heading">
        <div className="agents-connect-icon"><Icon name="shield" size={25} /></div>
        <div>
          <h2>Keep each agent within its limits.</h2>
          <p>Issue a passport with a task budget, runtime limit and total allowance. Your wallet stays in control.</p>
        </div>
        {!owner && <button className="console-button primary" disabled={connecting} onClick={connectWallet}><Icon name="wallet" size={18} />{connecting ? 'Connecting…' : 'Connect owner wallet'}</button>}
      </div>
      {!owner && <dl className="agents-boundaries">
        <div><dt>Spending</dt><dd>Per-task cap and total allowance</dd></div>
        <div><dt>Runtime</dt><dd>A time limit for every workload</dd></div>
        <div><dt>Access</dt><dd>Expiration and owner revocation</dd></div>
      </dl>}
      <details className="agents-help agents-intro-help">
        <summary>How passports work</summary>
        <p>Your wallet delegates Python CPU execution to an agent public key. A passport records its task budget, runtime and total allowance. This is owner-issued permission, with no legal identity or KYC claim.</p>
        <p>Generate and keep the agent private key in your SDK environment. This page only accepts its public key.</p>
      </details>
    </section>
    {notice && <div className="studio-notice" role="status"><Icon name="shield" size={18} /><p>{notice}</p></div>}
    {owner && <div className="agents-grid">
      <section className="console-panel agents-form"><div className="console-section-heading"><h2>{editing ? 'Update passport' : 'Issue a passport'}</h2><Icon name="shield" /></div>
        <form onSubmit={event => { event.preventDefault(); authorize(editing ? 'update' : 'register'); }}>
          <p className="agents-owner" title={owner}>Owner · {owner.slice(0, 8)}…{owner.slice(-8)}</p>
          <label>Agent public key<input name="agent_pubkey" value={form.agent_pubkey} onChange={updateField} disabled={busy || editing} placeholder="Solana / Ed25519 public key" required autoComplete="off" aria-describedby="agent-key-help" /></label>
          <p id="agent-key-help" className="agents-field-help">Keep the private key in your SDK environment.</p>
          <label>Name<input name="name" value={form.name} onChange={updateField} disabled={busy} maxLength={80} required /></label>
          <div className="agents-fields"><label>Max cost per task · SOL<input name="maxCost" type="number" min="0.000000001" max="1" step="0.000001" value={form.maxCost} onChange={updateField} disabled={busy} required /></label><label>Max runtime · seconds<input name="maxRuntime" type="number" min="1" max="180" step="1" value={form.maxRuntime} onChange={updateField} disabled={busy} required /></label></div>
          <label>Total spending allowance · SOL<input name="totalBudget" type="number" min="0.000000001" max="100" step="0.001" value={form.totalBudget} onChange={updateField} disabled={busy} required /></label>
          <label>Expiration · your local time<input name="expires" type="datetime-local" value={form.expires} onChange={updateField} disabled={busy} required /></label>
          <p className="agents-signing-note">Allows Python CPU execution. In Devnet mode, your wallet also confirms an on-chain policy transaction.</p>
          <button className="console-button primary" disabled={busy} aria-busy={busy}><Icon name={busy ? 'refresh' : 'shield'} size={17} />{busy ? 'Authorizing…' : editing ? 'Sign policy update' : 'Sign & issue passport'}</button>
          {editing && <button className="console-text-button" type="button" disabled={busy} onClick={() => { setEditing(false); setForm(defaults()); }}>Cancel update</button>}
        </form>
      </section>
      <section className="console-panel agents-list"><div className="console-section-heading"><h2>Your agents{agents.length > 0 && <span className="agents-count">{agents.length}</span>}</h2><button className="console-text-button" onClick={refresh} disabled={loading || busy || !signMessage} aria-busy={loading}><Icon name="refresh" size={17} />{loaded ? 'Sign & refresh' : 'Sign to view'}</button></div>
        {!agents.length ? <div className="console-empty agents-empty"><Icon name="shield" size={28} /><h3>{loading ? 'Loading passports…' : loaded ? 'No passports yet' : 'Passports are private'}</h3><p>{loading ? 'Waiting for the owner wallet…' : loaded ? 'Your agents will appear here once you issue a passport.' : 'Sign with the connected owner wallet to view passports and allowance usage.'}</p></div> : agents.map(agent => {
          const expired = agent.expires_at * 1000 <= now;
          return <article key={agent.agent_pubkey} className="agent-passport">
            <div className="console-section-heading"><h3>{agent.name}</h3><span className={'console-tag ' + (agent.revoked || expired ? 'error' : '')}>{agent.revoked ? 'Revoked' : expired ? 'Expired' : 'Active'}</span></div>
            <p className="agent-attestation"><code title={agent.agent_pubkey}>{agent.agent_pubkey.slice(0, 6)}…{agent.agent_pubkey.slice(-6)}</code><span>{agent.attestation === 'SOLANA_DEVNET' ? 'Solana Devnet' : 'Owner-signed off-chain'}</span></p>
            <dl>
              <div><dt>Cost per task</dt><dd>{agent.max_cost_lamports / 1e9} SOL</dd></div>
              <div><dt>Runtime</dt><dd>{agent.max_runtime_seconds}s</dd></div>
              <div><dt>Total allowance</dt><dd>{formatSol(agent.total_budget_lamports)} SOL</dd></div>
              <div><dt>Spent</dt><dd>{agent.allowance_status === 'available' ? `${formatSol(agent.spent_lamports)} SOL` : agent.allowance_status === 'requires_signature' ? 'Sign to load' : 'Unavailable'}</dd></div>
              <div><dt>Reserved by active tasks</dt><dd>{agent.allowance_status === 'available' ? `${formatSol(agent.reserved_lamports)} SOL` : agent.allowance_status === 'requires_signature' ? 'Sign to load' : 'Unavailable'}</dd></div>
              <div className="agent-remaining"><dt>Remaining</dt><dd>{agent.allowance_status === 'available' ? `${formatSol(agent.remaining_lamports)} SOL` : agent.allowance_status === 'requires_signature' ? 'Sign to load' : 'Unavailable'}</dd></div>
              <div><dt>Expires</dt><dd>{new Date(agent.expires_at * 1000).toLocaleString()}</dd></div>
            </dl>
            <p className="agent-allowance-source" role="status">{agent.allowance_status === 'available'
              ? `Usage source: ${agent.allowance_source === 'solana_devnet' ? 'Solana Devnet' : 'gateway ledger'}.`
              : agent.allowance_status === 'requires_signature'
                ? 'Sign with the connected owner wallet to load private usage data.'
                : 'Usage is unavailable from the configured source. Sign and refresh to try again.'}</p>
            <details className="agents-help agent-details"><summary>Passport details</summary><dl><div><dt>Public key</dt><dd><code>{agent.agent_pubkey}</code></dd></div><div><dt>Policy version</dt><dd>{agent.version}</dd></div></dl></details>
            <div className="agents-actions">
              <button className="console-text-button" disabled={busy} onClick={() => { setForm(fieldsFrom(agent)); setEditing(true); }}>Update limits</button>
              {!agent.revoked && <button className="console-text-button agent-revoke" disabled={busy} onClick={() => authorize('revoke', fieldsFrom(agent))}>Revoke access</button>}
            </div>
          </article>;
        })}
      </section>
    </div>}
  </div>;
}
