# Aperture live demo runbook

Compute Studio has one execution path: signed source and limits, authenticated gateway dispatch, real Python on a worker, and signed result evidence. It does not generate simulated progress or computation results.

`start_demo.bat` is only a presentation launcher: it checks `/health` and opens the console. The overview simulator uses illustrative values and sends no task. Use `start_preview.bat` and the steps below when you need actual local CPU execution and a signed receipt.

## Before the presentation

1. Start the configured gateway and one authenticated worker. Build the Docker task image first for isolated execution.
2. Open `http://127.0.0.1:3000`. Execution readiness must show a connected gateway and an active worker.
3. For Devnet settlement, deploy the compatible v2 program, initialize its protocol config, and set the frontend gateway and treasury public-key pins. A reachable HTTP server alone is insufficient.
4. For the retained Devnet setup, run `backend/venv/Scripts/python.exe scripts/devnet.py status`. Confirm `program_deployed: true`, `protocol_config_verified: true` and the intended program ID; this command only reads RPC state and submits no transaction.
5. Connect a Solana wallet. Confirm the actual network and settlement mode shown by the gateway.
6. Keep the worker and gateway running throughout the presentation.

## Three-minute live walkthrough

1. Open **Agent batch risk scoring** in Compute Studio. Show the actual Python source and fixed random seed.
2. Set the maximum spending and runtime limits. Request the gateway quote.
3. Inspect the rate, source-bound authorization and execution deadline. For Devnet, fund an idle payment channel before submitting.
4. Sign the exact reviewed quote. The gateway accepts the job and an authenticated worker claims it.
5. Watch worker output and the run state. Navigate to Worker network and return to Studio while the job is active; the run remains mounted and monitored.
6. Inspect the actual JSON result. Select a different reviewed sample and run it to show a different calculation. With an isolated Docker worker, you can also edit and rerun accepted Python source.
7. Show signature verification, source/output SHA-256 values, worker identity and execution boundary. Download the receipt and raw output.
8. For confirmed Devnet settlement, open the actual transaction link. Off-chain execution must be described as real computation without an on-chain payment.
9. Select **Policy rejection** and request a quote. The gateway's real AST policy rejects the source before worker dispatch.

## Local Windows execution without Docker

This is actual host execution of reviewed sources, without a Solana payment or a container security boundary. Use the normal Docker launcher when isolation is required.

For the complete interactive workspace, run `start_preview.bat` from the
project root. It prepares dependencies, starts the console/gateway/worker and
pins the console to its own gateway signing key. Data and development keys stay
in the ignored `.aperture/preview/` directory. Keep the launcher open; Ctrl+C
stops its services without deleting state. Occupied ports cause a clear refusal
instead of replacing a running workspace.

Choose Temporary key in the development wallet dialog, open Agent workflows
and select Use example data. Review and approve both batches and the final
merge, then open the verified JSON/CSV files. This uses real uploads and worker
execution. The temporary private key exists only in memory; a persistent wallet
is required for new approvals after reload. Saved task capabilities can still
recover accepted results in the same tab.

Advanced launch with different ports:

```powershell
backend\venv\Scripts\python.exe scripts\preview_workflows.py --frontend --temporary-key --supervise --port 8001 --frontend-port 3001
```

The following older demo helper is a separate profile under `.aperture/demo/`:

```powershell
node scripts/export-demo-workloads.mjs
# Review the exported .py files in .aperture/demo/approved.
backend/venv/Scripts/python.exe scripts/demo.py prepare --off-chain
```

In separate terminals:

```powershell
backend/venv/Scripts/python.exe scripts/demo.py gateway
backend/venv/Scripts/python.exe scripts/demo.py worker --allow-unsafe-local-execution
node frontend/scripts/vite.mjs --host 127.0.0.1 --port 3000 --strictPort
```

Run the SDK path with `backend/venv/Scripts/python.exe scripts/demo.py run --workload risk`. It signs real delegation and source authorization, waits for the worker, verifies both result signatures and retains the receipt and exact raw output under `.aperture/demo/evidence`. Repeat with `--workload math` or `--workload statistics` for a different calculation.

For the browser, set `VITE_ENABLE_SESSION_KEY=true` in the ignored `frontend/.env.local`, and copy the public gateway signing key from `.aperture/demo/public.json` into `VITE_APERTURE_GATEWAY_PUBKEY`. Select **Temporary key** in the wallet dialog. This creates a real Ed25519 key in browser memory; reload or disconnect loses it. The option is available only in the development server. Phantom and Solflare remain available for a persistent wallet.

