# Aperture historical integration map

This maps product ideas from the local Git history to the current workspace. It distinguishes implemented paths from old demo behavior and remaining roadmap work.

| Historical change | What it contributed | Current integration |
| --- | --- | --- |
| `a718ad6` · 2026-04-03 13:34:45 +05:00 | Initial FastAPI / frontend / Anchor architecture. The old contract recorded a balance and burn rate; its `open_channel` did not transfer the declared deposit into escrow. | Current channel code performs explicit funding and settlement operations. The historical account fields alone are not payment evidence. |
| `e44dea8` · 2026-04-06 15:40:40 +05:00 | Quantum Pricing, Aperture Penalty Scale (APS), script import and a compute dashboard. | Source analysis remains an execution-policy check. Following the owner's later product decision, task prices now come exclusively from the selected worker owner's published rate. AST, APS, Sentinel and SOL/USD do not set that price. The signed quote binds the worker and its rate. |
| `d659fc8` · 2026-04-07 00:31:21 +05:00 | Gemini-backed AI Sentinel, Robin Hood rate calibration, a wallet prompt and a single-page compute dashboard. The dashboard also showed a visual balance burn. | Sentinel now opens inside the task inspector beside the exact source. A completed matching Gemini review can be attached to the next compute manifest as `aperture_review`; the gateway checks its owner, exact prompt/source and receipt hash before issuing a quote. The owner signs that manifest digest, and the compute receipt binds it. The gateway source policy and compute approval remain separate. |
| `8bd5c54` · 2026-09-24 | Treasury-backed Solana payment channels. | That build settled the capped charge to the configured treasury. The newer 0.5.0 source pins the assigned worker and sends it the full charge; deployment and live payout evidence are still pending. |
| `d659fc8` · 2026-04-07; `191047b` · 2026-09-11 23:18:38 +05:00 | April's provider toggle and counters were component-local. September's provider view fetched `/active_nodes` and `/stats`, but supplied fallback values for tasks, SOL, VRAM and TFLOPS. The hardware selector in `Gateway.jsx` was not sent to `/execute`. | **Provide compute** uses authenticated worker operations and durable task/earning totals. **Use this worker** binds the chosen worker ID and key to authorization v5, dispatch and receipt verification. Unreported hardware figures stay unavailable. See [worker-market.md](worker-market.md). |
| `819e952` · 2026-09-26 23:54:23 +05:00 | Rebuilt the workspace and deleted `Gateway.jsx`, `ProviderDashboard.jsx` and the previous `HowItWorks.jsx`. Consumer, provider and pricing presentation were interrupted by this rewrite. | The current market reads authenticated worker heartbeats and configured model offers. The shared workbench now presents Python, model inference and workflows together, with source review, route, price and result evidence in the task journey. |
| `e6213b8`, `13f0ce0` · 2026-10-04 | Agent workspace, result previews, Compute Studio and the motion system. | These remain in the current shell as Agent workflows, Python compute, file previews and navigation motion. Model inference now shares their gateway, task limits and receipt flow. |
| `786bfdf`, `2cd1277` · 2026-10-05 | Receipt inspection, attestation entry point, command palette and editor shortcut. | Receipt verification and the command palette remain available across the unified workspace. |
| `c2db95a` · 2026-10-07 | Aperture v2 console, Python SDK, MCP tools and pitch materials. | This remains the current gateway and agent integration foundation. The inference runtime adds a separate `inference.chat` capability without treating ordinary Python source as model work. |

## Current limits

On 2026-10-24 the GitHub connector returned `main` at `1172a232726de9d9fda2ed5616840775f15e32b2`, matching local HEAD before this integration. The 79-commit history begins on 2026-04-03; that reference head is dated 2026-10-07 21:02:33 +05:00. Dates above use the recorded +05:00 timestamps. This comparison records the historical reference and the integration delivered alongside it.

The source-review link is verified by API regressions and a native Gemini SSE **HTTP fixture** followed by real trusted-local Python execution. That fixture proves request, signature and manifest linkage; it is not a live Google model response. The running preview still needs a configured Gemini key and worker for live model review. Downloading a compute task manifest exposes the review reference whose hash is covered by the compute receipt.

The unified route supports operator-configured model offers, authenticated inference workers, authenticated CPU workers, owner-signed budgets, and signed result evidence. The directory is operator-managed rather than permissionless. The 0.5.0 contract source binds the selected worker key and routes 100% of a confirmed task charge to that key; no live deployment has yet verified the path. The gateway does not directly pay upstream model API vendors. Signed receipts attribute reported output to a worker key but do not prove model identity or answer correctness.

For provider setup and model details, see [inference.md](inference.md). For current product scope and demo boundaries, see the [README](../README.md) and [MVP evidence](mvp-evidence.md).

## Source-review portability, 2026-10-26

The SDK and MCP now have dedicated Sentinel discovery, quote, recovery and
review-linked compute operations. DeepSeek is reserved for the fixed source
review, while worker owners set execution prices. Studio imports and exports
the same signed review bundle as the SDK and navigates findings to exact source
lines. Imports verify the connected gateway and preserve the reviewing owner;
they cannot authorize execution or bypass the gateway's retained-task checks.

The new process-level check exposed a recovery bug: `/agents/tasks/resume`
omitted `worker_target` from an authorization-v5 quote. Recovery now includes
that original signed route, verified by an API regression and actual fresh
SDK/MCP recovery. The combined fixture check completes thirteen tasks, including
SDK and MCP review-to-compute flows, with eight synthetic model requests and
zero Solana payment. This is local transport/provenance evidence; live hosted
model quality, remote execution and deployed worker payouts remain separate.

## Recheck on 2026-10-25

