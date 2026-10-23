# Aperture: two-minute pitch

About 230 spoken words. Target delivery: two minutes at a measured pace. This narration follows the six-slide English pitch deck.

## Slide 1 — The crypto problem (0:00–0:23)

Crypto lets software pay for data, APIs, and compute. But giving an AI agent a wallet raises the harder question: how much authority should it have? Too little, and people approve every step. Too much, and a single task can exceed its intended budget.

## Slide 2 — Aperture’s solution (0:23–0:49)

Aperture is an early AI inference gateway and compute marketplace on Solana. It connects configured model offers and authenticated compute workers to one owner-approved task flow. Model requests, Python jobs, and recoverable data workflows carry signed spending and runtime limits before dispatch.

## Slide 3 — How it works (0:49–1:07)

The capacity directory combines authenticated CPU workers with model offers configured by the gateway operator. Agents connect through MCP or our Python SDK; each task binds its route, input, limits, and owner approval. Accepted workflow steps are journaled for recovery, and the gateway returns named output files with checkable hashes. Discovery remains operator-managed. Updated contract source routes the full confirmed Devnet task charge to the assigned worker, pending deployment and live verification; upstream model API bills remain outside Aperture.

## Slide 4 — Recovery evidence (1:07–1:27)

After an intentional interruption, the workflow completed all five tasks across 17,000 synthetic rows with no duplicates. Three result files matched a direct Python run byte for byte. This was trusted local CPU execution, without Docker isolation or payment.

## Slide 5 — The Solana layer (1:27–1:47)

The retained September 27 Devnet run used the earlier treasury-settlement build: it charged 3,200 lamports and recorded a task receipt binding identities and file hashes. The updated contract source instead routes 100% of new confirmed task charges to the assigned worker; this path still needs deployment and live verification. The receipt does not prove the calculation was correct, and upstream model API vendors are not paid by Aperture.

## Slide 6 — The invitation (1:47–2:00)

That’s our goal: bring model inference and compute into one marketplace while keeping every request bounded by its owner. The MVP uses operator-configured model offers and CPU workers; we’re looking for pilot teams and independent providers to validate the next stage.

## Run of show

Advance slides at 0:00, 0:23, 0:49, 1:07, 1:27, and 1:47; finish at 2:00. This is a slide-led pitch with no live-demo segment or screen switch. Pause briefly after the question about how much authority an agent should have. Keep the local workflow test and Devnet settlement distinct.
