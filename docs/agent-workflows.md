# Agent data jobs and durable workflows

Aperture accepts immutable input files, job parameters and named result files.
An agent can batch a dataset, run dependent steps, join verified results and
resume the same workflow journal. Data passes through private object references
instead of being copied into the model's context.

## Useful first workflow

The CSV pipeline in examples/batch_data_workflow.py:

1. Streams a caller-selected CSV into bounded batches.
2. Stages each batch as a private immutable input.
3. Runs category summaries with invalid-row accounting.
4. Combines summaries through a tree with at most 16 inputs per join.
5. Produces report.json and categories.csv.

The dataset requires category and amount columns. The aggregation is an example
template; the job and workflow APIs accept caller-provided source and parameters.
Configure the existing SDK deployment and delegated agent key. The owner must
already have issued a suitable passport and, on Devnet, funded the channel.
The pipeline does not create a passport, increase its limits or deposit SOL.

    python examples/batch_data_workflow.py records.csv --batch-rows 5000 --workflow-budget-lamports 2000000

Each step defaults to a 100,000-lamport cap and 60-second runtime. The sum of all
step caps, including joins, must fit the workflow ceiling. These are authorization
limits, not a prediction of measured compute cost.

Rerun with the same journal to continue it. A changed plan, input reference,
deployment, key identity or rate ceiling requires a new journal. Never delete an
uncertain journal and blindly submit a replacement workflow.

The CSV staging plan retains every uploaded batch as it finishes. Restart checks
the dataset digest, batch size and execution identity before reusing references.
HTTP 429 pauses for the gateway's Retry-After interval within a bounded wait;
task admission repeats the same authorization before its expiry.

## Browser workspace

Start the complete Windows preview with `start_preview.bat`. It prepares the
console, gateway and exact-source reviewed local worker together in OFF_CHAIN
mode. Choose Temporary key for a memory-only signing identity, or a persistent
wallet if further approvals must survive reload. State remains in the ignored
`.aperture/preview/` directory. This path provides real host CPU computation,
without Docker isolation or a Solana payment.

For a first chain without selecting files, connect a wallet and choose **Use
example data** in Agent workflows. Two synthetic CSV batches travel through
the normal signed upload, quote and execution APIs. Each compute step still
requires explicit approval; its results are produced by the worker.

Compute Studio accepts caller-selected files and JSON parameters. The dataset
template produces report.json and categories.csv. File uploads need a wallet
message signature; starting a job needs a separate approval of its source,
input hashes, parameters and spending bounds. A downloaded result must match its
signed size and SHA-256. Inputs remain private to the signing wallet.

Agent workflows accepts selected CSV batches or immutable input references,
builds a bounded batch/merge plan and exports it for the CLI or
prepare_compute_workflow. In browser execution, the connected wallet acts as both
owner and agent. Prepare the plan, review the first quote and explicitly sign
each step. Verified outputs supply later inputs; later steps do not receive an
automatic wallet signature. Each selected CSV is one batch. Automatic splitting
of a larger dataset is available through examples/batch_data_workflow.py.

The browser keeps one private workflow journal in sessionStorage, including the
exact signed admission request and task recovery capabilities. Admission is
refused if that journal cannot be saved. Reloading the same tab can restore an
accepted task and resume monitoring; another step still needs a new explicit
review and approval. A lost admission response retains the original request.
Stop prevents later admissions and recovers an uncertain task from signed
history before requesting cancellation. It does not replay execution after a
stop request. Keep the tab open until its jobs finish and needed results are
downloaded: closing it removes the local journal while accepted gateway tasks
can continue. Use the SDK/MCP host for unattended chains and a durable disk
journal.

The executing identity must be the exact owner/agent pair that uploaded the
files. Studio and browser workflows use the connected wallet as that pair; a
dedicated MCP agent uploads its own files. References do not grant access across
identities. Input drafts are scoped to the wallet and deployment; switching
wallets does not move a prepared workflow or admit work for another owner.
Downloaded result bytes must match their verified receipt size and SHA-256.
JSON, CSV and text files up to 1 MiB can also be opened directly in the browser
after receipt and byte verification. Category reports show accepted/skipped
counts and totals; tables show up to 100 rows and 32 columns. Download for full
contents. Preview renders text and tables without executing file content.

Studio retains its latest accepted task in the same tab after completion.
Reloading fetches and verifies the original result again before its files can
be reopened. This browser checkpoint is not an agent disk journal: closing
the tab can discard it, and a lost temporary private key cannot approve later
steps. Workflow execution uses its separate private tab journal.

## Run an exported plan from the CLI

examples/run_workflow.py executes any validated version 1 workflow plan, including
the JSON exported by Agent workflows. The file must contain exactly version,
max_cost_lamports and steps. Sources, parameters, data dependencies, input names,
cycles and spending bounds are checked locally before signing or executing.
The gateway still applies its source policy and the worker must support the
selected sources. The reviewed local preview accepts only its built-in templates.