The local worker admits only the exact approved files captured at startup. Review a modified file, export it to the approved directory and restart the worker before submitting its changed source. This source approval rule does not provide OS isolation. Existing development settings and keys are preserved; `prepare` refuses to overwrite them.

## Functional workflow checks

These checks create separate local gateway/worker workspaces, use synthetic CSV
data and run in OFF_CHAIN mode. They require Node.js and a Python environment
with `backend/requirements.txt` and the editable `sdk[mcp]` package installed.
Run them from the repository root; on Linux, use `python` in place of the Windows
interpreter path. Choose a fresh output directory for every run to preserve
earlier evidence.

```powershell
backend/venv/Scripts/python.exe -X utf8 -m unittest discover -s sdk/tests -p test_batch_workflow.py -v
npm run test:data --prefix frontend
backend/venv/Scripts/python.exe -X utf8 scripts/demo_workflow.py --rows 1000 --output .aperture/checks/sdk
backend/venv/Scripts/python.exe -X utf8 scripts/check_workflow_cancel.py --output .aperture/checks/cancellation
backend/venv/Scripts/python.exe -X utf8 scripts/check_mcp_stdio.py --output .aperture/checks/stdio
backend/venv/Scripts/python.exe -X utf8 scripts/check_workspace_restart.py --output .aperture/checks/restart
backend/venv/Scripts/python.exe -X utf8 scripts/check_exported_plan.py --output .aperture/checks/exported-plan
```

The SDK demo interrupts and resumes the first accepted task. The cancellation
check covers both the SDK runner and the background MCP controller. The stdio
check launches two actual MCP server processes and resumes the same workflow
after closing the first process. Successful checks retain their summaries,
result files and journals under the chosen output directory and stop their own
services. The workspace restart check completes the first step, restarts both
gateway and worker, resumes the dependent step, then restarts again and checks
that intermediate/final files and completed journals survive unchanged.
The exported-plan check uses the actual frontend plan builder for 17 batches
and executes its 20-step JSON through `examples/run_workflow.py`. Preparation
submits no jobs; a completed replay verifies the same final files without
creating more tasks.

For repeated calculations and periodic service restarts:

```powershell
backend/venv/Scripts/python.exe -X utf8 scripts/soak_workflow.py --duration-seconds 600 --interval-seconds 60 --restart-every 10 --output .aperture/checks/soak
```

`summary.json` records the final status; `cycles.jsonl` records each verified
cycle. A `running` summary is not proof of completion. These checks establish
local CPU computation and recovery for the included templates; browser clicks,
Docker execution and Solana settlement require their own verification.

## Windows Devnet build and launch

Microsoft C++ Build Tools (x64/x86), Windows SDK, Rust and Agave 4.3.0 are required. Build with the exact gateway signing key that will initialize the protocol; the program rejects another initializer.

```powershell
$public = Get-Content .aperture/demo/public.json | ConvertFrom-Json
./scripts/build-devnet.ps1 -ConfigAuthority $public.gateway_pubkey
backend/venv/Scripts/python.exe scripts/devnet.py prepare
backend/venv/Scripts/python.exe scripts/devnet.py status
```

Review `target/deploy/build-manifest.json` before deployment. The program address must match the existing `.aperture/devnet/program.json` key. Keep that key private and pass its path only to Solana CLI. Deployment uses explicit Devnet RPC, a funded development signer and the reviewed binary; the prepare/status commands do not submit transactions.

Run `./scripts/deploy-devnet.ps1` for a read-only deployment review, including the build hash and a conservative funding target. After approval and sufficient Devnet funding, `./scripts/deploy-devnet.ps1 -Publish` submits the reviewed binary using the existing program key and pinned development authority. It does not replace an existing program automatically. CLI output is kept in ignored private files because a failed upload can contain buffer recovery material.

After the approved deployment, run `backend/venv/Scripts/python.exe scripts/devnet.py initialize`. This reads the deployed bytes back, checks them against the build hash, funds the separate treasury's rent reserve and initializes the v2 config using the pinned authority. An existing compatible configuration is preserved. A mismatch stops initialization.

When only the gateway development wallet was funded, run `backend/venv/Scripts/python.exe scripts/devnet.py fund-owner` after initialization. It transfers only the amount needed to bring the configured development owner's balance to 0.05 Devnet SOL, covering the channel deposit and account rent. An already funded owner receives no transfer. It never uses mainnet.

