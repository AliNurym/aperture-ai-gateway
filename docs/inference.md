# Model inference with owner-controlled compute

Aperture now supports two task runtimes through the same gateway: `python` CPU
workloads and `inference.chat` requests to operator-configured model servers.
This reconnects the original compute-gateway direction with task-level agent
permissions, bounded spending and attributable results.

## Configure Gemini or DeepSeek

The earlier Aperture used Gemini 2.0 Flash for its AI Sentinel code review. That
model shut down on June 1, 2026. The unified preview now supports the current
Gemini streaming API and DeepSeek's OpenAI-compatible chat-completions API. The
DeepSeek model defaults to `deepseek-flash`. Its dedicated Sentinel
adapter sends `thinking: {"type": "disabled"}` and requests
`response_format: {"type": "json_object"}` so the bounded output-token
allowance applies to a machine-readable report. Aperture still validates the
verdict, findings and source line references; malformed or truncated output
is rejected by the worker before it can become a successful inference artifact.
The signed task still records its failure for inspection, and the UI leaves the
review at manual review. A timeout or upstream HTTP error is not automatically
retried. See the [DeepSeek
chat-completions API](https://api-docs.deepseek.com/api/create-chat-completion/).

AI Sentinel can use either configured provider. DeepSeek is reserved for the
fixed, source-bound Sentinel prompt; generic DeepSeek chat requests are rejected
by the gateway. The owner reviews the provider and worker-published rate, then
signs the bounded request. The model result is advisory, not an execution
approval. The gateway's AST/source policy and a separate owner signature still
control compute. The completed review is attached to its source;
recovery verifies the original gateway and worker signatures, output hash,
manifest, and exact prompt before rebuilding the advisory. A changed source,
gateway, wallet, or invalid receipt cannot silently reuse it.

Model requests and Sentinel reviews pin a serving worker. The selected worker's
published rate, node ID and signing key are covered by authorization v5. When
the buyer selects automatic routing, the gateway chooses the lowest-priced
compatible worker and pins that exact route into the quote. The UI checks the
worker and rate before signing. The upstream model API bill remains a separate
gateway-operator expense; it is not hidden in the worker tariff.

For the local preview, add one provider key to the ignored `backend/.env` file
(the tracked `backend/.env.example` lists all supported settings), then run:

```powershell
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
notepad backend/.env
.\start_preview.bat
```

Set `DEEPSEEK_API_KEY` for DeepSeek, or `GEMINI_API_KEY` for Gemini. The launcher
reads only the allowlisted inference settings. Each provider key is passed only
to the authenticated inference worker that needs it; it is not sent to the
browser or gateway and is not written to provider configuration or task
receipts. Without a model key, the same workspace still starts with reviewed
CPU execution and explains how to connect a provider. Selecting a model and
signing sends the prompt to that provider; its separate API billing may apply.

DeepSeek defaults to model `deepseek-flash` and is exposed only inside the
source-review flow. It does not set task prices or approve execution. The
preview's local worker starts with a 1,000 lamports/second rate by default;
change `APERTURE_WORKER_RATE_LAMPORTS_SEC` or publish a different rate in
**Provide compute**. The operator pays DeepSeek separately. The preview remains
`OFF_CHAIN` and makes no Solana payment.

For a separate DeepSeek deployment, start from
`backend/inference-providers.deepseek.example.json`. Set the same absolute
`APERTURE_INFERENCE_CONFIG` path for the gateway and inference-only worker, and
expose `DEEPSEEK_API_KEY` only to that worker. The configuration pins DeepSeek
credentials to `api.deepseek.com`. For Gemini, use
`backend/inference-providers.gemini.example.json`; its native API uses the
`x-goog-api-key` header.

Ctrl+C stops only the services created by the preview launcher. State and logs
remain in `.aperture/inference-preview`. Another launcher cannot use the same
state directory concurrently. A temporary wallet key disappears when its tab
reloads; a retained task token still permits result recovery in that tab.

To verify request execution, repeated admission, fresh-client recovery, passport
revocation, and the retained CPU path without opening the UI:

```powershell
python scripts/inference_preview.py --check
```

This exits after the check and retains `evidence.json`, the quote, raw model
output, and signed receipt. It requires a configured model key or an operator-
approved endpoint and does not establish Devnet settlement or model quality.

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
messages, output-token request, task budget, runtime, owner and agent. Requesting
the quote sends the messages to the configured gateway, where its operator can
read them. The wallet signature authorizes the subsequent model request; the
model does not receive the prompt until the signed task is submitted. A source
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
