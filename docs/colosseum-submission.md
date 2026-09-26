# Aperture: Colosseum submission draft

Prepared 2026-09-27. This is application text and recording guidance. It does not assert that videos, profiles, registration, interviews, or a live deployment are complete.

## One-line description

**Aperture gives autonomous agents an owner-approved compute allowance, a quote before dispatch, and an attributable task and payment receipt on Solana.**

## Problem and audience

A developer lets an agent run short evaluation or analysis jobs. A funded wallet proves it can pay; it does not establish whose permission it used, which workload was approved, or which allowance the task consumed. The developer needs to prevent silent budget expansion and retain an explanation of each result and charge.

Initial audience: Solana agent developers running repeated bounded Python jobs. Start with workload support actually demonstrated by the worker. CPU examples must not be presented as GPU inference or an established provider marketplace.

## Product workflow and Solana role

Target workflow: owner-issued agent policy → signed workload-bound quote with cost/runtime limits → agent acceptance → authenticated bounded execution → attributable result and settlement receipt. KYA means wallet-owner-issued compute permission; it does not mean verified legal identity or a certified model.

The intended live program makes owner-controlled agent status/revocation readable onchain and enforces an accepted task payment cap in a funded channel. Independent clients can inspect authority and settlement. Worker output observation remains offchain; a gateway receipt is not proof of correct computation.

Include only features proven by the submitted commit, tests, and recording. Describe the chain path as live only after a compatible deployment and retained transaction evidence. `OFF_CHAIN` demonstrates gateway/worker execution; `SIMULATION` is browser illustration. [KYA proof obligations](kya-positioning.md#acceptance-evidence).

## Competitive context

KYA, registries, spending controls, and receipts already exist: Vouched and Trulioo/PayOS cover KYA; ERC-8004, Solana registry, and SATI cover trust/identity; x402 and agent wallets cover payment controls; Nosana, Akash, and Golem cover compute/payments. Our hypothesis is that developers value one coherent delegated-permission-to-task path with recoverable settlement. [Source-linked comparison](competitive-landscape.md).

## Validation and revenue hypothesis

No customer count, revenue, savings, or interview result is established by this draft. Proposed validation: five problem interviews, three independently run pilots, setup time and repeat usage. Proposed model: free self-hosting and hosted policy/history/support. Pricing is unvalidated. Provider fees require a real supplier/payout model and measured costs.

## Product demo: target 2:40, maximum 3:00

Record the running product. Slides or a code walkthrough do not satisfy the product-demo requirement.

| Time | Product action | Evidence / narration |
| --- | --- | --- |
| 0:00–0:20 | Show owner, agent, and passport policy | Explicit allowance, task cap, runtime, expiry |
| 0:20–0:45 | Quote a useful short analysis task | Input, limits, maximum charge, acceptance before dispatch |
| 0:45–1:10 | Reject an excessive request | Budget/policy rejection with no worker claim |
| 1:10–1:45 | Execute permitted task | Real result/status; accurately name CPU/Python and isolation mode |
| 1:45–2:10 | Inspect/export/verify receipt | Owner/agent, source/output hashes, limits, actual amount, settlement state |
| 2:10–2:30 | Revoke passport and reject a new request | Explain actual behavior for already accepted tasks |
| 2:30–2:40 | Show real transaction/account if Devnet | Genuine explorer evidence; otherwise state deployment milestone |

Use one recorded task following the shown path. Retain its raw output and exported receipt. A simulated result cannot be spliced into a live receipt.

## Separate pitch: target 1:50, maximum 2:00

1. **0:00–0:15 — Problem:** An agent can buy compute, but its developer needs to know whose permission it used and how much the task was allowed to spend.
2. **0:15–0:40 — Product:** Explain delegated compute permission, upfront task terms, and attributable receipt with one product image.
3. **0:40–1:00 — Mechanism:** Explain the chain enforcement actually proven in the demo and the worker trust boundary.
4. **1:00–1:20 — Audience:** Name the initial developer audience and integrated-workflow hypothesis; acknowledge existing alternatives.
5. **1:20–1:35 — Evidence:** State actual demo mode, checks, observed pilots/interviews if any, and deployment milestones. No invented traction.
6. **1:35–1:50 — Team:** Real founder names, roles, relevant work, and commitment. Team introduction is required; obtain actual details before recording.

## Team and external inputs still needed

- Actual founder names, roles, individual Colosseum profiles, relevant work, and continuing commitment.
- Real interviews/pilot observations and permission to name any users.
- Completed product-demo and separate pitch video URLs.
- Actual registration/application status and initial review outcome.

## Kazakhstan submission checklist

Local requirements come from the Superteam Kazakhstan text supplied by the project owner; no independent official local URL was supplied. Global dates and registration/past-work rules were checked on the [official Colosseum page](https://colosseum.com/hackathon).

- [ ] Join the current global hackathon and meet eligibility rules.
- [ ] Complete **Project Details**, **Media and Code**, **Team Profiles**.
- [ ] Every member finishes their individual profile; the team lead adds each member.
- [ ] Link the specific accessible [GitHub repository](https://github.com/AliNurym/aperture-ai-gateway), identify submitted branch/commit, and confirm the landing page exposes that implementation.
- [ ] Host a working-product demo on YouTube, Loom, or Vimeo, **no longer than three minutes**.
- [ ] Host a **separate** team/product pitch on those services, **no longer than two minutes**.
- [ ] Disclose relevant pre-existing work and identify work completed during the competition.
- [ ] Submit completely and pass Colosseum's initial application review.

Local brief dates: registration **8 October**, Demo Day **10 October**, global submission **12 October**. Official global page: **14 September–12 October 2026**. Exact deadline time/timezone needs verification in the portal before upload.

## Evidence for local judging criteria

| Criterion | Evidence to include |
| --- | --- |
| Problem/user value | Named user type and real workflow observations |
| Product execution | Running product demo, reproducible submitted commit |
| Technical quality | Auth/policy/cap/retry checks, isolation evidence, accurate receipt labels |
| Ecosystem impact | Concrete Solana account/enforcement evidence, explicit integration roadmap |
| Market potential | Actual pilots/repeat usage and labelled revenue hypothesis |
| Innovation | Permission-to-task lifecycle compared honestly with existing primitives |
| Team strength | Real roles, relevant demonstrated work, and commitment |
| Pitch/demo quality | Separate videos meeting duration/content requirements |

Do not mark submission readiness complete from this draft alone. Record actual video/profile/application URLs and confirmed deployment evidence before making those claims.
