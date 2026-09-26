# Aperture demo runbook

## Two-minute browser walkthrough

1. Run `start_frontend.bat` and open http://127.0.0.1:3000.
2. Choose **Numerical analysis** on Overview. It opens Compute Studio with the selected source.
3. Keep **Browser demo** selected and click **Run demo**.
4. Inspect the estimated rate, event log and result marked **SIMULATION**. No Python, wallet or payment is involved.
5. Download the JSON result or save the log.
6. Choose **Policy rejection** and run again. The demo stops at the restricted-import example.
7. Return to Overview to see session activity. Check Worker network: without a gateway it should show a useful offline state, not imaginary workers.
8. Resize the window to check the mobile navigation and editor.

The browser policy example is illustrative pattern matching, not a Python parser or a security boundary.

## Connected Devnet walkthrough

1. Configure `backend/.env` from `backend/.env.example` with a unique worker token and oracle signer. Leave backend demo mode disabled.
2. Deploy and verify the matching Anchor program and configure a payment channel before submitting a real workload.
3. Start the gateway and an authenticated worker in a suitable development environment. Direct host workers should receive only your own trusted code.
4. Connect a Solana wallet and select **Devnet gateway** in Studio.
5. Choose a small allowlisted Python workload, then **Sign & submit**. Declining the signature must prevent submission.
6. Inspect gateway output and the result. The receipt retains worker identity, exit code and settlement type.
7. Follow an Explorer link only when transaction evidence was returned. Failed chain settlement is not a Devnet success.

## Useful checks

- Switching pages must not interrupt a run.
- Running a second workload and switching modes are disabled during a run.
- Empty or oversized workloads show a clear error before submission.
- A failed cancellation must leave status monitoring active.
- A nonzero Python exit code must appear as a failed result.
- The gateway may need configuration even when its HTTP server is reachable.
- Add the exact frontend origin to `CORS_ORIGINS` if using a port other than 3000.
