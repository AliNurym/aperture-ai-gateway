# Aperture: competition positioning

Research date: 2026-09-27. See the [source-linked comparison](competitive-landscape.md), [KYA definition](kya-positioning.md), and [submission draft](colosseum-submission.md).

## The product

**Aperture lets a wallet owner delegate a compute allowance to an agent, approve the terms of a task, and inspect the result and settlement evidence.**

The first user is a developer operating a Solana agent that repeatedly runs short analysis or evaluation jobs. The developer needs to answer four questions: which agent submitted the task, whose permission it used, how much it could spend, and what actually happened. The current workload engine is Python; GPU capacity, independent providers, and audited production security require additional evidence.

## The KYA addition

Know Your Agent in Aperture means an owner-issued compute passport: an owner wallet delegates permission to an agent key under a budget, runtime limit, expiry, and revocation policy. The passport is useful only when those limits govern task admission and settlement. A badge or self-reported name does not provide that guarantee.

The passport establishes wallet control and delegated permission. It does not establish a person's legal identity, an agent's model quality, or correctness of the output. KYA is already an established category: Vouched offers agent identity, delegation, revocation, and audit controls; Trulioo and PayOS describe a Digital Agent Passport. [Vouched Agent Checkpoint](https://www.vouched.id/know-your-agent), [Trulioo / PayOS KYA framework](https://www.trulioo.com/resources/white-papers/know-your-agent-an-identity-framework-for-trusted-agentic-commerce).

## Position against existing products

- **Compute:** Nosana already has containerized Solana GPU jobs, machine access, and timeouts. Akash has leases, escrow, and audited provider attributes. Golem already reserves and enforces a requestor budget. Aperture must earn adoption through a simpler delegated task workflow and measurable reliability. [Nosana Jobs API](https://learn.nosana.com/api/jobs.html), [Akash providers and leases](https://akash.network/docs/learn/core-concepts/providers-leases/), [Golem allocation](https://docs.golem.network/docs/creators/common/requestor-provider-interaction).
- **Payments:** x402 already supports maximum-authorized usage payments, including Solana, and signed offers/receipts. Coinbase Agentic Wallets advertises session and transaction caps. These are alternatives and potential integration points. [x402 upto](https://docs.x402.org/schemes/upto), [x402 offers and receipts](https://docs.x402.org/extensions/offer-receipt), [Coinbase Agentic Wallets](https://www.coinbase.com/developer-platform/products/agentic-wallets).
- **Identity:** ERC-8004, Solana Agent Registry, and SATI provide identity, reputation, and validation mechanisms. Aperture's registry represents its compute permission and lifecycle; interoperability with existing identities is a future integration until tested. [ERC-8004 draft](https://eips.ethereum.org/EIPS/eip-8004), [Solana Agent Registry](https://solana.com/agent-registry/what-is-agent-registry), [SATI](https://github.com/cascade-protocol/sati).

Do not claim that Aperture invented KYA, spending limits, agent identity, or receipts. Its proposed advantage is the complete developer flow: delegated compute permission, workload-bound quote acceptance, bounded execution, recoverable settlement, and attributable receipt. That advantage remains a hypothesis until users prefer it to composing existing tools.

## Why Solana is part of the mechanism

The intended live mechanism uses Solana accounts to publish owner-controlled agent status and enforce the accepted task payment cap in a funded channel. Independent clients can read account state and inspect the settlement transaction. The gateway still selects and observes the worker, so chain state does not prove the computation was correct.

This claim needs a compatible deployed program and a real transaction path. An off-chain demo proves gateway behavior. The demonstration should show that expired/revoked permissions are rejected and that settlement cannot exceed the approved task cap.

## What judges should see

1. Owner creates an agent passport with explicit allowance, per-task limits, and expiry.
2. Agent receives a quote before dispatch and signs acceptance of its exact workload and limits.
3. Excessive requests or revoked passports are rejected with no worker claim.
4. A permitted task produces real execution output and an attributable receipt.
5. Receipt shows owner, agent, hashes, limits, actual charge, and settlement state.
6. A settlement retry completes without a second charge.

`SIMULATION` means browser illustration; `OFF_CHAIN` means gateway/worker execution without chain settlement; `DEVNET` needs an actual confirmed transaction. Do not describe a planned deployment as a completed demonstration.

## Adoption and revenue hypotheses

These are research plans, not traction or validated pricing.

- Start with Solana agent developers running repeated bounded evaluations or data-analysis jobs. Begin with the Python workload supported by the current worker.
- Offer one sample agent, task API, and receipt verifier. Measure clone-to-task time and whether a developer understands permission and charge without reading gateway internals.
- Interview five builders about a real recent compute workflow, existing budget control, and who approves permissions. Seek three pilots after the workflow is reproducible.
- Test a free self-hosted edition and hosted monthly service for policy, persistent task history, and support. Processing fees require actual supplier payouts and measured operating cost first.
- Track activation, task completion, settlement retry success, duplicate-charge incidents, and repeat usage. Record real observations before adding numbers or savings to the pitch.

## Research scope

This is current primary-source research. The user chose to continue without authenticated Colosseum Copilot API access. No Copilot archive, project, accelerator, or winner query was run for this comparison; the report does not assert a complete or uncontested market. [Official Copilot skill](https://github.com/ColosseumOrg/colosseum-copilot/tree/main/skills/colosseum-copilot).
