import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import {
  Connection, Keypair, PublicKey, sendAndConfirmTransaction,
  SystemProgram, Transaction, TransactionInstruction,
} from '@solana/web3.js';

const url = 'http://127.0.0.1:8899';
const project = process.cwd();
const programId = new PublicKey('A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ');
const authority = Keypair.fromSeed(new Uint8Array(32).fill(7));
const owner = Keypair.fromSeed(new Uint8Array(32).fill(8));
const agent = Keypair.fromSeed(new Uint8Array(32).fill(9));
const treasury = Keypair.fromSeed(new Uint8Array(32).fill(10));
const wrongOracle = Keypair.fromSeed(new Uint8Array(32).fill(11));
const system = SystemProgram.programId;
const discriminator = name => createHash('sha256').update(name).digest().subarray(0, 8);
const hash = value => createHash('sha256').update(value).digest();
const u32 = value => { const b = Buffer.alloc(4); b.writeUInt32LE(value); return b; };
const u64 = value => { const b = Buffer.alloc(8); b.writeBigUInt64LE(BigInt(value)); return b; };
const i64 = value => { const b = Buffer.alloc(8); b.writeBigInt64LE(BigInt(value)); return b; };
const seeds = (name, ...parts) => PublicKey.findProgramAddressSync([Buffer.from(name), ...parts], programId)[0];
const config = seeds('config');
const channel = seeds('channel', owner.publicKey.toBuffer());
const passport = seeds('agent', agent.publicKey.toBuffer());
const send = async (ix, signers) => sendAndConfirmTransaction(connection, new Transaction().add(ix), signers, { commitment: 'confirmed' });
const ix = (name, data, keys) => new TransactionInstruction({
  programId, data: Buffer.concat([discriminator('global:' + name), ...data]),
  keys: keys.map(([pubkey, isSigner = false, isWritable = false]) => ({ pubkey, isSigner, isWritable })),
});
const requireKeys = (accounts, name) => {
  for (const [pubkey, signer = false, writable = false] of accounts) {
    assert(pubkey instanceof PublicKey);
    assert.equal(typeof signer, 'boolean', name);
    assert.equal(typeof writable, 'boolean', name);
  }
  return accounts.map(([pubkey, signer = false, writable = false]) => [pubkey, signer, writable]);
};
const expectRejected = async (promise, label) => {
  let failed = false;
  try { await promise; } catch { failed = true; }
  assert(failed, label + ' unexpectedly succeeded');
};

const ledger = await mkdtemp(join(tmpdir(), 'aperture-v2-ledger-'));
const validator = spawn('solana-test-validator', [
  '--reset', '--quiet', '--ledger', ledger, '--rpc-port', '8899', '--bind-address', '127.0.0.1',
  '--bpf-program', programId.toBase58(), join(project, 'target', 'deploy', 'aperture_gateway.so'),
], { stdio: ['ignore', 'pipe', 'pipe'] });
let validatorOutput = '';
validator.stdout.on('data', chunk => { validatorOutput = (validatorOutput + chunk.toString()).slice(-4000); });
validator.stderr.on('data', chunk => { validatorOutput = (validatorOutput + chunk.toString()).slice(-4000); });
let connection;