`git fetch origin` completed. Local `HEAD` and GitHub `origin/main` both resolve to
`2ec06a982e7b545cd4b86ee37e8878b8393111a6`, dated 2026-10-24 02:22:06 +05:00.
The available history contains 80 commits. The subsequent browser worker-selection,
Sentinel recovery and purple-theme changes are still uncommitted working-tree changes;
the GitHub snapshot therefore does not yet include all locally tested behavior.

The conclusion is **shared task infrastructure and connected product roles, with
remaining integration and deployment gaps**. It is not a complete restoration of
every historical screen or completion of the old roadmap.

Confirmed connections:

- CPU and inference requests use the gateway's quote, owner authorization, admission,
  worker claim, cancellation and signed result lifecycle.
- A completed Gemini Sentinel review can bind the exact source and reviewing owner
  to the next Python manifest. The review is an optional advisory; gateway source
  policy and the owner's compute authorization still decide execution.
- Consumer worker selection, provider activity/totals and drain/resume use the same
  registered worker identity and durable task records.
- The frontend's CSV plan is executable by the SDK CLI, and owner-assigned workflows
  can run and recover through actual MCP stdio processes.

Remaining gaps, traced to current source and runtime:

1. **The running preview has no configured model route.** `GET /inference/providers`
   returned an empty provider list; `GET /workers` returned one online, accepting
   `python` worker in `trusted_local` mode. Live Gemini review and model inference
   are not available in that process. Protocol fixtures do not establish a live
   Google response.
2. **Workflow gap at the audit snapshot; closed by the subsequent local changes below.** The step schema in
   `sdk/python/aperture_client/workflows.py` has neither an inference runtime/offer
   nor a per-step worker target. Its runner calls `quote_job`/`execute_job` for
   Python sources. Standalone inference works through SDK/MCP, but a durable mixed
   model → Python → model plan was not implemented at that snapshot.
3. **Worker payment is source-level, not live payment evidence.** The Rust and IDL
   version is 0.5.0 and the contract binds a worker payout destination. This recheck
   ran native Rust tests, not a Solana validator or Devnet payout. The active preview
   is `OFF_CHAIN` and sends no SOL.
4. **The directory is operator-managed.** Provider offers are loaded from
   `APERTURE_INFERENCE_CONFIG`; there is no permissionless offer publication/market
   matching or integrated payment of upstream model API bills.
5. **Historical dynamic hardware pricing is only partly retained.** The AST/APS
   formula exists, but the default hardware divisor is 2.5 and pressure delta is
   0.0. CPU CSV and inference use published tariffs; SOL/USD is reference data,
   not an input to the signed task tariff. There is no live GPU-load price loop.
6. **No GPU execution path is implemented.** The current worker advertises Python
   CPU execution or an inference HTTP adapter. Docker configuration limits CPU
   resources; it does not provision CUDA/GPU jobs. Old GPU claims and fallback
   TFLOPS/counters are not evidence of a working GPU marketplace. Mainnet, ZK
   computation proofs and the old Rust SDK roadmap also remain outside the MVP.

Fresh verification:

- Backend: 113 tests run, 111 passed, 2 Docker-dependent tests skipped.
- Frontend: 66 tests passed. Python SDK/MCP: 41 tests passed. Rust: 17 tests passed
  with `cargo test --manifest-path programs/Cargo.toml --offline`.
- `scripts/check_inference_preview.py`: one streamed local fixture request,
  duplicate-admission recovery, a fresh client retrieving the same result, revoked
  agent rejection and actual CPU output `42`; no upstream model or Solana request.
- `scripts/check_exported_plan.py`: the actual frontend produced 17 CSV batches and
  20 workflow steps; all 20 tasks completed, replay reused verified output files,
  independent JSON/CSV checks matched and retained object storage returned to zero.
- `scripts/check_mcp_stdio.py --assigned`: 23 tools advertised; two MCP processes
  completed a three-task owner-assigned workflow, reused the first admitted task,
  matched SDK/MCP result bytes and released storage.

The first backend run exposed a test-isolation race in the Sentinel → CPU check:
the CPU stage polled the ambient preview gateway instead of its fixture gateway.
It now uses the same fixture HTTP bridge as the inference stage, and the complete
backend suite passed on the subsequent run. Runtime behavior was not changed.

Reproduction logs and summaries for this recheck are retained under ignored
`.aperture/audit-*-2026-10-25*`. They exercise local transports and trusted-host
computation. They do not establish Docker isolation, a compatible on-chain
deployment, a live hosted-model response or remote-compute correctness.

## Mixed workflow completion after the recheck

The working tree now supports model → Python → model plans through the browser,
SDK, MCP and owner-approved workflow inbox. Model responses publish signed
`response.txt` artifacts. Explicit `message_inputs` bind a named, size/hash-verified
parent result into a subsequent user message; the resolved prompt and source hash
are checked against the owner's plan. Each step can bind its own worker key.
Existing CSV plans retain their normalized shape and recovery identity.

The reproducible `scripts/check_mixed_workflow.py` run completed three SDK steps
after an intentional interruption, three MCP steps and three owner-assigned MCP
steps. Six synthetic model requests served those nine tasks; replay added none.
Actual Python statistics matched the exact UTF-8 model-response bytes, including
Kazakh text. Browser QA completed the three pinned steps, navigated away during
work and reloaded the final admission without creating another task.

This work also fixed Windows isolated-Python output encoding and the order in
which worker pins are added before an assigned-workflow quote is validated.
Publication of progress now checks resolved prompts, rather than comparing them
to an unresolved template. Live Gemini access, compatible Devnet deployment and
payment, GPU execution and permissionless discovery still require separate work;
they are not implied by these fixture-backed local checks.
