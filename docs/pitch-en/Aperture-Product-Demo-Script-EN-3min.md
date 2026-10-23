# Aperture — 3-Minute Product Demo

**Language:** English · **Length:** 3:00 · **Mode:** Gemini + Python in `OFF_CHAIN` preview

## Before you start

- Set `GEMINI_API_KEY` in the PowerShell session, then run `start_preview.bat`.
- Open `http://127.0.0.1:3000/#studio` and confirm the gateway, Gemini offer, inference worker and CPU worker are ready.
- Connect with **Temporary key**. Gemini receives a prompt only after its quote is signed. Google may charge separately for API use; Aperture preview makes no Solana payment.
- The demo uses the remote Gemini API and does not require a local model download.
- Prepare two small example CSV batches in Agent workflows, or upload them before recording.

## Run of show

### 0:00–0:20 — One workspace, three workload types

**On screen:** Overview, then Compute Studio with its Python and Model inference modes.

**Say:** “Aperture brings the original Gemini AI Sentinel into the current compute gateway. The same workspace can review Python with a model, run bounded Python work, or build a data workflow.”

### 0:20–0:40 — Show live provider and worker capacity

**On screen:** Open **Worker network**. Point to the current Gemini offer and authenticated CPU and inference workers.

**Say:** “Model and compute capacity use one gateway. Offers are configured by the operator. The updated Devnet source pays the assigned worker the full confirmed task charge; deployment and live payout verification remain ahead. Upstream model API bills are separate.”

### 0:40–1:55 — AI Sentinel, then separately approve compute

**On screen:** In Compute Studio, keep the Python source visible and select **Request AI Sentinel code review**. A right-side review drawer opens over the editor. Review the exact prompt, Gemini provider, budget and runtime. Sign and wait for the real response, then inspect its receipt. Close the review drawer and confirm that the advisory report matches the current source. Select **Review compute price & limits** to show the separate quote and owner signature.

**Say:** “AI Sentinel sends the exact source to Gemini as untrusted input and returns an advisory report. The model does not approve or execute code. Aperture checks its source policy and prepares a separate compute quote; execution needs a second owner approval.”

### 1:55–2:30 — Recoverable agent workflow

**On screen:** Open **Agent workflows**. Show the plan, inputs, per-step approvals and saved progress.

**Say:** “The same gateway also runs data workflows. Each step has its own source, inputs and spending limit, and accepted work can be recovered without blindly submitting it twice.”

### 2:30–3:00 — Read the evidence and name its limits

**On screen:** Show the actual task receipt and leave `OFF_CHAIN` visible.

**Say:** “The receipt connects the reported output and task bounds to gateway and worker signatures. It does not prove model identity, answer quality, or faithful remote execution. This preview performs real work without a Solana payment; Devnet settlement needs a configured program and funded channel.”

## Keep the demo accurate

- The selected provider receives the approved prompt. The output-token limit is sent upstream, but token usage is not independently verified.
- The workflow example uses synthetic CSV data. It is real upload and worker execution, not customer data.
- The temporary key exists only in browser memory. Keep the tab open through result review.
- The preview CPU worker executes reviewed sources on the host without a Docker boundary. Do not describe it as isolated execution.
- A signed receipt does not establish model identity, answer quality, or faithful remote computation.
