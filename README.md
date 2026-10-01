# Aperture

**A compute workspace for AI agents: private data in, bounded jobs and chains, verified result files out.**

Aperture lets an agent process datasets without copying their contents into a model's context. A job binds Python source, immutable input hashes, JSON parameters and spending/runtime limits to one signed authorization. A worker returns named files and signed execution evidence. Workflows reuse verified outputs, join batches and recover accepted jobs from a durable journal.

The current implementation is a CPU compute MVP with a React workspace, FastAPI gateway, Python SDK, local MCP server and Solana Devnet payment channels.

## Start the complete local workspace on Windows

```powershell
.\start_preview.bat
```

The launcher prepares the project's Node/Python dependencies and starts the console, gateway and worker together:

- Console: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- API: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- State, result files, logs and development identity: `.aperture/preview/`

Keep the launcher open. Ctrl+C stops its services and preserves their state. On Windows its child processes also stop when the launcher exits. Occupied ports are reported; the launcher does not replace an existing workspace. Existing `.env` configuration and external wallets are preserved.

This path runs the reviewed templates on the local host in **OFF_CHAIN** mode: real computation, no Solana payment, no Docker isolation. It accepts only the exact built-in sources exported at startup. Select **Temporary key** in the wallet chooser to use a real memory-only development signing key. Reload or disconnect loses that private key; use a persistent wallet for continuing approvals across reloads. Saved accepted-task capabilities can still recover results within the same browser tab.

Python 3.11+ and Node.js with npm are required. The Windows launcher also recognizes the bundled Codex runtimes when installed.

### First useful result

1. Connect a wallet and open **Agent workflows**.
2. Upload CSV batches with `category` and `amount` columns. Each selected file is one batch; the CLI below can split a larger dataset automatically.
3. Prepare the plan, review the first quote and explicitly sign each step.
4. Open `report.json` for category totals and invalid-row accounting, or `categories.csv` as a table. Downloads preserve the exact verified bytes.

Every browser step needs its own approval. The unattended SDK/MCP path uses a separate delegated key and a disk journal. Uploads belong to the exact owner and agent pair; a different agent cannot reuse another identity's references.

## What is implemented

| Area | Current behavior |
| --- | --- |
| Compute Studio | Source, private inputs, JSON parameters, source-bound quotes, execution, cancellation, result inspection and verified file downloads. |
| Agent workflows | Batch/merge plan builder, per-step browser approval, verified dependencies, retained admission requests and recovery in the same tab. |
| Files & results | Signed private storage usage, quota display and explicit file release. Active jobs and unexpired quotes protect their inputs from release. |
| Python SDK | Signed uploads, quote/receipt verification, task history/recovery, named output files and serial DAG execution with a durable SQLite journal. |
| MCP server | Local stdio tools for compute, private files and background workflow preparation, status, execution and cancellation. The host supplies its own AI model. |
| Worker | Bounded CPU execution. Configured Docker tasks use an unprivileged user, read-only root, disabled network and CPU/RAM/PID/runtime limits. |
| Devnet protocol | Agent passports, capped allowances, payment channels, configured settlement authority and persistent task receipts. Requires a compatible deployed program and funded channel. |

## Agent and CLI integration

```powershell
backend\venv\Scripts\python.exe -m pip install -e ".\sdk[mcp]"
```

Configure the existing gateway identity, network, owner and delegated agent key as described in the guides. Issuing a passport and funding a Devnet channel are separate owner actions; the runners do not increase their own allowance.

Automatic CSV batching:

```powershell
backend\venv\Scripts\python.exe examples\batch_data_workflow.py records.csv --batch-rows 5000 --workflow-budget-lamports 2000000
```

Run any validated version 1 plan exported by the browser. Supply its exact declared workflow ceiling; this example assumes `max_cost_lamports: 200000`:

```powershell
backend\venv\Scripts\python.exe examples\run_workflow.py aperture-workflow.json --workflow-budget-lamports 200000 --prepare
backend\venv\Scripts\python.exe examples\run_workflow.py aperture-workflow.json --workflow-budget-lamports 200000 --output .aperture-runs\results
```

Rerun the same command and journal to resume. An uncertain admission retains its original authorization; completed tasks are verified and reused. Do not delete a journal to replace a potentially accepted job.

## Configured Docker and Devnet execution

For caller-written workloads with container isolation, configure `backend/.env` and `backend/.worker.env` from their example files. Use matching worker authentication and pin the gateway/program identities in the frontend.

```powershell
.\start_frontend.bat
.\start_backend.bat
.\start_worker.bat
```

The worker launcher requires Docker with Linux containers and builds the task image when missing. `start_all.bat` starts only the frontend and gateway; a configured worker must be launched separately. Compose provides the equivalent deployment in [docker-compose.yml](docker-compose.yml).

Devnet payments additionally require a compatible program build, initialized protocol configuration, pinned treasury and an idle funded payment channel. Follow the [Devnet runbook](docs/demo-runbook.md); launching the local preview does not deploy, fund or confirm any Solana transaction.

## Bounds and evidence

| Bound | v1 implementation |
| --- | --- |
| Source and parameters | Up to 32,000 UTF-8 bytes each in the browser. |
| Job inputs | Up to 16 files and 64 MiB total. |
| Job outputs | Up to 16 files, 8 MiB each and 16 MiB total. |
| Job runtime | Up to 180 seconds, reduced when the authorized budget requires it. |
| Workflow | Up to 256 serially admitted steps; sum of step caps must fit the declared workflow ceiling. |
| Private storage | Up to 256 MiB and 512 objects per owner/agent pair. |
| Browser preview | JSON, CSV and text up to 1 MiB; tables show at most 100 rows and 32 columns. Download for full contents. |

The source analyzer sets a **heuristic rate**. It does not predict exact runtime or prove a worst-case compute cost. Authorized spend and runtime are bounded separately. `OFF_CHAIN` receipts report authenticated execution without a payment; `DEVNET` settlement requires independent on-chain verification.

Receipt signatures bind source/output hashes, identities and reported outcomes. They do **not** prove that remote hardware faithfully performed a computation. The reviewed local preview runs trusted host code; the Docker coordinator is also trusted because it controls the Docker socket. GPU inference, multi-gateway high availability and a cryptographic proof of computation are outside the implemented MVP.

## Documentation

- [Agent data jobs and durable workflows](docs/agent-workflows.md)
- [Python SDK](docs/python-agent-sdk.md)
- [MCP host setup](docs/mcp-agent.md)
- [Local walkthrough and Devnet runbook](docs/demo-runbook.md)
- [Protocol v2 accounts and settlement](docs/protocol-v2.md)
- [Architecture and economics](docs/WHITEPAPER.md)
- [Delegation and threat model](docs/kya-positioning.md)

## Development checks

The repository's [CI workflow](.github/workflows/ci.yml) contains backend/SDK, frontend and local-validator checks. For local frontend lint and build:

```powershell
cd frontend
npm run lint
npm run build
```

Runtime execution, container isolation and Devnet settlement are separate checks; a successful frontend build does not establish worker or payment readiness.

## License

[Apache 2.0](LICENSE).
