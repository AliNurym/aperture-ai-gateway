# Security model

## Current security boundary

Aperture is a Devnet prototype. It accepts a wallet-signed, hash-bound Python payload, applies a deterministic source-policy check, then makes it available only to authenticated workers. It is designed for a controlled demonstration environment, not for untrusted public compute.

The gateway accepts a request only when the Ed25519 signature covers this exact canonical message:

```text
Aperture execution request
wallet:<base58 wallet>
code_sha256:<sha256 of code>
```

This prevents a valid signature for one payload being replayed for another payload. Demo authentication is disabled unless `APERTURE_DEMO_MODE=true` is explicitly set.

## Controls implemented

- A shared `APERTURE_WORKER_TOKEN` plus a named worker ID is required to register, claim, stream, or settle work. A task lease is bound to that worker ID, so another authenticated worker cannot stream or settle it.
- Task IDs are opaque random UUIDs. Unknown tasks cannot receive logs or a result.
- Each task response also contains a high-entropy, session-only capability token. That token is required to poll output, download logs, or cancel the task; the task ID alone grants no access.
- Worker leases expire and tasks are returned to the queue rather than silently stalling.
- Completed output and raw logs have a configurable in-memory retention cap, so a long-running gateway cannot retain an unbounded number of task artifacts.
- Source policy limits code size and AST nodes; imports are allowlisted and dynamic imports, dunder access, and dangerous built-ins are rejected.
- The development worker uses a temporary directory, stripped environment, isolated Python mode, wall-time/CPU/memory limits where supported, and capped stdout.
- CORS defaults to local origins and API responses use basic anti-sniffing, frame, referrer, and no-store headers.
- The gateway rate-limits task creation and Devnet faucet requests per client in a short in-memory window.
- The gateway never fabricates a transaction signature. A receipt is labelled `DEVNET`, `OFF_CHAIN`, or `SIMULATION`.

## Important limitations

The AST policy is not a complete sandbox. The current worker can execute approved Python on its host, so it must run only on a disposable isolated VM or container with restrictive network and filesystem permissions. Do not expose the worker token, oracle signing key, or a public worker endpoint.

The built-in rate limiter is per-process. A horizontally scaled production deployment must enforce equivalent limits at the edge or in a shared store.

Worker-reported duration is bounded but is not independently hardware-attested. The in-memory task queue and metrics are lost on restart. Wallet deposits are deliberately disabled in the UI until the revised Anchor program is built, deployed, and its generated IDL is published.

## Deployment checklist

1. Set a unique `APERTURE_WORKER_TOKEN` outside source control.
2. Keep `BACKEND_PRIVATE_KEY` in a secrets manager; never generate or commit `oracle_keypair.json` on a production host.
3. Set `APERTURE_ENV=production`, keep `APERTURE_DEMO_MODE=false`, and configure exact `CORS_ORIGINS`.
4. Run workers in separate sandboxed VM/container instances with no host secrets and restricted egress.
5. Deploy the revised Anchor program and update program ID/IDL before enabling wallet deposits.
6. Run `python backend/test_security.py` and `python backend/test_api_security.py` before release.

## Reporting a vulnerability

Please do not publish an exploit with secrets or production endpoints. Open a private security report with reproduction steps, impact, and a minimal proof of concept.
