# Model inference with owner-controlled compute

Aperture now supports two task runtimes through the same gateway: `python` CPU
workloads and `inference.chat` requests to operator-configured model servers.
This reconnects the original compute-gateway direction with task-level agent
permissions, bounded spending and attributable results.

## Reconnect the original Gemini model

The earlier Aperture used Gemini 2.0 Flash for its AI Sentinel code review.
That model shut down on June 1, 2026, so the gateway now offers the current
Gemini Generate Content streaming API and defaults to `gemini-3.8-flash`.
The model appears in the provider selector and runs through the same owner
quote, wallet signature, capability check, worker and receipt flow as the rest
of Aperture. The gateway's AST/source policy remains the enforcement check;
Gemini output is an inference result, never a security verdict.
AI Sentinel filters the provider list to the native Gemini route. It does not
fall back to the local fixture or another OpenAI-compatible model; without a
 Gemini offer, the review panel explains how to configure the preview and sends
no source to a model.

In Compute Studio, **Request AI Sentinel code review** opens a review panel beside
the Python editor. The source stays visible while the owner reviews the selected
model, prompt and price, then signs the quote. The result is an advisory report;
it does not replace the gateway's AST/source policy, approve execution, or prove
that code is safe. The full prompt and result are covered by the existing
inference receipt. The report stays attached to its source and is marked stale
if that source changes. For a matching report, **Review compute price & limits**
continues into the existing Python quote and execution flow. The report never
skips the gateway policy, quote, or separate owner signature for code execution.

For the local preview, copy the example environment file and add your key:

```powershell
Copy-Item backend/.env.example backend/.env
notepad backend/.env
.\start_preview.bat
```

Fill in `GEMINI_API_KEY` in `backend/.env`. This file is ignored by Git. The
unified launcher reads only `GEMINI_API_KEY`, `APERTURE_GEMINI_MODEL`, and
`APERTURE_GEMINI_RATE_LAMPORTS_SEC` from it. It starts the authenticated
inference worker alongside the reviewed CPU worker. The API key is passed to
that worker; it is not sent to the browser or gateway and is not written to
provider configuration or task receipts. Without a key, the same workspace
still starts and explains how to connect Gemini. There is no local-model
fallback. Selecting Gemini and signing a request sends that prompt to Google's
API and may incur Google's separate API charges.

To use a different current model or displayed Aperture time tariff, change
`APERTURE_GEMINI_MODEL` and `APERTURE_GEMINI_RATE_LAMPORTS_SEC` in
`backend/.env` before starting.
The default tariff is a demo value of 1,000 lamports per elapsed second. It does
not pay Google's token invoice, and the preview remains `OFF_CHAIN` with no
Solana payment.

For a separate deployment, copy
`backend/inference-providers.gemini.example.json` into the operator's provider
configuration. Set `APERTURE_INFERENCE_CONFIG` for the gateway and the
inference-only worker, and expose `GEMINI_API_KEY` only to the worker. Keep the
provider protocol as `gemini_generate_content`; it uses Google's native SSE API
and `x-goog-api-key` header instead of the OpenAI chat-completions format.

Ctrl+C stops only the services created by this launcher. State and logs remain
in `.aperture/inference-preview`. Another launcher cannot use the same state
directory concurrently. The temporary wallet's private key disappears when its
tab reloads; a retained task token still permits result recovery in that tab.

To verify model execution, repeated admission, fresh-client recovery, passport
revocation, and the retained CPU path without opening the UI:

```powershell
python scripts/inference_preview.py --check
```

This exits after the check and retains `evidence.json`, the quote, raw model
output and signed receipt in the preview state directory. It requires Gemini or
an operator-approved hosted endpoint and never claims Devnet settlement or model
quality from an off-chain run.

## Use an operator-hosted model endpoint

For an operator-approved OpenAI-compatible endpoint that supports streamed chat completions:

```powershell
python scripts/inference_preview.py --base-url http://127.0.0.1:8081/v1 --model YOUR_MODEL_ID
```

For a separate deployment, copy `backend/inference-providers.example.json` to
operator-owned configuration, update the actual endpoint/model/tariff, and set
the absolute `APERTURE_INFERENCE_CONFIG` path for both gateway and inference
worker. Restart both after changing an offer. Each entry represents one
provider/model offer, with a unique ID. Add `api_key_env` only when the endpoint
requires a credential; the corresponding value belongs in the worker's
environment. Never put a key in `base_url`, the JSON file or browser code.

Start the adapter with the same worker authentication and gateway configuration
as other workers:

```powershell
python backend/worker.py --inference-only
```

This worker does not require Docker and cannot claim arbitrary Python jobs.
The CPU worker cannot claim inference jobs. An offer must match the worker's
published configuration exactly before the gateway dispatches it. Catalog
worker counts report recent registrations, not verified model-server health.
Remote model endpoints require HTTPS; plain HTTP is permitted only on loopback.

## Permission and authorization

Existing passports default to `python.execute`. Inference requires the separate
`inference.chat` capability. The owner can authorize either or both in the
console or SDK. Updating a passport does not silently expand an existing
signed quote. Revoked, expired, over-budget or incompatible capabilities are
rejected before dispatch. On-chain policies bind the capabilities through the
owner-approved metadata hash; the gateway interprets capability names.

