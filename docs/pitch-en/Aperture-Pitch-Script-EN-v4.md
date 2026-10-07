# Aperture: two-minute pitch

About 220 spoken words. Target delivery: two minutes with brief transitions. This narration follows the six-slide English pitch deck.

## 1. When agents do real work (0:00–0:18)

AI agents are moving from conversation into real workflows: using tools, handling data, and completing multi-step tasks. For teams, that raises practical questions: what may an agent access and spend, and how can its work be recovered and reviewed?

## 2. A control layer for agent work (0:18–0:37)

Aperture gives teams a control layer for that work. The owner defines the permitted task and spending ceiling before execution begins.

## 3. Bounded, recoverable execution (0:37–0:59)

Agents connect through MCP or our Python SDK. Aperture records accepted steps so a workflow can recover after interruption and returns files whose hashes can be checked. Input data can stay outside the model’s context unless selected results are sent back.

## 4. Evidence from a recovery test (0:59–1:24)

To test the control flow, we used recurring data analysis across 17,000 synthetic CSV rows. We deliberately interrupted the run: all five planned tasks completed after recovery with no duplicates, and three result files matched a direct Python run byte for byte. This was trusted local CPU execution, with no Docker isolation or on-chain payment.

## 5. Delegated spending on Solana (1:24–1:45)

Solana provides delegated budgets, task-level spending caps, and revocation. In a separate retained Devnet run on September 27, 3,200 lamports settled on-chain and a task receipt was recorded. Signatures bind identities and file hashes; they do not prove a remote calculation was correct.

## 6. The broader purpose (1:45–2:00)

The goal is to give teams a practical way to delegate bounded work, stop or recover it, and inspect what came back. We’re looking for pilot teams to test this with recurring workflows.

## Delivery

Open on the move from conversation to real work. Pause briefly after the questions about access, spending, and recovery. Present the CSV run as evidence for the control flow, then clearly separate it from the historical Devnet payment. Close with the pilot invitation.
