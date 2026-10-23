# Connect an AI agent with MCP

Aperture's local MCP server connects an MCP-compatible agent host to bounded
Python compute, data workflows, and optional operator-configured model
inference. The host supplies the agent; Aperture supplies the task gateway,
execution and receipt verification. Inference is sent to the configured model
operator after the owner-approved task is admitted and may incur separate
provider charges.

The server exposes Python, inference, data-job and workflow tools:

See [Agent data jobs and workflows](agent-workflows.md) for immutable files,
batch processing, dependent steps and durable background workflow control.

The current server advertises 22 tools. For a chain approved in the console,
call `get_assigned_workflows`, `start_assigned_workflow(workflow_id)` and
`get_assigned_workflow_progress`. The owner approves the exact CSV plan and
total maximum once; the configured host executes it within its local ceilings
and retains its journal. Full plans and dataset bytes stay on the host/gateway,
while the model receives compact workflow metadata. Follow the
[receiver setup](agent-workflows.md#approve-a-chain-once-and-receive-it-on-the-agent-host)
for key creation, console approval, observation, stop and recovery.

- `quote_python` analyzes a source-bound quote without starting a task.
- `start_python_task` runs the exact source held for that quote.
- `list_python_tasks` lists recent task metadata for the configured owner and
  agent keys. Follow its `next_cursor` to page through older retained tasks.
- `resume_python_task` reacquires access to an existing task without submitting
  it again or creating another charge.
- `get_python_task` polls and returns output only after the SDK verifies the
  gateway and worker evidence, and independently checks the Devnet receipt
  when the task is billed on Devnet.
- `cancel_python_task` requests cancellation; poll afterward for the final
  receipt.
- `list_inference_providers` reads the operator-configured model offers without
  exposing endpoint URLs or credentials.
- `quote_inference` binds the provider, messages, output limit, budget and
  runtime to a quote. It requires the separate `inference.chat` passport
  capability.
- `start_inference_task` admits that exact signed quote. The selected model
  operator receives the messages only after admission; poll the task with
  `get_python_task` for the verified result and receipt.

Inference billing in Aperture uses the operator's elapsed-time tariff, not
token billing. The model vendor may charge its own API usage separately. Keep
provider credentials in the inference worker environment; they do not belong
in the MCP host's browser-visible offer catalog. See the [inference setup and
trust boundaries](inference.md) before enabling the `inference.chat` capability.

## Install

Create a dedicated environment and install the optional MCP extra:

```powershell
python -m venv .venv-agent
.\.venv-agent\Scripts\python.exe -m pip install -e ".\sdk[mcp]"
```

Use Python 3.11 or newer. The SDK MCP extra installs the official MCP Python
SDK v2 line. The adapter uses the local stdio transport, so the host launches
the process and talks to it over stdin/stdout.

## Prepare delegation

Create a distinct agent keypair and keep its private key file on the machine
that runs the MCP host. The MCP server refuses to start if this key matches
`APERTURE_OWNER_PUBKEY`, so it cannot silently use the owner's direct-execution
path. From the owner-connected **Agents** page, issue a passport for the agent
public key with a per-task cost cap, runtime cap, total allowance, and expiry.
The MCP server cannot issue or expand a passport and does not need the owner's
private key. For Devnet, the owner must separately fund an idle payment
channel; the server never deposits SOL.

Start with `APERTURE_NETWORK=off_chain` against a configured development
gateway if you want to check the tool flow without a chain payment. For live
Devnet work, use public keys from the deployed v2 protocol configuration,
provide the Devnet treasury and RPC URL, and keep the owner-issued passport
limits as low as the job allows.

## Configure the agent host

Add a local server entry to an MCP host configuration that supports the common
`mcpServers` shape. Use the full path to the Python executable from the
environment created above:

```json
{
  "mcpServers": {
    "aperture": {
      "command": "C:\\path\\to\\aperture\\.venv-agent\\Scripts\\python.exe",
      "args": ["-m", "aperture_client.mcp_server"],
      "env": {
        "APERTURE_GATEWAY_URL": "http://127.0.0.1:8000",
        "APERTURE_OWNER_PUBKEY": "<owner-public-key>",
        "APERTURE_AGENT_KEYPAIR": "C:\\secure\\agent.json",
        "APERTURE_PROGRAM_ID": "<deployed-program-id>",
        "APERTURE_GATEWAY_PUBKEY": "<configured-gateway-signer-public-key>",
        "APERTURE_NETWORK": "off_chain",
        "APERTURE_MCP_MAX_COST_LAMPORTS": "100000",
        "APERTURE_MCP_MAX_RUNTIME_SECONDS": "30",
        "APERTURE_MCP_EXECUTION_ENABLED": "false"
      }
    }
  }
}
```

Host configuration paths and field names vary. Replace the placeholders and
use `https://` for a remote gateway. For Devnet also set
`APERTURE_TREASURY_PUBKEY` and `SOLANA_RPC_URL`. `APERTURE_MCP_MAX_RATE_LAMPORTS`
defaults to 25,000 lamports per second; pending quote and tracked task counts
have bounded defaults and can be changed with `APERTURE_MCP_MAX_PENDING_QUOTES`
and `APERTURE_MCP_MAX_TRACKED_TASKS`.

The execution flag defaults to `false`: the host may request a quote, but task
admission is refused until the local operator changes it to `true`. Set that
flag only after checking the agent passport, MCP ceilings, network and payment
channel. Tool arguments may lower the configured cost/runtime ceilings but
cannot raise them. The gateway still checks the signed owner-issued passport.

## Agent workflow

Ask the agent host to use Aperture when it needs a bounded Python computation:

1. Call `quote_python` with the source and limits no higher than the configured
   ceilings. Review the source hash, estimated rate, charge cap and runtime.
2. Call `start_python_task` with that returned `quote_id`.
3. Poll `get_python_task` using its `task_id` until `ready` is true. The final
   response includes the execution status, output, charge and signed receipt.
4. If needed, call `cancel_python_task`, then poll for the final receipt.

For example, ask the agent: “Use Aperture to calculate the 95th-percentile
loss for this small synthetic dataset. First show me the quote and keep the
maximum at 50,000 lamports and 10 seconds. Start only after I approve the
quoted source, then return the verified output and settlement status.” The
host may require its own tool-approval setting; that UI approval is separate
from the owner-issued passport and gateway enforcement.

The MCP process stores quote source and task access capabilities only in
memory; it never returns them to the model or writes them to disk. If the host
restarts the server, call `list_python_tasks` (pass a previous page's
`next_cursor` as `cursor` when needed) and then `resume_python_task` with the
task ID. The SDK signs a fresh, one-use request with the configured agent
key, and the gateway returns that task's capability only to the local MCP
process. Recovery does not repeat admission. Completed jobs remain recoverable
while they are in gateway history; older completed records are removed according
to `APERTURE_MAX_COMPLETED_TASKS` (default 1000). The original source is not
returned by task history. Tracked task and result counts are bounded so a
long-lived process cannot grow without limit.

The receipt verifies signed attribution, hashes, budget and settlement
evidence. It is not proof that remote hardware faithfully executed the source.
The worker is isolated by the configured task container, but the coordinator
still controls the host Docker daemon; use a dedicated host or VM for mutually
untrusted operators.