try {
  connection = new Connection(url, 'confirmed');
  let ready = false;
  let lastRpcError;
  for (let attempt = 0; attempt < 90; attempt++) {
    if (validator.exitCode !== null) throw new Error('Local validator exited: ' + validatorOutput);
    try {
      if (await connection.getSlot('processed') > 0) { ready = true; break; }
    } catch (error) {
      lastRpcError = error;
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  assert(ready, `Local validator failed to start: ${validatorOutput}; RPC: ${lastRpcError?.message ?? 'no slot produced'}`);

  async function airdrop(keypair, sol = 2) {
    const signature = await connection.requestAirdrop(keypair.publicKey, sol * 1_000_000_000);
    const latest = await connection.getLatestBlockhash('confirmed');
    await connection.confirmTransaction({ signature, ...latest }, 'confirmed');
  }
  for (const key of [authority, owner, wrongOracle]) await airdrop(key);

  const initialize = ix('initialize_config', [treasury.publicKey.toBuffer()], requireKeys([
    [config, false, true], [authority.publicKey, true, true], [system],
  ], 'initialize'));
  await expectRejected(send(initialize, [wrongOracle]), 'non-pinned config authority');
  await send(initialize, [authority]);

  const configAccount = await connection.getAccountInfo(config);
  assert(configAccount);
  assert.equal(configAccount.owner.toBase58(), programId.toBase58());
  assert.equal(configAccount.data.length, 107);
  assert.deepEqual(configAccount.data.subarray(40, 72), authority.publicKey.toBuffer());
  assert.deepEqual(configAccount.data.subarray(72, 104), treasury.publicKey.toBuffer());
  assert.equal(configAccount.data.readUInt16LE(105), 2);

  const passportHash = hash('owner policy version 1');
  const future = Math.floor(Date.now() / 1000) + 3600;
  await send(ix('register_agent', [passportHash, u64(500_000), u32(30), i64(future), u64(1_000_000)], [
    [passport, false, true], [owner.publicKey, true, true], [agent.publicKey], [system],
  ]), [owner]);
  await send(ix('open_channel', [u64(4_000_000)], [
    [config], [channel, false, true], [owner.publicKey, true, true], [system],
  ]), [owner]);

  const taskHash = hash('delegated task one');
  const sourceHash = hash('print deterministic test');
  const receipt = seeds('task', taskHash);
  const startAccounts = oracle => [
    [config], [channel, false, true], [oracle, true, true], [treasury.publicKey, false, true],
    [passport, false, true], [receipt, false, true], [system],
  ];
  const startData = [taskHash, sourceHash, agent.publicKey.toBuffer(), u64(10_000), u64(100_000), u32(20)];
  await expectRejected(send(ix('start_task', startData, startAccounts(wrongOracle.publicKey)), [wrongOracle]), 'wrong oracle start');
  await expectRejected(send(ix('start_task', [
    taskHash, sourceHash, agent.publicKey.toBuffer(), u64(25_001), u64(100_000), u32(20),
  ], startAccounts(authority.publicKey)), [authority]), 'rate above program maximum');
  await expectRejected(send(ix('start_task', [
    taskHash, sourceHash, agent.publicKey.toBuffer(), u64(10_000), u64(500_001), u32(20),
  ], startAccounts(authority.publicKey)), [authority]), 'cost above passport maximum');
  await send(ix('start_task', startData, startAccounts(authority.publicKey)), [authority]);

  let channelAccount = await connection.getAccountInfo(channel);
  let passportAccount = await connection.getAccountInfo(passport);
  let receiptAccount = await connection.getAccountInfo(receipt);
  assert.equal(channelAccount.data.length, 225);
  assert.equal(passportAccount.data.length, 158);
  assert.equal(receiptAccount.data.length, 186);
  assert.equal(channelAccount.data.readBigUInt64LE(80), 10_000n);
  assert.equal(passportAccount.data.readBigUInt64LE(140), 100_000n);
  assert.equal(receiptAccount.data[184], 0);

  await new Promise(resolve => setTimeout(resolve, 1100));
  const stop = ix('stop_task', [taskHash], [
    [config], [channel, false, true], [authority.publicKey, true], [treasury.publicKey, false, true],
    [passport, false, true], [receipt, false, true],
  ]);
  await send(stop, [authority]);
  receiptAccount = await connection.getAccountInfo(receipt);
  channelAccount = await connection.getAccountInfo(channel);
  passportAccount = await connection.getAccountInfo(passport);
  const charged = receiptAccount.data.readBigUInt64LE(176);
  assert.equal(receiptAccount.data[184], 1);
  assert(charged > 0n && charged <= 100_000n);
  assert.equal(channelAccount.data.readBigUInt64LE(80), 0n);
  assert.equal(channelAccount.data.readBigUInt64LE(217), charged);
  assert.equal(passportAccount.data.readBigUInt64LE(140), 0n);
  assert.equal(passportAccount.data.readBigUInt64LE(132), charged);

  const balanceAfterSettlement = channelAccount.data.readBigUInt64LE(72);
  await send(stop, [authority]);
  channelAccount = await connection.getAccountInfo(channel);
  assert.equal(channelAccount.data.readBigUInt64LE(72), balanceAfterSettlement, 'duplicate settlement charged again');
  await expectRejected(send(ix('start_task', startData, startAccounts(authority.publicKey)), [authority]), 'task-hash replay');

  await send(ix('revoke_agent', [], [[passport, false, true], [owner.publicKey, true]]), [owner]);
  const revokedTask = hash('revoked task');
  await expectRejected(send(ix('start_task', [
    revokedTask, sourceHash, agent.publicKey.toBuffer(), u64(10_000), u64(100_000), u32(20),
  ], [...startAccounts(authority.publicKey).slice(0, 4), [passport, false, true], [seeds('task', revokedTask), false, true], [system]]), [authority]), 'revoked agent');

  const ownerTaskHash = hash('owner closes active channel');
  const ownerReceipt = seeds('task', ownerTaskHash);
  await send(ix('start_task', [
    ownerTaskHash, sourceHash, owner.publicKey.toBuffer(), u64(10_000), u64(100_000), u32(20),
  ], [
    [config], [channel, false, true], [authority.publicKey, true, true], [treasury.publicKey, false, true],
    [programId], [ownerReceipt, false, true], [system],
  ]), [authority]);
  await send(ix('close_channel', [], [
    [config], [channel, false, true], [owner.publicKey, true, true], [treasury.publicKey, false, true],
    [programId], [ownerReceipt, false, true],
  ]), [owner]);
  assert.equal(await connection.getAccountInfo(channel), null);
  const closedReceipt = await connection.getAccountInfo(ownerReceipt);
  assert(closedReceipt, 'task receipt was closed together with the channel');
  assert.equal(closedReceipt.data[184], 1);
  assert(closedReceipt.data.readBigUInt64LE(176) <= 100_000n);

  console.log(JSON.stringify({
    program_id: programId.toBase58(), initialized_version: 2,
    delegated_task_charge_lamports: charged.toString(),
    checks: ['pinned config authority', 'register/open/start/stop', 'wrong oracle rejection',
      'rate and passport caps', 'replay rejection', 'duplicate settlement', 'revocation admission',
      'owner close with persistent settled receipt'],
  }, null, 2));
} finally {
  validator.kill('SIGTERM');
  await new Promise(resolve => {
    if (validator.exitCode !== null) resolve();
    else { validator.once('exit', resolve); setTimeout(() => { validator.kill('SIGKILL'); resolve(); }, 5000).unref(); }
  });
  await rm(ledger, { recursive: true, force: true });
}
