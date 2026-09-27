# Security model

## Scope

Aperture is a controlled Solana Devnet prototype. The repository does not promise safe public execution for mutually untrusted operators. Studio dispatches real Python to an authenticated worker; it does not generate simulated results. Devnet settlement additionally requires a compatible deployed Anchor program, an initialized protocol configuration, and a funded channel. Explicit off-chain development executes the same worker path without a Solana payment.

## Authorization and state

- The gateway issues a short-lived quote bound to the wallet, agent, source hash, rate, cost/runtime limits, network, program, gateway signer, treasury, and passport version. The frontend reconstructs the canonical v2 message and checks the quote fields before requesting a wallet signature; live Devnet approvals also require independently configured gateway signer and treasury pins. The Agent page similarly reconstructs the owner challenge and locally derives instruction bytes and accounts against the pinned program before asking for a wallet signature. `/execute` checks the exact stored message, source, caller, expiry, and signature before admitting new work.
- Repeating the same valid signed admission recovers the same task response after a lost network response. The task access token is a bearer capability: result, receipt, stream and cancellation routes require it. Keep it private.
- Agent passports are owner-authorized policies with bounded cost, duration, expiry, and total allowance. The program verifies the configured authority and oracle for payment operations. Verify a compatible deployment and initialized configuration before enabling live tasks.
- Gateway state is persistent SQLite by default (`backend/data/gateway.sqlite3`) or at `APERTURE_STATE_DB`. Jobs can contain submitted source, output/logs, and capability tokens. Expired unused quotes and challenges are removed when new transient records are issued; completed jobs are capped by `APERTURE_MAX_COMPLETED_TASKS` (default 1000). A compact delegated-spend ledger preserves lifetime allowance accounting after old job details are pruned. Protect the state directory and configure an external retention policy for backups.
- Task IDs alone do not authorize result access. Worker results are checked against the registered worker signature and task lease; gateway receipts bind the result to its quote and settlement. For gateway runs, the browser verifies the gateway signature, the worker signature when present, and the signed output hash against the approved quote and downloaded raw output. For Devnet settlement it independently checks the persistent on-chain TaskReceipt and transaction confirmation before reporting verification. Off-chain runs check the configured gateway signer pin when supplied and have no Solana settlement. Signatures attribute reports but do not attest faithful hardware execution.

## Worker boundary

- The default coordinator starts each task in a separate Docker container with a read-only input mount, no network, a non-root user, a read-only container filesystem, dropped capabilities, and resource/time/output limits.
- The worker coordinator is trusted and has access to the Docker daemon socket in Compose. Compose currently supplies the backend environment file to both gateway and coordinator. Separate their secrets when deploying; workload containers receive only the explicit task environment.
- Host execution is an explicit trusted-development option. It is not the default sandbox and should only run for code the operator trusts. `--trusted-source-directory` snapshots the SHA-256 values of reviewed UTF-8 Python files at startup and rejects any other source before launching a process. It limits source admission; it does not create OS isolation.
- Worker leases are durable. A gateway restart or expired running lease is settled as failed rather than returned to the queue, because its on-chain start may already have been submitted.

## Network and deployment

- Local launchers and `python main.py` bind the API to loopback by default. Docker Compose also publishes the gateway on loopback. Override `APERTURE_BIND_HOST` only with deliberate network controls.
- The API enforces a bounded request-body limit (`APERTURE_MAX_REQUEST_BYTES`, default 2.5 MB) and a bounded in-process rate limiter. Horizontally scaled or publicly reachable deployments still need shared/edge rate controls. CORS is browser policy, not API authentication.
- Browser run metadata and the active task capability are stored in tab `sessionStorage` to resume polling. While an admission response is uncertain, the exact signed request, including its source, stays in that tab until the gateway accepts or rejects it. Do not treat same-origin scripts or a compromised browser/API response path as trusted; inspect wallet prompts.
- Keep `BACKEND_PRIVATE_KEY`, worker tokens, deployment keypairs, and SQLite data outside source control and outside workload containers. Never copy a local state database into a distributed Docker image.
- `VITE_ENABLE_SESSION_KEY=true` enables a temporary Ed25519 signing key only in the Vite development server. The key is generated on connection and remains non-extractable in browser memory; reload or disconnect loses it. It must not hold persistent assets. Production builds omit this connection option.
- Pin `APERTURE_CONFIG_AUTHORITY` at program build time and verify it matches the protected initializer signer. Source changes do not change an already deployed program.

## Before a release

1. Review the exact gateway URL, TLS/ingress, CORS origins, secrets, worker mode, Docker host, and persistent-volume permissions.
2. Confirm the deployed program address and on-chain v2 configuration independently.
3. Review the completed-task retention limit and backup lifecycle; delegated spend totals remain available after task details are pruned.
4. Run the backend, SDK, frontend, container-isolation, and local-validator checks listed in `README.md`.
5. Review wallet-signed actions and receipt-verification behavior before describing a browser result as confirmed execution or settlement.

## Reporting

Report suspected vulnerabilities privately with affected source locations, prerequisites, impact, and minimal sanitized evidence. Do not include secrets or production endpoints in a public report.
