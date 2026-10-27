# Signed source reviews

AI Sentinel reviews one exact Python source. The model reports risks; the worker
owner publishes the execution price. A review and a Python run each have their
own quote, limits, authorization and signed receipt.

The fixed Sentinel prompt checks security and unsafe execution behavior. It
does not estimate compute, time, performance or price, and it cannot approve a
run. DeepSeek is asked for a JSON report; Aperture validates its verdict,
findings and source line references. A malformed report is left for manual
review. The worker rejects a malformed source-bound response before publishing
it as a successful result; the signed failure output remains inspectable. A
provider timeout or HTTP failure does not trigger another model request. The UI
asks for manual review after either a failed task or an invalid completed
report. A SAFE result means no obvious issue was found; it is not a safety
guarantee.

Before requesting a review quote, check the prompt shown in Studio. The quote
request sends that prompt to the gateway, where its operator can read it. Your
signature and submission authorize forwarding it to the selected model. A
source-bound review contains the full Python source, but the model request does
not execute it. Provider API usage is billed to the gateway operator's
configured model account and is separate from the worker owner's published
execution rate.

## In Compute Studio

Use **Review with AI Sentinel** to inspect the fixed, read-only source-review
request and approve its quote. Edit code in Studio before opening Sentinel. If
the editor changes while the review panel is open, the old quote is cleared and
the request must be reopened for the new source. When a review finishes, its
findings appear beside the source. A **Line** button selects that exact line in
the editor; it is disabled when the source changes or the reported line does
not exist.

**Export signed review** saves a JSON bundle containing the source, original
model output, signed quote and gateway/worker receipt. It excludes wallet keys
and task access tokens. **Import signed review** checks those signatures and
hashes against the connected gateway before restoring the source and report.
The import does not run code or send a new model request.

The same reviewing wallet must be connected before the report attaches to a
compute quote. A different wallet or gateway cannot silently reuse it. The
bundle can be verified after the original quote expires. Attaching it to new
compute also requires the completed review task to remain retained by that
gateway. Exporting evidence does not extend gateway retention.

## Python SDK

The SDK's dedicated catalog includes DeepSeek, which is absent from the general
inference catalog. Start with a configured `ApertureClient` and a passport
allowing both `inference.chat` and `python.execute`:

```python
import json
from pathlib import Path

source = "print(6 * 7)\n"
quote = client.quote_source_review("aperture-deepseek", source, max_tokens=1024)
# Explicit approval of this model request:
review_task = client.execute_inference(quote)
client.wait(review_task)
review = client.source_review(review_task.task_id, source)
Path("source-review.json").write_text(
    json.dumps(review["bundle"], ensure_ascii=False, indent=2), encoding="utf-8"
)

# A separate compute quote binds the review's source and receipt hashes:
compute_quote = client.quote_reviewed_job(source, review_task.task_id)
# Inspect its worker, published rate and spending limits before approving:
task = client.execute_job(compute_quote, source,
    parameters=compute_quote["workload"]["parameters"])
result = client.wait(task)
```

`source_review()` recovers an existing task without another model request.
Changed source, a conflicting `aperture_review` parameter, a failed review or
an unrecognized model verdict is rejected before a reviewed compute quote.
Existing named inputs and other compute parameters are preserved.

For offline verification of a browser export, supply pins from your trusted
deployment configuration:

```python
from aperture_client import verify_source_review_bundle

verified = verify_source_review_bundle(
    json.loads(Path("source-review.json").read_text(encoding="utf-8")),
    owner=client.owner, program_id=client.program_id,
    gateway_pubkey=client.gateway_pubkey, network=client.network,
    treasury=client.treasury,
)
```

Offline verification checks source provenance, signatures and output bytes.
Devnet settlement finality still needs the independent RPC checks performed by
`client.wait()`. A signed `SAFE` verdict remains an advisory, not a guarantee of
safe execution or proof of model identity.

## MCP

The same flow is available to an agent host:

1. `list_sentinel_providers` finds configured review models.
2. `quote_source_review(provider_id, source)` prepares the fixed review request.
3. `start_inference_task(quote_id)` admits that exact request within local limits.
4. `get_source_review(task_id, source)` returns a verified report and reference.
   Poll again when `ready` is false. It also works after restarting the MCP host
   with the same agent key and deployment configuration.
5. `quote_reviewed_job(source, review_task_id)` prepares separate Python compute.
6. `start_compute_job(quote_id)` admits it; `get_python_task` verifies its result.

Local execution must be enabled and the passport must permit each runtime.
MCP summaries exclude task capabilities and the full exported bundle. The SDK
or browser can export the portable evidence when the owner wants a file.

## Reproducible local check

`backend\venv\Scripts\python.exe scripts\check_mixed_workflow.py` starts isolated
gateway/worker processes and a synthetic HTTP model server. It checks nine mixed
workflow tasks, four additional source-review/compute tasks, checkpoint recovery,
replay without duplicate model requests, exact Unicode statistics and rejection
of a changed reviewed source. Eight fixture model requests serve those thirteen
tasks. No upstream API key or Solana payment is used.