Use the public gateway and treasury values from `.aperture/demo/devnet/public.json` for `VITE_APERTURE_GATEWAY_PUBKEY` and `VITE_APERTURE_TREASURY_PUBKEY` in `frontend/.env.local`. When no task is active, stop the off-chain gateway/worker and launch the Devnet services in separate terminals:

```powershell
backend/venv/Scripts/python.exe scripts/devnet.py gateway
backend/venv/Scripts/python.exe scripts/devnet.py worker --allow-unsafe-local-execution
```

The Devnet owner and gateway keys need actual Devnet funds. To fund a channel with an explicit 0.01 Devnet SOL deposit and execute a paid task, use `backend/venv/Scripts/python.exe scripts/devnet.py run --workload risk --deposit-lamports 10000000`. Repeated runs can omit the deposit. The SDK verifies the signed output, persistent on-chain task record and settlement confirmation. The helper does not request airdrops or deploy automatically, and never substitutes off-chain execution for a failed Devnet run.

If the public airdrop RPC returns HTTP 429, respect its `Retry-After` interval. Obtain the required test funds through an available Solana-recommended faucet or an existing Devnet wallet. Keep the running off-chain services available until program deployment and configuration are confirmed; funding failure does not make a Devnet payment ready.

If monitoring is interrupted after acceptance, run `backend/venv/Scripts/python.exe scripts/devnet.py resume --task-id task-...` with the actual printed task ID. Its capability is retained locally in the ignored Devnet pending directory; resuming monitors the existing job and does not submit another paid execution. Keep the capability files private.

## Recorded paid execution

Task `task-183cd90e80584f2f933afe53349fa7b1` completed the risk sample's 1,500,000 scenarios in 0.9525 seconds on the reviewed local CPU worker. The owner deposited 0.01 Devnet SOL; the confirmed task charge was 3,200 lamports (0.0000032 Devnet SOL).

The SDK verified gateway and worker signatures, exact source/output hashes, the settled on-chain TaskReceipt and transaction confirmation. Monitoring the same accepted task with `resume` repeated those checks without another deposit or execution.

- [Confirmed settlement transaction](https://explorer.solana.com/tx/59yEcz3hDauPWuX9NdgMP9fQwtQLF2YMkz8vphMrtFs1pEHAEXRSaBoVnMiQ1qDsbjns8ZtDRrCFYtgRqduHWNza?cluster=devnet)
- On-chain TaskReceipt: `E1wgDM7gaSLSrU9gZ4BJMSNJ7esQYXi3nk8FzPdiydDL`.
- Local receipt, raw output and verification record: `.aperture/demo/devnet/evidence/task-183cd90e80584f2f933afe53349fa7b1.*`.

This is a record of an observed execution. Current worker readiness must still be checked before each presentation. The worker used trusted host execution of three reviewed sources, without Docker isolation.

On 2026-10-05, the official `https://api.devnet.solana.com` endpoint and QuickNode's public Devnet documentation endpoint both returned `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`; both resolved the settlement as finalized at slot 504877196. The [Solana `getGenesisHash` reference](https://solana.com/docs/rpc/http/getgenesishash) still shows the different static example `GH7ome3EiwEr7tu9JuTh2dpYWBJK3z69Xm1ZE3MEE6JC`. The clients pin the matching live hash. Recheck the endpoint before recording if Solana restarts or resets Devnet.

## Settlement and execution boundaries

- `DEVNET`: a confirmed program settlement is reported with its transaction signature.
- `OFF_CHAIN`: Python ran through the authenticated worker path, without a Solana payment. This is not a substitute for demonstrating Devnet settlement.
- `NOT_STARTED` / `NONE`: execution or settlement did not start. A rejection is not a successful computation.
- Docker workers use a task container with network, user, filesystem, resource and runtime restrictions.
- Trusted local workers execute Python on the host. They require explicit operator opt-in and are labelled as trusted local execution.
- Receipt signatures attribute output and bounds to gateway/worker keys; they do not prove faithful remote computation. For Devnet settlement, the browser also independently queries the on-chain task receipt and transaction confirmation before reporting verification.

## Presentation recovery

- Gateway offline: keep source in Studio, restart the gateway, then refresh readiness.
- No worker heartbeat: restart the configured worker and wait for registration. Do not claim execution is ready.
- Wallet signature declined: no new job is submitted; review a fresh quote before retrying.
- Admission response lost: recover the exact saved signed request in that browser tab before creating another job.
- Browser reload during an accepted task: monitoring recovers using its tab-local capability; closing the tab does not cancel server execution.
- Cancellation not confirmed: keep monitoring until the gateway reports a terminal outcome.
