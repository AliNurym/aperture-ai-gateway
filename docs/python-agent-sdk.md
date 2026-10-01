# Python agent client

`sdk/python/aperture_client` lets a local agent verify an exact quote, sign it
with its own Solana key, submit the task, and verify the returned worker and
gateway signatures. The SDK pins the deployment's program, oracle signer,
treasury, network, source hash, execution cap and runtime. For Devnet it reads
the v2 protocol config independently and checks the persistent on-chain task
receipt and confirmed settlement transaction.

The gateway signature attributes a receipt; the worker signature attributes a
result. Neither proves that remote hardware faithfully ran the submitted source.
Review output and settlement evidence independently. An `OFF_CHAIN` run has no
Devnet payment settlement.

## Install

```powershell
python -m pip install -e .\sdk
```

Use Python 3.11 or newer. The normal browser demo does not need this SDK.

For an MCP-compatible host, install the optional integration with
`python -m pip install -e ".\sdk[mcp]"` and follow the [MCP agent guide](mcp-agent.md).

## Create a local agent key

Keep the owner wallet and agent key in local Solana keypair files. The example
does not generate keys or upload them; it sends only public keys and signatures.
Fund the owner on Devnet to pay fees. Keep the agent key separate from the owner
wallet. It needs to be available to the process that signs an approved quote.

Set public deployment values and local paths in PowerShell:

```powershell
$env:APERTURE_GATEWAY_URL = "https://your-devnet-gateway.example"
$env:APERTURE_PROGRAM_ID = "<deployed-v2-program-id>"
$env:APERTURE_GATEWAY_PUBKEY = "<configured-devnet-oracle-public-key>"
$env:APERTURE_TREASURY_PUBKEY = "<configured-devnet-treasury-public-key>"
$env:APERTURE_OWNER_KEYPAIR = "C:\secure\owner.json"
$env:APERTURE_AGENT_KEYPAIR = "C:\secure\agent.json"
$env:SOLANA_RPC_URL = "https://api.devnet.solana.com"
```

Set the treasury and RPC values from the deployment's verified protocol config;
the SDK compares them with the on-chain account. Do not paste private key
contents into chat, source files, or project environment files committed to Git.
Before remote RPC use, the SDK also checks Solana's Devnet genesis hash; loopback
RPC endpoints are allowed for local-validator development.

## Run the example

The example computes a deterministic Monte Carlo distribution from synthetic
returns. It demonstrates general Python execution; it is not a financial
forecast. The owner explicitly signs the passport when `--authorize` is passed.
Depositing SOL is a separate explicit option, capped at 1 SOL per invocation.

```powershell
python .\examples\budgeted_risk_agent.py --authorize --max-cost-lamports 100000 --max-runtime-seconds 30
```

This only authorizes and submits the bounded task; the owner must first have an
open, adequately funded idle payment channel on Devnet. To create or top up a
channel, make a separate owner-signed deposit:

```powershell
python .\examples\budgeted_risk_agent.py --deposit-lamports 1000000
```

Use the exact same public-key configuration. Review the transaction in your
wallet before signing. The example writes the signed receipt to
`aperture-receipt.json`; treat it as project evidence and store it securely.

For a local demonstration without chain payment, set
`APERTURE_NETWORK=off_chain`, provide a demo-mode gateway and worker, and use
`--authorize`. The receipt will say `OFF_CHAIN`; it does not claim a Devnet
transaction.

## Library entry points

- `client.list_agent_passports(owner_keypair)` requests the owner's passport
  list and allowance usage with a short-lived wallet signature, then verifies
  each returned policy, owner signature, and allowance calculation locally.
- `client.passport(owner_keypair, ...)` requests an owner challenge, checks its
  canonical policy and metadata hash, submits the locally constructed on-chain
  registration/update/revocation instruction on Devnet, then signs the owner
  authorization. The secret stays in the local process.
- `client.quote(source, ...)` checks the pinned deployment and verifies the
  source, owner, delegated agent, quote expiry, price ceiling and exact budgets.
  Source is limited to 32,000 UTF-8 bytes across the console, SDK and gateway.
- `client.execute(quote, source)` signs that exact quote with the agent key. A
  retry reuses the same payload after a lost response, HTTP 408/5xx or an invalid
  admission response. If two attempts remain uncertain, `AdmissionUncertainError`
  exposes the public `quote_id`: use task history and resume to recover that
  admission before requesting another workload. HTTP 429 rejects the current
  attempt; it does not rule out admission by an earlier uncertain attempt. The
  raised `requests.HTTPError` includes the gateway's reason and retry/recovery
  guidance. Gateway redirects are rejected; configure its final URL explicitly.
- `client.wait(task)` polls settlement, downloads the original log, verifies
  gateway and worker signatures, checks hashes/cost bounds, and independently
  reads the Devnet TaskReceipt and checks its deadline against the signed runtime
  and spending limit for a `DEVNET` result. Returned `output` and `full_log` use
  the original downloaded log whose hash was verified. Temporary connection failures,
  HTTP 408/429/5xx and invalid JSON responses are retried with bounded backoff
  during the wait. Integrity failures and other HTTP errors stop immediately.
  A timeout retains the original task capability; cancellation is requested by
  default only while the gateway has not reported completion. If cancellation
  cannot be confirmed, the timeout states that explicitly. Call `wait()` again to
  retry an unfinished result verification, without admitting another task.
- `client.list_agent_tasks(limit=20, cursor=None)` reads one bounded task-history
  page after a fresh one-use signature from the configured agent key. Continue
  with its `next_cursor`. `client.resume_task(id)`
  reacquires that task's private capability without executing it again. Keep the
  returned `Task` object local; it contains the capability used for polling and
  cancellation.

See [the complete protocol contract](protocol-v2.md), including its oracle
trust boundary, new deployment requirement and stored account layouts.
