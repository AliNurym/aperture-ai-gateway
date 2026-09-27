# Aperture — On-Demand Python Compute

Aperture is a Solana-powered compute network for Python and AI workloads. Developers use Compute Studio to review source-policy findings and runtime estimates, authorize jobs with a Solana wallet, and follow results from connected workers. The gateway queues each task; a worker executes the Python and streams output back. Live payment-channel billing begins only after the worker claims the task, and Compute Studio shows settlement evidence when available.

The hackathon MVP includes the task queue, authenticated worker handoff, Python execution, source-policy preview, and Devnet payment-channel integration. GPU acceleration and provider payouts are planned milestones.

Compute Studio submits real workloads through the gateway. It requests a source-bound quote, obtains a wallet signature, follows authenticated worker output and verifies signed result evidence. There is no browser-only simulated execution path.

Devnet settlement requires a configured gateway, an approved worker and a deployed compatible payment-channel program. Explicit off-chain development configuration can execute real Python through the same authenticated worker path without a Solana payment; its results are labelled `OFF_CHAIN` and never presented as Devnet settlement.

## Start on Windows

For the interface, double-click `start_frontend.bat`, then open **http://127.0.0.1:3000**. Actual execution requires the configured gateway and an authenticated worker.

`start_all.bat` opens the frontend and gateway. Workers are started separately using `start_worker.bat` after configuration.

The launchers find Node.js/Python, create a project Python virtual environment when needed, install missing project dependencies, and report startup failures. Python CPU execution does not require a GPU. If Node.js or Python is missing, install Node.js LTS and Python 3.11+ first.

The Vite launcher resolves Windows directory junctions before starting. This avoids build paths escaping the project and dependency-optimizer failures when the same checkout has multiple directory names.

## Frontend commands

```powershell
cd frontend
npm ci --legacy-peer-deps
npm run dev -- --port 3000
npm run lint
npm run build
npm run preview
```

The checked-in `frontend/package-lock.json` is the canonical dependency lock. Set `VITE_API_URL` in `frontend/.env` for a gateway other than `http://127.0.0.1:8000`. Rebuild after changing it.

## Configure the gateway

Copy `backend/.env.example` to `backend/.env` and configure:

- `APERTURE_WORKER_TOKEN`: a unique secret of at least 16 characters, shared with approved workers. Example placeholders are rejected.
- `APERTURE_CONFIG_AUTHORITY`: public key pinned into the Anchor program at build time. It must match the protected backend signing wallet used to initialize the protocol config.
- `BACKEND_PRIVATE_KEY`: your development oracle signer, for Devnet payment-channel operations.
- `APERTURE_TREASURY_PUBKEY`: the shared payout wallet for confirmed channel charges. Fund it to its rent-exempt minimum before starting tasks; the program rejects an unfunded treasury so small first charges cannot fail at settlement.
- `SOLANA_RPC_URL` and `SOLANA_PROGRAM_ID`: the intended Devnet deployment.
- `CORS_ORIGINS`: your frontend's exact origins. The defaults permit localhost and 127.0.0.1 on port 3000.

Check the treasury wallet's current rent-exempt minimum with `solana rent 0` and fund it before initializing the v2 config.

Keep `APERTURE_DEMO_MODE=false` for Devnet settlement. The legacy flag explicitly selects off-chain development settlement; it still requires real worker execution and signed authorization.

The protocol initializer is pinned to `APERTURE_CONFIG_AUTHORITY` at program build time. Choose and protect that signing wallet first, set the same public key in `backend/.env`, and build the program from the project root with that environment variable:

Use Agave CLI 4.3.0 and Anchor Lang 0.32.2 for a fresh Devnet deployment. On Windows, the build helper initializes Microsoft C++ Build Tools and Windows SDK, performs the native Rust check and builds sBPF v3. It uses the locally installed Agave tools or `cargo-build-sbf` from PATH.

```powershell
./scripts/build-devnet.ps1 -ConfigAuthority "<protected signing-wallet public key>"
# Review target/deploy/build-manifest.json before publishing anything.
```

The v2 Program ID in the source and Anchor config is A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ. The ignored program keypair was generated for this local checkout; keep a secure backup and pass its path only to Solana CLI. For a different checkout, generate a new keypair and update every configured program ID consistently. The program-address key signs deployment; it is separate from the protected authority/oracle key. Deployment and initialized configuration must be confirmed against Devnet before accepting paid jobs.

For this checkout's separate development wallets, use the [Windows Devnet runbook](docs/demo-runbook.md#windows-devnet-build-and-launch). `scripts/deploy-devnet.ps1` reviews the exact build and funding target without transactions; `-Publish` explicitly publishes the reviewed build to Devnet. `scripts/devnet.py initialize` reads the deployed binary back before configuring it. These helpers preserve the existing off-chain settings and keep private deployment logs out of version control.

Set `APERTURE_CONFIG_AUTHORITY` to the public key of the signing wallet and `BACKEND_PRIVATE_KEY` to its matching local private key in `backend/.env`. It must be available at program build time and later sign `initialize_config`. Build and deploy before initializing. A source edit does not change an existing on-chain deployment; do not run the initializer against a program that was not built with this authority check. After deployment, verify the new program's executable account and configured address, then run this command from `backend/`:

