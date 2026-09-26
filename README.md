# Aperture — On-Demand Python Compute

Aperture is a Solana-powered compute network for Python and AI workloads. Developers use Compute Studio to review source-policy findings and runtime estimates, authorize jobs with a Solana wallet, and follow results from connected workers. The gateway queues each task; a worker executes the Python and streams output back. Live payment-channel billing begins only after the worker claims the task, and Compute Studio shows settlement evidence when available.

The hackathon MVP includes the task queue, authenticated worker handoff, Python execution, source-policy preview, and Devnet payment-channel integration. GPU acceleration and provider payouts are planned milestones.

The application has two explicit modes:

- **Browser demo:** local walkthrough with selectable Python examples and simulated progress. It never executes Python, signs a message, contacts a worker or makes a payment.
- **Devnet gateway:** one-time wallet authorization, server-side source policy, authenticated worker dispatch, streamed output and recorded settlement evidence. This requires a configured gateway, an approved worker and a deployed compatible payment-channel program.

## Start on Windows

For the interface and its browser demo, double-click `start_frontend.bat`, then open **http://127.0.0.1:3000**.

`start_all.bat` opens the frontend and gateway. Workers are started separately using `start_worker.bat` after configuration.

The launchers find Node.js/Python, create a project Python virtual environment when needed, install missing project dependencies, and report startup failures. They do not require a GPU for the browser demo. If Node.js or Python is missing, install Node.js LTS and Python 3.11+ first.

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
- `APERTURE_TREASURY_PUBKEY`: the shared payout wallet for confirmed channel charges.
- `SOLANA_RPC_URL` and `SOLANA_PROGRAM_ID`: the intended Devnet deployment.
- `CORS_ORIGINS`: your frontend's exact origins. The defaults permit localhost and 127.0.0.1 on port 3000.

Keep `APERTURE_DEMO_MODE=false`. The browser demo is independent of this backend setting.

The protocol initializer is pinned to `APERTURE_CONFIG_AUTHORITY` at program build time. Choose and protect that signing wallet first, set the same public key in `backend/.env`, and build the program from the project root with that environment variable:

```powershell
$env:APERTURE_CONFIG_AUTHORITY = "<protected signing-wallet public key>"
anchor build
```

Set `BACKEND_PRIVATE_KEY` to the matching private key in `backend/.env`, then deploy and verify this guarded program before initializing the protocol config. A source edit does not change an existing on-chain deployment; do not run the initializer against a program that was not built with this authority check. After verification, run the command from `backend/`:

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

The worker launcher explicitly enables direct host execution for trusted local development. This is not a security sandbox. Use an isolated container/VM for untrusted workloads. Source checks and time limits do not replace operating-system isolation.

## Workspace

- **Overview:** gateway availability, reported worker capacity, sample workloads and recent runs.
- **Compute Studio:** Python editing/import, copy/reset, explicit mode selection, progress, cancellation, output, JSON results and session history.
- **Worker network:** current heartbeats and reported hardware metrics. Unavailable telemetry is not replaced with invented data.
- **Getting started:** setup instructions and an explanation of the execution flow.

Navigation preserves a running Studio session. Run metadata persists in session storage for the current browser tab; source code, output and access tokens are not saved there. Reloading during a run is discouraged and closing the UI does not cancel a server task.

## Results and limits

A process exiting with a nonzero status is reported as failed. The gateway retains the worker identity, exit code and settlement evidence for authenticated result polling. A successful process does not by itself imply an on-chain settlement.

Result types include `SIMULATION`, `DEVNET`, `OFF_CHAIN`, `NONE` and `UNKNOWN`. Explorer links are shown only when the gateway supplies transaction evidence. A disconnected client cannot assume that a submitted task was cancelled.

The gateway queue, logs and receipts currently live in bounded process memory. Deploying the revised Anchor program, durable storage, transaction reconciliation and stronger worker isolation remain necessary before production use. This repository is a development prototype, not a mainnet service.

## Verification

Run from the project root with backend dependencies installed:

```powershell
python -m unittest discover -s backend -p 'test_*security.py'
python backend/test_task_results.py
npm run lint --prefix frontend
npm run build --prefix frontend
```

The result tests exercise failed Python execution, successful execution, task-capability enforcement, receipt polling and invalid worker result handling. Security tests cover authorization, task leases and source policy. RPC calls are mocked in automated tests; they are not proof of a live chain deployment.

For a short walkthrough, see [the demo runbook](docs/demo-runbook.md). Existing contract sources are in `programs/`; API and worker code are in `backend/`.