Review the declared maximum in the JSON, then supply that exact number explicitly.
The CLI refuses a different budget and never increases a step limit or passport.
These commands assume the selected plan declares a 200,000-lamport maximum:

    python examples/run_workflow.py aperture-workflow.json --workflow-budget-lamports 200000 --prepare
    python examples/run_workflow.py aperture-workflow.json --workflow-budget-lamports 200000 --output .aperture-runs/results

Use a Python environment containing the backend dependencies; on Windows the
repository environment can be selected with backend\venv\Scripts\python.exe.
The command uses the repository SDK directly. It does not start a worker or
gateway, fund a channel, create a passport or request a separate owner key.
Only the explicitly configured execution key is used.

Execution requires these existing deployment and delegated-key environment values:

- APERTURE_GATEWAY_URL: the configured HTTPS gateway, or HTTP on loopback.
- APERTURE_OWNER_PUBKEY: the owner that delegated the compute allowance.
- APERTURE_AGENT_KEYPAIR: a private local Solana CLI keypair file for that agent.
- APERTURE_PROGRAM_ID and APERTURE_GATEWAY_PUBKEY: the pinned deployment keys.
- APERTURE_NETWORK: explicitly devnet or off_chain.
- APERTURE_TREASURY_PUBKEY: required for Devnet; pin the deployment treasury.
- SOLANA_RPC_URL: optional independent Devnet or local-validator RPC.

The agent needs an existing suitable passport; Devnet also needs an idle funded
payment channel. Object references belong to the exact owner/agent pair that
uploaded the bytes. Browser Studio uploads use the connected wallet as both
owner and agent. A delegated CLI/MCP key cannot consume those references merely
because it shares the owner: upload the inputs with that delegated key before
building its plan. Configure the same deployment, network and identity on resume.

The default private journal is .aperture-runs/workflows/<plan-sha256>.sqlite3.
An explicit --journal selects another durable path. Rerun the same command to
continue that journal; saved results are verified before reuse and completed
steps are not admitted again. Do not delete an uncertain journal to start over.
An intentional changed plan needs its own journal. Preparing and checking local
status require no agent key and contact no gateway:

    python examples/run_workflow.py aperture-workflow.json --workflow-budget-lamports 200000 --status

Progress prints step state, counts and task IDs. Local status reflects the last
durable checkpoint, so a running record can be stale after an interrupted host.
Source, task capabilities, quotes, keys and raw task logs are not printed or
exported. Keep the journal private because recovery capabilities are stored there.
--max-rate-lamports defaults to 25,000 and is pinned in the journal.
--wait-seconds defaults to 600 for each task; it changes waiting, not runtime caps.

All artifacts from every terminal branch are downloaded by default. Signatures,
sizes and SHA-256 are verified through the SDK. Each sink has a distinct numbered
step directory under --output; the default root is
.aperture-runs/results/<first-24-plan-hash-characters>. Existing files are reused
only when size and digest match the signed result. Different bytes, symlinks and
filename collisions are refused. Files are staged privately and published
atomically without replacing another file. Only result bytes are exported.

Ctrl+C, SIGTERM and Windows Ctrl+Break stop new admissions and request cancellation
of the current task. If interruption occurs during admission, bounded signed
history recovery searches for that original authorization and cancels the found
task; it never submits a replacement. --cancel-wait-seconds defaults to 90 and
can be 1 to 600. The CLI creates no child processes. It reports whether terminal
cancellation was confirmed; when confirmation fails, retain the journal and
recover the same task before starting new work. A terminal failed or cancelled
step cannot be rerun inside the same workflow; inspect its retained result and
prepare an intentional revised plan. Interrupted downloads can resume from the
completed journal without new compute admissions.

## SDK jobs

    data = client.upload_input("records.csv")
    code = 'from aperture import read_csv, write_json\ncount = sum(1 for row in read_csv("records.csv"))\nwrite_json("count.json", {"rows": count})\n'
    quote = client.quote_job(code, inputs=[data], parameters={},
                             max_cost_lamports=100000, max_runtime_seconds=60)
    task = client.execute_job(quote, code, inputs=[data], parameters={})
    result = client.wait(task)
    output = client.download_artifact(task, result["receipt"], "count.json")

The in-job aperture module provides parameters, read_bytes, read_text,
read_json, streaming read_csv, and write_bytes, write_text, write_json, write_csv.
Only named inputs approved in the job manifest are available. Result frames are
captured by the coordinator, stored separately from logs and bound to the worker
and gateway receipts. No writable host output mount is exposed to containers.

## Workflow dependencies