```powershell
.\venv\Scripts\python.exe .\init_protocol_config.py
```

This signs one Devnet transaction with the backend oracle key. The protocol config fixes the common treasury for that deployment; changing it later requires an explicit program migration or a new deployment. The UI will not open or top up a live channel until the config is available.

```powershell
cd backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

API documentation is at **http://127.0.0.1:8000/docs**; readiness is at `/health`.

Workers use a separate Docker container per task by default. The task has no network, runs as an unprivileged user, sees only its read-only input, and has CPU, memory, process, output and time limits. The Docker socket belongs to the trusted coordinator only; the coordinator process still controls the host Docker daemon. Use an isolated VM or host for mutually untrusted operators. Host execution requires an explicit trusted-development flag and is never enabled by the launcher by default.

## Workspace

- **Overview:** gateway availability, reported worker capacity, sample workloads and recent runs.
- **Compute Studio:** Python editing/import, copy/reset, quote review, explicit cost/runtime limits, progress, cancellation, output, signed receipt export and session history.
- **Agent passports:** owner-issued, revocable delegation for a separate public agent key, with the `python.execute` capability, per-run caps, total allowance and expiry. This is a cryptographic delegation record, not legal KYC or a verified human identity.
- **Worker network:** current heartbeats and reported hardware metrics. Unavailable telemetry is not replaced with invented data.
- **Getting started:** setup instructions and an explanation of the execution flow.

Navigation preserves a running Studio session. Run metadata and the active task capability are stored in session storage for the current browser tab so polling can recover after a reload. If the gateway response is uncertain, the exact signed admission (including its source) stays in that tab until recovery or rejection; it is removed after acceptance. Wallet private keys are never stored there. Closing the UI does not cancel a server task.

## Results and limits

A process exiting with a nonzero status is reported as failed. The gateway retains the worker identity, exit code and settlement evidence for authenticated result polling. A successful process does not by itself imply an on-chain settlement.

Result types include `DEVNET`, `OFF_CHAIN`, `NOT_STARTED`, `NONE` and `UNKNOWN`. Explorer links are shown only when the gateway supplies transaction evidence. A disconnected client cannot assume that a submitted task was cancelled.

Gateway quotes, jobs, worker outbox, and receipts use local SQLite and survive process restarts. The gateway requires one process per database file and a persistent writable state volume. Run Docker Compose with a configured `backend/.env`; the worker is a separately started trusted coordinator (`docker compose --profile worker up --build`). Build its per-task image first using the launcher instructions. The gate rejects Devnet work until a compatible v2 program and matching protocol configuration are available. The v2 program requires a new deployment because the earlier account layout is not compatible; close old channels with their original deployment first. This is a Devnet development prototype, not a mainnet service.

Expired unused quotes and challenges are pruned as new ones are issued. Completed job records are capped by `APERTURE_MAX_COMPLETED_TASKS` (default 1000); delegated spend totals remain in a compact SQLite ledger after job details age out. The API rejects request bodies above `APERTURE_MAX_REQUEST_BYTES` (default 2.5 MB). For live Devnet approvals, copy `frontend/.env.example` to `frontend/.env.local` and set the gateway signer and treasury pins from trusted deployment configuration; the frontend reconstructs the canonical quote message and checks these pins before requesting a wallet signature.

For gateway results, the browser verifies the gateway signature and worker signature when present, and matches signed receipt evidence to the approved quote and downloaded raw output. For Devnet settlement it also independently reads the on-chain TaskReceipt, compares its owner, source, rate and charge, and checks transaction confirmation. Off-chain runs use the configured gateway signer pin when supplied and do not settle on Solana. Signatures do not prove faithful remote computation.

## Owner delegated Python agents

Install the local client with `python -m pip install -e .\sdk` and follow [the Python agent SDK guide](docs/python-agent-sdk.md) to create a separate agent key, issue an owner-signed passport, review bounded quotes, and verify worker and gateway receipts. The example computes a deterministic synthetic Monte Carlo risk distribution. It uses CPU only and does not call a paid model API.

## Verification

Run from the project root with backend dependencies installed:

```powershell
python -m unittest discover -s backend -p 'test_*security.py'
python backend/test_task_results.py
python backend/test_solana_client.py
python -m unittest discover -s sdk/tests -v
npm run lint --prefix frontend
npm run build --prefix frontend
```

CI also validates Compose, builds the isolated task image and runs the Docker
isolation tests. The contract job builds the SBF artifact and exercises real
instructions against a temporary local Solana validator. These local-chain
checks do not assert that the separate Devnet deployment has been completed.

The result tests exercise failed Python execution, successful execution, task-capability enforcement, receipt polling and invalid worker result handling. Security tests cover authorization, task leases and source policy. RPC calls are mocked in automated tests; they are not proof of a live chain deployment.

For a short walkthrough, see [the demo runbook](docs/demo-runbook.md). Existing contract sources are in `programs/`; API and worker code are in `backend/`.
