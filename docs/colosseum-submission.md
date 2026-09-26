# Aperture AI — Colosseum submission draft

## One-line description

**Aperture gives autonomous agents a spend-controlled way to buy short-lived GPU compute on Solana: policy check, upfront quote, authenticated worker execution, and an honest settlement receipt.**

## Problem

An AI agent can call an API, rent a GPU, and accidentally run an expensive or unsafe workload. Existing decentralized compute networks are optimized for capacity marketplaces and deployments; an agent still needs a reliable control plane that can reject unsafe code, cap work before dispatch, and distinguish a chain settlement from a local simulation.

## Product

1. The agent signs a request containing the exact SHA-256 hash of its code.
2. AI Sentinel applies deterministic policy checks and produces a complexity-based price quote.
3. Only authenticated workers can claim, stream, and settle the task.
4. The UI exports a receipt labelled `DEVNET`, `OFF_CHAIN`, or `SIMULATION`; it never fabricates a blockchain explorer link.

## Live demo plan (90 seconds)

1. Open the Studio and show the signed code-hash message in the wallet prompt.
2. Submit an unsafe import; show the 403 policy rejection and zero dispatch.
3. Submit the matrix benchmark; show quote, authenticated worker heartbeat, and streamed stdout.
4. Open receipt and show its explicit status plus raw log.
5. Open the Devnet explorer only when an actual transaction was returned.

## Why this can win

- The demo has a sharp agent-specific risk: uncontrolled compute spend.
- The technical surface is inspectable: signed payload binding, worker authentication, policy tests, and an on-chain channel program.
- The product is honest about its state. This is stronger than a polished simulation that claims unverified execution.

## Milestones after the hackathon

- **Week 1:** deploy the revised channel program, publish one real Devnet receipt.
- **Week 2:** put every worker task into a network-disabled, resource-capped container.
- **Week 3:** ship a TypeScript SDK and an agent example with budget/receipt verification.
- **Week 4:** onboard three independent worker operators and measure completion rate, quote error, and median settlement latency.
