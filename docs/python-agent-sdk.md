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

- `client.passport(owner_keypair, ...)` requests an owner challenge, checks its
  canonical policy and metadata hash, submits the locally constructed on-chain
  registration/update/revocation instruction on Devnet, then signs the owner
  authorization. The secret stays in the local process.
- `client.quote(source, ...)` checks the pinned deployment and verifies the
  source, owner, delegated agent, quote expiry, price ceiling and exact budgets.
- `client.execute(quote, source)` signs that exact quote with the agent key. A
  retry reuses the same quote and payload after a lost response.
- `client.wait(task)` polls settlement, downloads the original log, verifies
  gateway and worker signatures, checks hashes/cost bounds, and independently
  reads the Devnet TaskReceipt for a `DEVNET` result.

See [the complete protocol contract](protocol-v2.md), including its oracle
trust boundary, new deployment requirement and stored account layouts.
