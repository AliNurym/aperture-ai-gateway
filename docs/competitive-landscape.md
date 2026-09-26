# Aperture competitive landscape

Reviewed 2026-09-27 from linked primary sources. Features are documented capabilities, not independent performance/security audits. A feature absent from a linked page is **not assessed**, rather than presumed absent. Prices and marketing claims about scale/speed are intentionally not compared.

## Feature and mechanism comparison

| Product / standard | Documented mechanism and actual overlap | Existing strength | Implication for Aperture |
| --- | --- | --- | --- |
| [Vouched Agent Checkpoint / KYA](https://www.vouched.id/know-your-agent) | Agent/user authentication, delegation, policy, authorization, revocation, auditability; KYA-OS and KnowThat.ai registry. | Broader merchant-facing governance and identity-verification scope. | Direct KYA overlap. Initial passport claim should be owner-authorized compute; credential interoperability needs investigation. |
| [Trulioo / PayOS Digital Agent Passport](https://www.trulioo.com/resources/white-papers/know-your-agent-an-identity-framework-for-trusted-agentic-commerce) | Agent-commerce identity framework linking origin, ownership, and user intent through a passport. | Wider commerce/identity ecosystem. Public page describes a framework; enforcement was not independently assessed. | Wallet ownership is narrower. No KYC/KYB or compliance claim without a trusted issuer integration. |
| [ERC-8004: Trustless Agents](https://eips.ethereum.org/EIPS/eip-8004) | Draft identity, reputation, and validation registries; portable metadata and independent validation hooks. Payments are outside its scope. | Shared discovery/trust schemas and interfaces. | A compute mandate does not replace portable reputation or independent validation. |
| [Solana Agent Registry](https://solana.com/agent-registry/what-is-agent-registry) | PDA-backed identity, metadata, transferable/delegatable ownership, reputation feedback, and validation hooks. | Existing Solana discovery and trust infrastructure. | A proprietary agent list is insufficient differentiation. Upstream interoperability remains future work until tested. |
| [SATI](https://github.com/cascade-protocol/sati) | Token-2022 identity, signed interaction commitments, feedback/validation attestations, ERC-8004-compatible registration format. | SDKs and public Solana attestation infrastructure. Published deployment addresses were not transaction-verified here. | Receipt hashes could feed SATI later. A gateway signature is not a SATI attestation or computation proof. |
| [AP2 Agent Authorization](https://ap2-protocol.org/ap2/agent_authorization/) | User-approved mandates delegated to an agent; verifier checks action authority and returns a receipt. | General authorization and credential-based consent model. | Distinguish identity from action permission. Current custom messages do not establish AP2 conformance. |
| [x402 upto](https://docs.x402.org/schemes/upto) / [signed offers and receipts](https://docs.x402.org/extensions/offer-receipt) | Buyer authorizes maximum, seller settles actual usage. Includes Solana; portable signed offers/receipts support Ed25519/JWS. | Standard payment middleware with existing capped metering and receipt primitives. | Strong overlap. Demonstrate compute lifecycle, agent policy, and isolation; x402 interoperability is a future integration. |
| [Coinbase Agentic Wallets](https://www.coinbase.com/developer-platform/products/agentic-wallets) | Agent wallet skills, x402, session/per-transaction caps, enclave key isolation, KYT screening. | Wallet/key infrastructure and advertised transaction controls. | Spending caps are not unique. Wallet policy can compose with workload/worker policy. |
| [Coinbase AgentKit](https://github.com/coinbase/agentkit) | Agent wallet/action toolkit; its risk section says the SDK itself does not gate transfers, enforce caps, or allowlist recipients. | Action providers and framework/wallet integrations. | Distinguish AgentKit from the separate Agentic Wallets product. Aperture can supply a task tool. |
| [Nosana jobs](https://learn.nosana.com/deployments/jobs/) / [Jobs API](https://learn.nosana.com/api/jobs.html) | Containerized Solana GPU jobs, node selection, results/rewards, machine access, configurable runtime limit. | Existing GPU supply and workload execution. | Closest compute comparison. Do not imply Nosana lacks task bounds or API access. |
| [Akash providers and leases](https://akash.network/docs/learn/core-concepts/providers-leases/) | Provider bids, deployment leases, escrow, published capabilities, audited-provider filtering. | Deployment marketplace and provider selection. | Possible supplier later. Aperture does not establish equivalent GPU supply or provider assurance. |
| [Golem allocation](https://docs.golem.network/docs/creators/common/requestor-provider-interaction) / [payments](https://docs.golem.network/docs/golem/payments) | Provider agreements; reserved budget limits requestor spend; usage billing and batched payments. | Existing task-market, budget, and provider payment lifecycle. | Direct counterexample to claims of missing compute budget controls. Show the benefit of owner/agent delegation and attribution. |
| [io.net IO Cloud](https://io.net/docs/guides/clouds/io-cloud) | Distributed GPU/CPU access, cluster creation, monitoring, API-related operations. | Compute supply and cluster-oriented operation. Agent delegation was not assessed from this overview. | Capacity alternative; not evidence of production GPU capacity in Aperture. |
| [Aethir](https://docs.aethir.com/aethir-introduction) | Distributed GPU aggregation, resource evaluation, workload matching, rewards after delivery confirmation. | Wider GPU supply/delivery network. Agent mandates were not assessed from the overview. | Keep supplier quality and agent policy separate. Worker tokens do not verify advertised hardware. |

## Conclusion and current limitations

Based on these sources, agent identity, delegation, budget-controlled compute, Solana GPU execution, and signed payment receipts already exist. Combining them is useful if the resulting workflow is simpler or more reliable for a specific user.

**Initial hypothesis:** an owner authorizes an agent for bounded Python tasks; the agent accepts a workload-bound quote; gateway and contract enforce the allowance; the result and recoverable payment produce an attributable receipt. This requires a complete demonstration and user evidence.

Aperture has no established production workload, GPU supply, independent operator network, provider payout history, or measured cost advantage in this report. Owner signatures prove wallet control; they do not certify a model, prevent Sybils, or prove output correctness. A receipt signature proves an assertion by the signer. Independent re-execution, hardware attestation, and cryptographic execution proofs require additional mechanisms.

Existing identity/AP2/x402/compute-provider integrations remain future work until their wire/API paths are tested. Settlement guarantees need cap, revocation, restart, retry, and duplicate-charge evidence; browser illustration does not establish them.

## Validation plan

1. Have an independent developer reproduce a complete task from a fresh clone. Save commands, receipt, setup time, and failure points.
2. Interview five Solana agent developers about their actual workflow, budgets, approvals, and recent failures. Do not lead them to endorse KYA.
3. Run three pilots comparing Aperture with their existing stack; measure API steps, rejection clarity, task completion, and repeat usage.
4. Determine whether users prefer the full gateway or only its reusable permission/receipt component; follow observed demand.
5. Test free self-hosting versus managed history/policy/support. Pricing and willingness to pay are unvalidated.

## Coverage

The user selected current primary sources without Copilot API access. No authenticated archive, builder-project, winner, or accelerator search was performed. This review does not infer company absence, market completeness, or competitor performance from that limitation. [Official Copilot authentication/workflow](https://github.com/ColosseumOrg/colosseum-copilot/blob/main/skills/colosseum-copilot/SKILL.md).
