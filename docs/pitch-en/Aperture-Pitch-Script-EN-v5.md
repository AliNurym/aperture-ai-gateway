# Aperture: two-minute pitch

About 230 spoken words. Target delivery: two minutes at a measured pace. This narration follows the six-slide English pitch deck.

## Slide 1 — The crypto problem (0:00–0:23)

Crypto lets software pay for data, APIs, and compute. But giving an AI agent a wallet raises the harder question: how much authority should it have? Too little, and people approve every step. Too much, and a single task can exceed its intended budget.

## Slide 2 — Aperture’s solution (0:23–0:49)

Aperture is a task-level control layer for agent compute. The owner selects permitted data, approves the task, and sets one total spending ceiling before work begins. The agent executes inside that boundary, while the owner can stop the workflow or revoke its allowance.

## Slide 3 — How it works (0:49–1:07)

Agents connect through MCP or our Python SDK. Aperture records accepted steps so work can recover after interruption and returns named output files with checkable hashes. Dataset contents stay outside the model’s context unless selected results are sent back.

## Slide 4 — Recovery evidence (1:07–1:27)

After an intentional interruption, the workflow completed all five tasks across 17,000 synthetic rows with no duplicates. Three result files matched a direct Python run byte for byte. This was trusted local CPU execution, without Docker isolation or payment.

## Slide 5 — The Solana layer (1:27–1:47)

On Solana, Aperture links delegated budgets to task-level settlement. A retained Devnet run on September 27 settled 3,200 lamports on-chain and recorded a task receipt binding identities and file hashes. The receipt does not prove the calculation was correct.

## Slide 6 — The invitation (1:47–2:00)

That’s our goal: let agents use compute within clear limits and give owners results they can inspect. We’re looking for pilot teams with recurring workflows.

## Run of show

Advance slides at 0:00, 0:23, 0:49, 1:07, 1:27, and 1:47; finish at 2:00. This is a slide-led pitch with no live-demo segment or screen switch. Pause briefly after the question about how much authority an agent should have. Keep the local workflow test and Devnet settlement distinct.