WorkflowRunner accepts a DAG. Steps contain id, source, inputs, parameters,
max_cost_lamports, max_runtime_seconds, and optional depends_on. An input is an
immutable object descriptor or a preceding result:

    {"from_step": "prepare", "artifact": "prepared.json"}

The later job consumes that file with its original name. Dependencies are
checked for cycles and unknown steps before work starts. Failed or unverified
steps withhold downstream admission. Quote/admission intent/task capability and
verified result commit to the local journal. Ambiguous admission searches signed
task history and resumes the original task.

Branches currently execute serially on one owner's payment channel. Parallel
execution across channels is not implemented by this runner.

## MCP

New tools:

- upload_compute_input: stage agent-provided bytes, up to 1 MiB inline.
- quote_compute_job / start_compute_job: run a source/data/parameter-bound job.
- prepare_compute_workflow: validate and retain a DAG within local ceilings.
- start_compute_workflow: start or resume it in the background.
- get_compute_workflow: return progress, task IDs and final artifact references.
- cancel_compute_workflow: stop new admissions and request active cancellation.
- read_compute_artifact: retrieve a verified result file as base64, up to 1 MiB.
- get_compute_storage: inspect this agent's private retained files and quota.
- release_compute_object: explicitly discard selected retained bytes.

Existing get_python_task returns signed artifact references after verification;
these can feed another quote_compute_job. The SDK handles caller-selected files
up to 64 MiB without sending their bytes through an LLM.

Configure durable workflow storage and a total ceiling explicitly:

    APERTURE_MCP_WORKFLOW_DIRECTORY=C:\aperture-agent\workflows
    APERTURE_MCP_MAX_WORKFLOW_COST_LAMPORTS=2000000

Each step also obeys APERTURE_MCP_MAX_COST_LAMPORTS,
APERTURE_MCP_MAX_RUNTIME_SECONDS and APERTURE_MCP_MAX_RATE_LAMPORTS. Execution
requires APERTURE_MCP_EXECUTION_ENABLED=true. Preparing a plan does not start it.
Keep journals private: they retain task capabilities but never private keys.
After MCP restart, explicitly start the same workflow ID to continue its journal.

## Authorization and bounds

Execution authorization v3 binds the existing source, price, budget, runtime
and deployment fields plus the canonical manifest digest: runtime/version,
source hash, immutable input descriptors and parameters. Source-only v2 remains.

Inputs require a short-lived agent signature for an upload capability. Streamed
uploads must match their authorized byte count and SHA-256. Workers fetch only
inputs assigned to their active lease. Result publication requires the owning
worker and matching lease. Downloads require the task capability; the SDK checks
signatures, descriptor bounds and downloaded bytes. Later jobs may use only
objects matching their owner/agent.

Limits: 64 MiB total input per job, 16 input files, 8 MiB per result, 16 MiB total
results, 16 result files. Per owner/agent storage is 256 MiB/512 objects; gateway
storage is bounded to 2 GiB/10,000 objects. Use storage_usage() and
release_object(reference) through the SDK, or the storage MCP tools, after
saving needed results. Active tasks and unexpired unused quotes block removal.
The exact file reference is signed and checked before deletion. A small retained
deletion record allows the same release to return success for seven days
(bounded to the newest 4,096 records); it contains no file bytes. Historical
receipts remain signed metadata, while released files cannot be downloaded or
used again. Files & results in the browser shows this wallet's private file
list and real quota through a signed read. Select a specific file, review its
hash and size, then sign its release. Released inputs are also removed from
Compute Studio's selections. Delegated agents inspect their separate storage
through the SDK/MCP tools.

The on-chain receipt retains its source hash/payment limits. The expanded
input/output manifest is attested by the agent, worker and gateway. This change
does not introduce on-chain proofs of input execution or correct computation.

## Local demonstration

    backend\venv\Scripts\python.exe scripts\demo_workflow.py --output .aperture-runs\demo --rows 50000

This uses synthetic data and ephemeral keys, a disposable gateway and a local
worker allowing only the two reviewed templates. The orchestrator interrupts
after admission but before the task ID is committed to the journal, recovers
the same task through signed history, and downloads verified files.
Child processes close afterward. It is real local CPU execution with OFF_CHAIN
receipts; Docker isolation and Solana payment are not claimed. Full Docker/Devnet
verification and automatic browser chain execution remain separate work.

For interactive local use, scripts/preview_workflows.py starts a gateway and
worker restricted to the reviewed built-in sources. Select a separate local
database path. The worker is trusted local CPU execution and edited source is
rejected; this preview does not provide Docker isolation or on-chain payment.
The starter prints its public gateway key and program ID. Match the frontend's
VITE_APERTURE_GATEWAY_PUBKEY and VITE_APERTURE_PROGRAM_ID to these public values,
and use its gateway URL for VITE_API_URL. Keep the gateway pin enabled. The
preview signer persists in the private state directory across restarts.
