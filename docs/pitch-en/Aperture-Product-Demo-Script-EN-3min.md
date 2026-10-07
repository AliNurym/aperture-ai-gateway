# Aperture — 3-Minute Demo Cue Sheet

**Language:** English · **Length:** 3:00 · **Mode:** local `OFF_CHAIN` preview

## Before you start

- Open the running local preview: [http://127.0.0.1:3031](http://127.0.0.1:3031/), then open **Compute Studio**.
- Connect with **Temporary key**. No external API key or account is needed.
- Confirm the gateway and worker are ready. Keep this browser tab open.
- Have **Agent batch risk scoring** selected before the timer starts.

## Run of show

### 0:00–0:20 — Set the stakes

**On screen:** Compute Studio; point to the selected sample.

**Say:** “AI agents are starting to do real work. Before an agent can spend compute, its owner needs clear limits on what may run, how long it may run, and what it may cost. Aperture puts that decision before execution.”

### 0:20–0:45 — Review the bounds

**On screen:** Set the maximum cost and runtime. Select **Review price & limits** and show the quote.

**Say:** “For this task, the gateway shows the maximum cost and runtime up front. The quote is tied to this exact source and these limits. The worker has not received a job.”

### 0:45–1:05 — Show the guardrail

**On screen:** Select **Policy rejection**, review it, and pause on the rejection. Then reselect **Agent batch risk scoring**.

**Say:** “This request falls outside policy, so Aperture rejects it before dispatch. The worker receives nothing. I’ll return to the allowed sample.”

### 1:05–1:30 — Approve the task

**On screen:** Review the quote again, select **Accept quote & sign**, then approve with **Temporary key**.

**Say:** “I check the new quote and approve the exact task and spending limits. This is a local run; it does not call an external AI service.”

### 1:30–2:05 — Watch it run

**On screen:** Keep the run status and output visible until completion.

**Say:** “The local CPU worker is now running the fixed-seed Python sample. The output is produced by the worker, rather than being a sample animation.”

### 2:05–2:35 — Inspect the evidence

**On screen:** Show the result, then open **Inspect receipt evidence**. Point to verification, source and output hashes, and the execution boundary.

**Say:** “The run returns a signed receipt. Here I can inspect the reported source and output hashes, worker identity, and execution boundary. That gives the owner evidence tied to this task.”

### 2:35–3:00 — Close clearly

**On screen:** Leave the receipt and `OFF_CHAIN` status visible.

**Say:** “This preview uses a trusted local worker. `OFF_CHAIN` means there is no SOL payment, and this run does not demonstrate Docker isolation or prove remote computation. Aperture puts approval limits before execution and task evidence after it.”

## Keep the demo accurate

- The sample uses synthetic data and a fixed seed; it is not a customer result or financial advice.
- Compute Studio uses the connected wallet as both owner and agent. This walkthrough does not show a separate delegated agent identity.
- The temporary key exists only in the browser session. Keep the tab open until the receipt review is complete.
- A signed receipt binds the task evidence; it does not prove that a remote worker computed correctly.
