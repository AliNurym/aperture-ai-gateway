# Aperture payment and agent protocol v2

This specification follows programs/src/lib.rs and backend/solana_client.py.
The on-chain oracle is a trusted execution and settlement reporter: it confirms
that the gateway accepted a signed task authorization, then applies an
enforceable rate, cost cap, and deadline. It is not a trustless execution proof.
The worker and gateway attestations establish which keys signed reported bytes;
they do not prove correct execution.

## Deployment compatibility

Version 2 changes the sizes of ProtocolConfig and ChannelState, and adds agent
passports and persistent task receipts. Existing v1 accounts are not reallocated
or migrated by these instructions. The old config PDA is already occupied, so
initializing v2 at the same program address cannot overwrite it. Use a new
program ID for v2, deploy a compatible build, initialize its config, and verify
program owner, version, oracle and treasury before enabling live quotes.
Close/refund active v1 channels through their original program before moving
funds. Do not point a new gateway at an old deployment.

## Build toolchain

Use Anchor CLI and Anchor Lang 0.32.2 with Agave CLI 4.3.0 for a fresh Devnet
deployment. CI builds the program with `cargo build-sbf --arch v3` and executes
the resulting artifact on a temporary local validator. Preserve the deployed
program ID and the compile-time `APERTURE_CONFIG_AUTHORITY`; rebuilding under a
different authority requires deploying a new program. Regenerate and review the
IDL whenever changing Anchor versions, then verify the hand-built SDK accounts
and instruction data against it.

The build pins APERTURE_CONFIG_AUTHORITY; initialize_config accepts only that
key. The config fixes the authority/oracle signer and treasury for the program
deployment. Protect their keys. No such signing key belongs in source control.

## PDA accounts

All account lengths below include Anchor's 8-byte discriminator; scalar fields
use Borsh little-endian encoding. Seeds use the program ID of the active v2
deployment.

| Account | Seeds | Serialized fields after discriminator | Total bytes |
| --- | --- | --- | ---: |
| ProtocolConfig | ["config"] | authority, oracle, treasury (Pubkey each), bump (u8), version (u16, value 2) | 107 |
| AgentPassport | ["agent", agent_pubkey] | owner, agent, metadata hash ([u8;32] each), max cost (u64), max runtime (u32), valid-until (i64), total/spent/reserved budget (u64 each), revoked (bool), revoked-at (i64), bump (u8) | 158 |
| ChannelState | ["channel", owner] | user and oracle (Pubkey), balance and burn rate (u64), last update (i64), bump (u8), active agent (Pubkey), active task hash ([u8;32]), task cap (u64), deadline/start (i64 each), last task hash ([u8;32]), last charge (u64) | 225 |
| TaskReceipt | ["task", task_hash] | owner and agent (Pubkey each), task/source hashes ([u8;32] each), rate/cap (u64 each), start/deadline/settled-at (i64 each), charged (u64), settled (bool), bump (u8) | 186 |

The v2 channel retains the old 97-byte serialized prefix, but its full size is
different. Parsers must verify program owner, discriminator, exact length, and
version where present before reading offsets.

## Agent passport

1. An owner nominates a distinct Ed25519/Solana agent public key. The owner
   signs an audience-bound API challenge and an on-chain register/update/revoke
   instruction. The gateway checks both.
2. Passport metadata hashes the canonical policy/name/version, the fixed
   python.execute capability, task cost/runtime, total allowance, expiry,
   program ID, and network.
3. The chain enforces per-task and lifetime budget reservations for delegated
   tasks. Updating a policy preserves spent budget and is blocked while a
   reservation is active. A nonzero reservation cannot be silently reissued.
4. Revocation rejects new task admission. A running task remains charged only
   up to the earlier of its deadline and the recorded revocation time; unused
   reserved allowance is released at settlement.

This is wallet-owner delegation, not legal KYC or a person/model identity
credential. The durable gateway policy record is also needed to bind descriptive
metadata and versions; a single on-chain registration does not establish a
portable identity standard.

## Bounded task lifecycle

Before worker dispatch the gateway obtains a signed task quote and checks an
idle, funded channel. It stores a prepared start_task transaction and task
intent durably before broadcast. The oracle signs the start; the chain writes a
unique persistent receipt and starts the timer only when the transaction lands.
An uncertain send is reconciled against the same signature/task; the gateway
does not create a second task as a retry.

start_task records task and source hashes, agent, lamports/second, maximum
lamports and maximum runtime. The rate is bounded at 25,000 lamports/second and
runtime at 3,600 seconds on chain (the gateway currently admits up to 180
seconds). The full task cap is reserved against the channel. A delegated task
also reserves that allowance against the passport. An owner executing as its
own agent does not need a passport.

Settlement charges:

```
min(channel balance,
    task maximum cost,
    rate * max(0, min(now, task deadline, revocation time when revoked) - start))
```

It releases the original reserved task allowance, accounts only the actual
charge, stores the settled amount in the persistent TaskReceipt, and clears
active channel state. A settled receipt retry is a no-op and cannot mutate a
newer task. Owner channel closure can settle a running task and refund the
remaining balance while leaving the receipt PDA alive. Legacy nonzero
update_burn_rate requests are rejected to prevent unbounded accrual.

Gateway SQLite preserves quote, job, nonce, worker registration, and signed
receipt state across a restart. One gateway process may own a database file at
a time. If RPC confirmation is uncertain, the task remains pending and the
gateway reconciles the original task receipt/transaction before reporting an
exact charge. An off-chain task reports OFF_CHAIN and does not claim a chain
charge.

## Transaction ABI

- initialize_config(treasury: Pubkey) uses [config writable/init, authority
  signer+writable, system program] and rejects any authority other than the
  compile-time APERTURE_CONFIG_AUTHORITY.
- register_agent(metadata_hash, max_cost, max_runtime, valid_until,
  total_budget) uses [passport writable/init, owner signer+writable, agent,
  system program].
- update_agent takes the same policy arguments and uses [passport writable,
  owner signer]; revoke_agent takes no policy and uses the same accounts.
- start_task(task_hash, source_hash, agent, rate, max_cost, max_runtime) uses
  [config, channel writable, oracle signer+writable, treasury writable,
  optional passport writable, receipt writable/init, system program]. Direct
  owner execution omits passport using the program-ID sentinel in the manual
  client path.
- stop_task(task_hash) uses [config, channel writable, oracle signer,
  treasury writable, optional passport writable, receipt writable].
- close_channel is owner-signed and takes the config, channel, owner,
  treasury, optional passport, and optional receipt needed for active settle.

Check the deployed generated IDL and every client account flag when changing
Anchor versions or the Rust accounts structs. The backend hand-builds Anchor
discriminators and Borsh payloads.

## Receipt verification limits

The gateway signs canonical Aperture compute receipt v1 JSON. It includes
quote/owner/agent/version, source and full-output hashes, status, run limits,
charge and settlement evidence, worker receipt, and signer keys. A client must
recompute the message from all evidence fields, verify the expected gateway
key, check quote limits and hashes, and independently read the persistent task
receipt and confirmed transaction for DEVNET claims.

The worker signs canonical aperture.worker.result.v1 JSON binding its stable
registered key, task and lease IDs, source/output hashes, mode, duration and
exit code. This provides attribution and tamper evidence. A compromised worker
can still lie about computation. The gateway selects/observes execution, and
neither signature is a TEE/zk proof, model identity, GPU attestation, or
independent replication.
