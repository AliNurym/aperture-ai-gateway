# Aperture demo runbook

## Two-minute browser walkthrough

1. Run `start_frontend.bat` and open http://127.0.0.1:3000.
2. Choose **Numerical analysis** on Overview. It opens Compute Studio with the selected source.
3. Keep **Browser demo** selected and click **Run demo**.
4. Inspect the estimated rate, event log and result marked **SIMULATION**. No Python, wallet or payment is involved.
5. Download the JSON result or save the log.
6. Choose **Policy rejection** and run again. The demo stops at the restricted-import example.
7. Return to Overview to see session activity. Check Worker network: without a gateway it should show a useful offline state, not imaginary workers.
8. Open Agent passports to inspect the owner-signing and permission-boundary UI. Without a wallet/backend it remains clearly disconnected.
9. Resize the window to check the mobile navigation and editor.

The browser policy example is illustrative pattern matching, not a Python parser or a security boundary.

## Connected Devnet walkthrough

1. Create a new Devnet v2 deployment using the installation instructions in README. The current v2 Program ID has not been deployed yet.
2. Configure backend/.env from backend/.env.example with the matching config authority/oracle signer, treasury, a unique worker token, and the v2 program ID. Keep demo mode disabled.
3. Initialize the protocol config; verify the program ID, config PDA, authority, oracle, treasury and protocol version 2 through the gateway.
4. Start the gateway and a worker configured with the isolated Docker image. Direct host execution is only for code the operator trusts.
5. Connect a Solana wallet. In Agent passports, issue a policy for a separate agent public key with explicit limits and expiry, then confirm the wallet and Devnet transaction.
6. Deposit Devnet SOL into the idle payment channel. In Studio, select Devnet gateway, request and review the exact quote, then sign acceptance.
7. Inspect the authenticated worker result, hashes, signed receipt, persistent on-chain TaskReceipt, and confirmed charge. A declined signature or policy rejection must stop before dispatch.
8. Follow an Explorer link only when the gateway returns the actual confirmed transaction. OFF_CHAIN and SIMULATION are not Devnet settlements.

## Useful checks

- Switching pages must not interrupt a run.
- Running a second workload and switching modes are disabled during a run.
- Empty or oversized workloads show a clear error before submission.
- A failed cancellation must leave status monitoring active.
- A nonzero Python exit code must appear as a failed result.
- The gateway may need configuration even when its HTTP server is reachable.
- Add the exact frontend origin to `CORS_ORIGINS` if using a port other than 3000.
