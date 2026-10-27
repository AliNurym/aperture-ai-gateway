import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve, sep } from 'node:path';
import { spawn } from 'node:child_process';
import {
  Connection, Keypair, PublicKey, SystemProgram, Transaction, TransactionInstruction,
} from '@solana/web3.js';

const project = process.cwd();
const tempBase = resolve(project, '.aperture');
await mkdir(tempBase, { recursive: true });
const tempRoot = await mkdtemp(join(tempBase, 'legacy-recovery-'));
const ledger = join(tempRoot, 'ledger');
const programSo = resolve(project, process.env.APERTURE_TEST_PROGRAM_SO || 'target/deploy/aperture_gateway.so');
const programId = new PublicKey('A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ');
const authority = Keypair.fromSeed(new Uint8Array(32).fill(7));
const owner = Keypair.fromSeed(new Uint8Array(32).fill(17));
const treasury = Keypair.fromSeed(new Uint8Array(32).fill(18));
const oracle = Keypair.fromSeed(new Uint8Array(32).fill(19));
const worker = Keypair.fromSeed(new Uint8Array(32).fill(20));
const url = 'http://127.0.0.1:8899';
const hash = value => createHash('sha256').update(value).digest();
const accountDiscriminator = name => hash(`account:${name}`).subarray(0, 8);
const instructionDiscriminator = name => hash(`global:${name}`).subarray(0, 8);
const seeds = (name, ...parts) => PublicKey.findProgramAddressSync([Buffer.from(name), ...parts], programId);
const putKey = (data, offset, key) => Buffer.from(key.toBuffer?.() ?? key).copy(data, offset);
const putU64 = (data, offset, value) => data.writeBigUInt64LE(BigInt(value), offset);
const putI64 = (data, offset, value) => data.writeBigInt64LE(BigInt(value), offset);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

await mkdir(ledger);
const configFile = join(tempRoot, 'cli-config.yml');
await writeFile(configFile, [
  'json_rpc_url: http://127.0.0.1:8899',
  'websocket_url: ws://127.0.0.1:8900',
  'keypair_path: ""',
  '',
].join('\n'), { flag: 'wx' });

const [config, configBump] = seeds('config');
const [channel, channelBump] = seeds('channel', owner.publicKey.toBuffer());
const taskHash = hash('pre-worker-pinning active task recovery');
const [receipt, receiptBump] = seeds('task', taskHash);
const startedAt = Math.floor(Date.now() / 1000) - 5;
const deadline = startedAt + 600;
const chargeRate = 100;
const maxCost = 60_000;
const balance = 1_000_000;

const configData = Buffer.alloc(8 + 32 * 3 + 1 + 2);
accountDiscriminator('ProtocolConfig').copy(configData, 0);
putKey(configData, 8, authority.publicKey);
putKey(configData, 40, oracle.publicKey);
putKey(configData, 72, treasury.publicKey);
configData.writeUInt8(configBump, 104);
configData.writeUInt16LE(2, 105);

// Simulates the pre-pinning bounded-task state: last_charged is an ordinary
// previous charge, not the WORKER_PAYOUT_BOUND marker used by new tasks.
const channelData = Buffer.alloc(225);
accountDiscriminator('ChannelState').copy(channelData, 0);
putKey(channelData, 8, owner.publicKey);
putKey(channelData, 40, oracle.publicKey);
putU64(channelData, 72, balance);
putU64(channelData, 80, chargeRate);
putI64(channelData, 88, startedAt - 1);
channelData.writeUInt8(channelBump, 96);
putKey(channelData, 97, owner.publicKey);
putKey(channelData, 129, taskHash);
putU64(channelData, 161, maxCost);
putI64(channelData, 169, deadline);
putI64(channelData, 177, startedAt);
putKey(channelData, 185, new Uint8Array(32));
putU64(channelData, 217, 0);

const receiptData = Buffer.alloc(186);
accountDiscriminator('TaskReceipt').copy(receiptData, 0);
putKey(receiptData, 8, owner.publicKey);
putKey(receiptData, 40, owner.publicKey);
putKey(receiptData, 72, taskHash);
putKey(receiptData, 104, hash('legacy source bytes'));
putU64(receiptData, 136, chargeRate);
putU64(receiptData, 144, maxCost);
putI64(receiptData, 152, startedAt);
putI64(receiptData, 160, deadline);
putI64(receiptData, 168, 0);
putU64(receiptData, 176, 0);
receiptData.writeUInt8(0, 184);
receiptData.writeUInt8(receiptBump, 185);

const writeSeedAccount = async (name, address, data, ownerAddress, lamports) => {
  const file = join(tempRoot, `${name}.json`);
  await writeFile(file, JSON.stringify({
    lamports,
    data: [data.toString('base64'), 'base64'],
    owner: ownerAddress.toBase58(),
    executable: false,
    rentEpoch: 0,
    space: data.length,
  }), { flag: 'wx' });
  return [address.toBase58(), file];
};

const systemAccount = Buffer.alloc(0);
const seededAccounts = await Promise.all([
  writeSeedAccount('config', config, configData, programId, 1_000_000_000),
  writeSeedAccount('channel', channel, channelData, programId, 1_000_000_000),
  writeSeedAccount('receipt', receipt, receiptData, programId, 1_000_000_000),
  writeSeedAccount('owner', owner.publicKey, systemAccount, SystemProgram.programId, 1_000_000_000),
  writeSeedAccount('treasury', treasury.publicKey, systemAccount, SystemProgram.programId, 100_000),
  writeSeedAccount('worker', worker.publicKey, systemAccount, SystemProgram.programId, 100_000),
  writeSeedAccount('oracle', oracle.publicKey, systemAccount, SystemProgram.programId, 0),
]);