An inference quote binds provider ID, model, endpoint digest, published tariff,
messages, output-token request, task budget, runtime, owner and agent. A source
commitment includes the canonical request digest, so the existing Solana task
source hash also commits to the inference request. The frontend and SDK rebuild
the request before signing. Changing the prompt, provider or token limit needs a
new quote and signature.

`POST /inference/quotes` prepares a quote and an `execution_request` containing
the committed source and parameters. Sign its canonical `message` and submit
that exact request through the existing `POST /execute`. Repeating an admitted
quote recovers the same task. Result polling, cancellation, retained task
history and receipts use the existing endpoints.

## Python SDK and MCP

```python
client.passport(owner_keypair, capabilities=["inference.chat"],
                max_cost_lamports=100_000, max_runtime_seconds=30)
offers = client.inference_providers()
quote = client.quote_inference(
    offers[0]["id"], [{"role": "user", "content": "Explain a compute budget."}],
    max_tokens=128, max_cost_lamports=100_000, max_runtime_seconds=30,
)
task = client.execute_inference(quote)
result = client.wait(task)  # verifies the gateway/worker signatures and raw output
```

Construct `client` with its owner/agent identity and deployment pins as described
in `python-agent-sdk.md`. The local MCP server adds `list_inference_providers`,
`quote_inference` and `start_inference_task`. Existing task polling, cancellation,
listing and recovery tools also handle inference. Execution remains subject to
the MCP server's explicit execution flag and local spending/runtime ceilings.

## Billing and trust boundaries

- **Tariff:** operator-set lamports per elapsed second, including upstream
  waiting. This version reuses the existing time-bounded payment-channel
  contract. It does not estimate or settle a model vendor's token bill.
- **Token limit:** sent as `max_tokens` to the model server. Upstream compliance
  and token counts are not independently proven. The adapter also bounds stream
  size, process duration and captured output.
- **Settlement:** off-chain preview has no payment. The updated Devnet source
  routes 100% of a confirmed bounded task charge to the authenticated worker
  assigned at start. Deployment and a real worker payout still need verification.
- **Providers:** offers are configured by the operator, with explicit user
  selection. There is no permissionless discovery or automatic failover, and
  Aperture does not directly settle the upstream model vendor's bill.
- **Privacy:** after authorization the selected provider receives the prompt.
  Prompts and results are retained in local gateway/worker task state. Credentials
  stay in the adapter environment and are not sent to the browser or job code.
- **Cancellation:** Aperture stops its adapter subprocess and closes its HTTP
  connection. A remote operator may continue processing or billing; Aperture
  cannot guarantee upstream cancellation or enforce that operator's invoice.
- **Recovery:** admission and receipt delivery are idempotent. An interrupted
  inference is recorded as interrupted and is not automatically sent again.
- **Evidence:** signatures bind the reported output, source commitment and
  authorized request. They do not prove the advertised model ran, GPU execution,
  confidentiality at the provider, or correctness of the answer.

Next marketplace work is independent provider discovery, measured health-based
selection, and a verified live worker-payout run. Direct settlement to upstream
model vendors needs its own accounting and payout design. Token-priced billing
needs an explicit metering design; relabeling the current time tariff would not
implement it.

## Verification, 23 October 2026

Automated checks passed: 99 backend tests (two skipped), 39 SDK/MCP tests, 55
frontend tests, frontend lint and production build, and 17 Rust contract tests
with `cargo fmt --check` and `cargo check`. Local HTTP fixtures verify the
Gemini SSE adapter and signed gateway receipt path without calling Google or
spending API credits.

Run `python scripts/check_inference_preview.py` for a process-level check of the
configured-provider adapter, authenticated inference worker, signed gateway
receipt, SDK recovery, agent revocation and reviewed CPU worker. It uses a local
SSE fixture that returns a fixed synthetic sentence; it verifies transport and
task integration, not a model's identity or answer quality. No API key or
external model endpoint is used, and the run stays `OFF_CHAIN`.

The combined check passed: the fixture received one streamed request, retrying
the signed admission returned the same task, a fresh SDK client recovered the
same verified output, revocation blocked a new quote, and the CPU worker returned
`42`. The receipt remained `OFF_CHAIN`; the report labels model quality as
unevaluated and the 100% worker split as source-only evidence.

The unified preview was exercised without a model key. Its gateway reported
`OFF_CHAIN`, zero model offers and one authenticated CPU worker. The SDK signed
and ran the exact default Compute Studio math sample, returned
`Mean root score: 29.817865`, and verified its receipt. A browser check at
1440×980 and 390×844 opened Compute Studio, switched to Model inference, checked
the no-provider guidance, and found no horizontal overflow or console errors.
The screenshot and local `/health`, provider-catalog and worker-catalog checks
confirm that the no-key state sends no model request. A separate local fixture
startup confirmed that two configured offers share one inference worker.

The browser check used a temporary Playwright install because the Browser
plugin was unavailable. `GEMINI_API_KEY` was absent, so no live Gemini request
was sent. The local Solana validator test was not run because
`solana-test-validator` was unavailable in this Windows environment. Rust unit
tests cover worker-bound payout accounting; a local-validator balance check,
live worker payout, Docker execution and Devnet settlement still need their own
verification. The 100% worker-payout source has not been deployed.

An earlier development build exercised a local llama.cpp model. That is
historical evidence only: local development fixtures remain hidden from the
public model catalog and worker directory. The supported preview paths are
Gemini or an explicitly operator-approved OpenAI-compatible endpoint.
