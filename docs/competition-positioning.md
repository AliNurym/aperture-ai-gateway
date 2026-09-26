# Aperture AI: Competition Positioning

## The wedge

Aperture is not another GPU marketplace. It is an **agent-native spend-control and execution-receipt layer** for short-lived compute on Solana.

An agent submits a bounded workload, receives a deterministic pre-flight policy decision and price estimate, and then receives a receipt that clearly distinguishes Devnet settlement, off-chain execution, and browser simulation.

## Competitive landscape

| Product | Strength | What Aperture must not copy | Aperture wedge |
| --- | --- | --- | --- |
| Akash | Production container leases, provider bidding, escrow and provider attributes | A generic Kubernetes/GPU marketplace | Short agent tasks with policy before dispatch and a cost guardrail |
| Nosana | Solana-native GPU jobs, API/SDK, node and reward system | A token-first GPU rental clone | Per-task payment channels and a verifiable task lifecycle |
| Aethir | Enterprise GPU supply, host quality controls and proof-of-delivery | Claiming enterprise scale before it exists | Small, inspectable, developer-first trust surface |

Sources: [Akash provider/lease docs](https://akash.network/docs/learn/core-concepts/providers-leases/), [Nosana docs](https://learn.nosana.com/), [Aethir docs](https://docs.aethir.com/aethir-introduction).

## What judges should see in the demo

1. A signed workload request is rejected when its policy is unsafe.
2. A permitted workload shows a predicted cost before a worker can claim it.
3. The worker authenticates with a node secret; unauthenticated nodes cannot fetch or settle work.
4. The receipt says exactly one of: `DEVNET`, `OFF_CHAIN`, or `SIMULATION`. No fabricated explorer link is ever shown.

## Near-term proof points

- Deploy the revised channel program and display the new program ID.
- Run one real signed Devnet task end-to-end and retain its explorer link and raw log.
- Containerize worker execution with no network, resource limits, and per-task ephemeral storage.
- Add an SDK example that opens a channel, signs a task request, and verifies the receipt status.