const args = [
  '--reset', '--log', '--config', configFile, '--ledger', ledger,
  '--rpc-port', '8899', '--bind-address', '127.0.0.1',
  '--bpf-program', programId.toBase58(), programSo,
];
for (const [address, file] of seededAccounts) args.push('--account', address, file);
const validator = spawn('solana-test-validator', args, { stdio: ['ignore', 'pipe', 'pipe'] });
let validatorOutput = '';
let spawnError;
validator.on('error', error => { spawnError = error; });
validator.stdout.on('data', chunk => { validatorOutput = (validatorOutput + chunk.toString()).slice(-5000); });
validator.stderr.on('data', chunk => { validatorOutput = (validatorOutput + chunk.toString()).slice(-5000); });

try {
  const connection = new Connection(url, 'processed');
  let ready = false;
  let lastRpcError;
  for (let attempt = 0; attempt < 90; attempt++) {
    if (spawnError) throw new Error(`Cannot start local validator: ${spawnError.message}`);
    if (validator.exitCode !== null) throw new Error(`Local validator exited: ${validatorOutput}`);
    try {
      if (await connection.getSlot('processed') > 0) { ready = true; break; }
    } catch (error) { lastRpcError = error; }
    await sleep(1000);
  }
  assert(ready, `Local validator did not become ready: ${lastRpcError?.message || validatorOutput}`);

  const preCloseChannel = await connection.getAccountInfo(channel, 'processed');
  const preCloseReceipt = await connection.getAccountInfo(receipt, 'processed');
  assert(preCloseChannel && preCloseReceipt, 'legacy channel and receipt were seeded');
  assert.equal(preCloseChannel.data.length, 225);
  assert.notEqual(preCloseChannel.data.readBigUInt64LE(217), (1n << 64n) - 1n,
    'fixture represents an unpinned pre-upgrade task');
  assert.equal(preCloseReceipt.data[184], 0, 'legacy task receipt starts unsettled');

  const treasuryBefore = await connection.getBalance(treasury.publicKey, 'processed');
  const workerBefore = await connection.getBalance(worker.publicKey, 'processed');
  const instruction = new TransactionInstruction({
    programId,
    data: Buffer.concat([instructionDiscriminator('close_channel')]),
    keys: [
      [config, false, false], [channel, false, true], [owner.publicKey, true, true],
      [treasury.publicKey, false, true], [worker.publicKey, false, true],
      [programId, false, false], [receipt, false, true],
    ].map(([pubkey, isSigner, isWritable]) => ({ pubkey, isSigner, isWritable })),
  });
  const latest = await connection.getLatestBlockhash('processed');
  const transaction = new Transaction({
    feePayer: owner.publicKey,
    blockhash: latest.blockhash,
    lastValidBlockHeight: latest.lastValidBlockHeight,
  }).add(instruction);
  transaction.sign(owner);
  const signature = await connection.sendRawTransaction(transaction.serialize(), {
    preflightCommitment: 'processed',
  });
  const waitDeadline = Date.now() + 30_000;
  while (Date.now() < waitDeadline) {
    const { value: [status] } = await connection.getSignatureStatuses([signature], { searchTransactionHistory: true });
    if (status) {
      assert.equal(status.err, null, `close_channel failed: ${JSON.stringify(status.err)}`);
      break;
    }
    const blockHeight = await connection.getBlockHeight('processed');
    assert(blockHeight <= latest.lastValidBlockHeight, `Transaction expired: ${signature}`);
    await sleep(250);
  }
  assert(Date.now() < waitDeadline, `Timed out waiting for transaction ${signature}`);

  const treasuryAfter = await connection.getBalance(treasury.publicKey, 'processed');
  const settledReceipt = await connection.getAccountInfo(receipt, 'processed');
  assert.equal(await connection.getAccountInfo(channel, 'processed'), null, 'owner close removes the channel');
  assert(settledReceipt, 'settled receipt remains available after channel close');
  assert.equal(settledReceipt.data[184], 1, 'legacy receipt is settled');
  const charged = settledReceipt.data.readBigUInt64LE(176);
  assert(charged > 0n && charged <= BigInt(maxCost), 'legacy task charge is bounded and positive');
  assert.equal(BigInt(treasuryAfter - treasuryBefore), charged,
    'legacy recovery sends exactly the task charge to configured treasury');
  assert.equal(await connection.getBalance(worker.publicKey, 'processed'), workerBefore,
    'unpinned legacy task does not redirect recovery funds to the supplied worker');

  console.log(JSON.stringify({
    program_id: programId.toBase58(),
    recovery: 'pre-pinning active task -> configured treasury',
    charged_lamports: charged.toString(),
    checks: ['seeded legacy-compatible channel and receipt', 'owner close transaction executed',
      'receipt remains settled', 'treasury receives exact bounded charge', 'worker receives no legacy payout'],
  }, null, 2));
} finally {
  if (!spawnError) {
    validator.kill('SIGTERM');
    await new Promise(resolve => {
      if (validator.exitCode !== null) resolve();
      else {
        validator.once('exit', resolve);
        setTimeout(() => { validator.kill('SIGKILL'); resolve(); }, 5000).unref();
      }
    });
  }
  const resolvedRoot = resolve(tempRoot);
  if (!resolvedRoot.startsWith(tempBase + sep)) throw new Error('Temporary validator directory escaped .aperture');
  await rm(resolvedRoot, { recursive: true, force: true });
}
