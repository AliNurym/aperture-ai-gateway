# Know Your Agent in Aperture

## Benefit and scope

**An owner can give an agent a limited compute allowance and trace each task to that permission.**

The questions are: who controls the agent key, whose allowance it uses, which task actions are allowed, what the spend/runtime limits are, and whether permission is active. This is the compute-specific meaning of KYA in Aperture.

Owner signatures establish wallet-key control and consent to the signed mandate. They do not verify legal identity. No identity-document check, enterprise verification, compliance certification, model certification, or trust score should be implied by registration.

## Intended enforcement model

The implementation target is an owner-issued `AgentPassport` binding an agent public key and metadata hash to `python.execute`, expiry/revocation, per-task cost/runtime caps, and a total allowance with spent/reserved accounting. The quote binds owner, agent, program context, source hash, rate, maximum cost/runtime, and expiry. Agent acceptance must happen before dispatch.

The target onchain task state bounds payment with an accepted task hash, cap, and deadline. Settlement must respect elapsed time and those limits, release unused allowance, and survive retry without charging twice. Gateway and worker journals preserve lifecycle evidence; receipts bind source/output hashes to authority, limits, and settlement.

These are the intended invariants. The [acceptance evidence below](#acceptance-evidence) and actual implementation tests determine which are proven; this document does not substitute for deployment evidence.

| Layer | Meaning | Required checks |
| --- | --- | --- |
| Identity | Stable key with owner-issued passport | Correct owner/agent signatures, versioned payload, explicit scope |
| Authority | Permission within approved allowance | Expiry, revocation, per-task cap, aggregate reservation, runtime bound |
| Quote acceptance | Consent to this exact workload's terms | Code/quote hashes, context, limits, signature, expiry, replay handling |
| Execution | Authenticated worker runs admitted task | Claim binding, isolation/resource/output limits, worker identity |
| Receipt | Attributable result and charge evidence | Input/output hashes, limits, amount, times, settlement state, real transaction reference |

A passport UI without admission and settlement enforcement is metadata. Onchain state is meaningful only if the live program and gateway enforce the same permission.

## Revocation and outage behavior

Reject new admission after revocation or expiry. Already accepted work needs an explicit rule: settle or cancel the existing capped obligation under its agreed terms while preserving evidence. Revocation must not create unlimited charges or erase debt. Document the implementation's exact effect on unclaimed/running work before presenting a stronger guarantee.

Live registry read failures must reject admission. An off-chain mode must disclose that its gateway is the policy authority. A restart must preserve reservations and settlement state.

## What evidence can prove

A receipt signature proves which key attested its bytes. A chain transaction proves observed account state or payment. Neither proves Python ran on a GPU or the answer is correct. AST checks, tokens, and containers do not certify a malicious operator.

Version and deployment/network binding prevent cross-context replay. Key rotation, policy change, and revocation need explicit history; key possession does not establish model identity or human identity.

## Relationship to existing standards

- Identity/discovery and reputation already exist in ERC-8004 and Solana Agent Registry. Referencing these identities needs an implemented adapter; similar fields do not establish compatibility. [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004), [Solana registry](https://solana.com/agent-registry/what-is-agent-registry).
- AP2's user-delegated mandate/action-verification distinction informs the model. Current custom messages are not AP2-conformant credentials. [AP2 authorization](https://ap2-protocol.org/ap2/agent_authorization/).
- x402 already supports capped usage and signed offers/receipts. An API adapter can compose later; current task messages are not automatically x402. [upto](https://docs.x402.org/schemes/upto), [offers/receipts](https://docs.x402.org/extensions/offer-receipt).
- Vouched and Trulioo/PayOS already describe KYA and agent passports. If verified human/company identity is needed, integrate a trusted issuer. [Vouched KYA](https://www.vouched.id/know-your-agent), [Trulioo / PayOS](https://www.trulioo.com/resources/white-papers/know-your-agent-an-identity-framework-for-trusted-agentic-commerce).

## Acceptance evidence

Proof obligations for a live claim:

1. Owner registers a bounded policy; unrelated wallets cannot register/revoke it.
2. Agent accepts a quote without the owner's private key.
3. Wrong key, expiry, revocation, changed source/terms, and replay fail before dispatch.
4. Allowance reservation is atomic across concurrent tasks, with explicit release/consume rules.
5. Runtime and payment remain capped during timeout, cancel, restart, and retry.
6. Compatible deployed program enforces registry ownership/status and task caps; configured RPC confirms state.
7. Actual isolated worker execution yields output hashes and a signature-verifiable receipt.
8. Demo/off-chain paths remain labelled and simulated signatures never become explorer links.

Record real tests, retained receipts, program identity, and transactions in the demo runbook. Production guarantees require further independent security and operational evidence.
