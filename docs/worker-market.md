# Worker selection and provider operations

Implemented locally on 2026-10-23. This joins the old consumer/provider product roles to the current gateway, rather than recreating the old provider screen's local counters.

The shell also retains its stateful Studio, inference and visited workflow modules across navigation. Changing the active page no longer remounts the whole workspace, aborts task monitoring or replaces the editor with a recovery placeholder. Full browser reload still uses the existing task/authorization recovery checkpoints.

## Consumer flow

1. A worker owner publishes a rate in **Provide compute** (or at startup with `APERTURE_WORKER_RATE_LAMPORTS_SEC`).
2. Open **Worker network** and choose a priced Python worker with **Use this worker**, or leave the Studio route on automatic.
3. The gateway checks that the exact key is registered, its heartbeat is recent, it accepts tasks, its rate is valid, and its runtime/offer matches.
4. Execution authorization **v5** includes the selected `worker_target` and the worker's per-second rate alongside the source hash, cost/runtime limits and deployment identity. Automatic routing selects the lowest-priced compatible worker and pins that identity. Older v2/v3/v4 authorizations remain supported.
5. Admission rechecks capacity. A different worker cannot claim a pinned job. Queued work does not silently fall back if the chosen node disconnects or drains; the owner can stop it or wait for the queue timeout.
6. The gateway receipt preserves the target. Browser and Python SDK verification reject results attributed to another node or signing key.

Python, file jobs and inference use the same pinned executor and published rate through the API, SDK and browser. In **Model inference** or **AI Sentinel**, choose an **Execution worker** after selecting the offer, or let the gateway select the lowest-priced compatible worker. The browser rechecks the key, offer, admission mode and rate before asking for a signature. A stale explicit selection remains pinned and unavailable until the owner chooses another node or automatic routing.

```python
node = next(node for node in client.workers()
            if node['online'] and node['accepting_tasks'] and 'python' in node['runtimes'])
target = {key: node[key] for key in ('node_id', 'worker_pubkey')}
quote = client.quote('print(6 * 7)', worker_target=target)
result = client.wait(client.execute(quote, 'print(6 * 7)'))
```

MCP exposes `list_workers` and the same optional `worker_target` on `quote_python`, `quote_compute_job`, and `quote_inference`. Owner delegation and local MCP execution/cost ceilings still apply.

## Provider flow

Open **Provide compute**, enter the running worker's ID and configured worker credential. Set the lamports-per-second rate that you want buyers to sign. The worker's full confirmed task charge goes to its executor address; the gateway's DeepSeek/Gemini API bill remains separate. Credentials are held only in component memory, never in browser storage, URLs or public network responses.

The workspace reads:

- Actual heartbeat freshness, runtime, source policy and execution mode.
- Assigned jobs and their states from the gateway database, up to 20 retained tasks.
- Completed/finished task counts and measured execution seconds.
- Confirmed Devnet lamports attributed to the executor address.
- Separate OFF_CHAIN task counts and estimates; these are not payments.

**Drain worker** persists `accepting_tasks=false`. Current leases can be recovered and completed, but the worker cannot claim another task. Heartbeats and gateway restarts preserve the mode. **Resume admissions** enables new claims. Neither operation starts/stops the operating system process or kills a running job.

Public `GET /workers` returns selected metadata, published rate and aggregate totals. Authenticated `GET /workers/me` adds private task activity; `POST /workers/me/mode` changes admission mode and `POST /workers/me/rate` updates the worker owner's rate. Authentication uses existing per-worker credentials; source, wallet owner identities, task tokens and worker credentials are excluded from the public directory and operator activity response.

Headless operators can use the same API through:

```powershell
backend\venv\Scripts\python.exe scripts\worker_control.py status
backend\venv\Scripts\python.exe scripts\worker_control.py drain
backend\venv\Scripts\python.exe scripts\worker_control.py resume
```

These commands read `backend/.worker.env` with process environment taking precedence. Remote operator access requires HTTPS; loopback HTTP is supported.

The combined preview writes its temporary operator credential to ignored `.aperture/inference-preview/worker-access.json` and prints only that file's path. It is not a wallet key. The file can also be used without copying the credential:

```powershell
backend\venv\Scripts\python.exe scripts\worker_control.py status --credential-file .aperture\inference-preview\worker-access.json
```

## Durable totals and evidence limits

Worker totals are updated in the same SQLite transaction as the first completion transition. Duplicate result/admission retries do not add earnings again. Totals survive completed-task pruning and database reopening. Initial migration includes retained completed jobs and marks them as a baseline; previously pruned history cannot be reconstructed.

Only a `DEVNET` receipt with an exact worker payout matching the task charge contributes to paid earnings. OFF_CHAIN elapsed-time estimates remain separate. Gateway/worker signatures attribute reported execution; they do not prove faithful remote computation. Updated 0.5.0 contract source routes the entire confirmed task charge to the executor, but a compatible deployment and an independently verified live Devnet payout remain unverified.

## Verification on 2026-10-23

- Backend: 107 tests run, with 2 Docker-dependent tests skipped. Six new integration tests cover exact executor dispatch, stale/incompatible keys, scoped credentials, drain/recovery, and totals after pruning/database reopening.
- Python SDK/MCP: 40 tests passed, including rejection of a gateway-signed result attributed to a substituted executor.
- Frontend: 58 tests passed, including v5 canonical authorization and cryptographic receipt verification for a chosen worker.
- A real MCP stdio run discovered live workers, preserved a pinned quote, restarted its MCP process, and finished a three-step data workflow without duplicating the first admitted task. JSON/CSV bytes matched the expected output.
- Browser at `127.0.0.1:3041`: selected a real preview CPU worker, ran the numerical sample and 1.5 million synthetic risk scenarios, verified gateway/worker signatures, inspected actual operator activity, and drained/resumed the node. Heartbeats preserved its drain mode. Studio retained the source and exact quote across navigation, and the second job completed while another section was open.
- Receipt dialogs render through a body portal so transformed/animated workspace parents cannot position them outside the visible viewport.

The browser/API evidence is stored in ignored `.aperture/qa/`; the reproducible MCP command is:

```powershell
backend\venv\Scripts\python.exe scripts\check_mcp_stdio.py --output .aperture\qa\mcp-worker-route-NEW
```

These checks exercise actual reviewed host Python computation and local transport in OFF_CHAIN mode. They do not establish Docker isolation, remote worker honesty, a live hosted-model response or a Solana payout.
