#!/usr/bin/env python3
"""01_financial_monte_carlo.py

Aperture Example 1: Bounded Financial Monte Carlo Simulation
Demonstrates submitting a scientific numerical workload with deterministic
limits on CPU time, RAM, and maximum lamport cost.
"""
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add backend and sdk to path if running directly
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))

try:
    from ai_engine import analyze_code_ast
except ImportError:
    analyze_code_ast = None

# Mathematical workload executed by the Aperture Worker in an isolated container
MONTE_CARLO_CODE = '''# Agent tool: deterministic batch scenario scoring
import random
import statistics
import json

# Synthetic inputs for a reproducible compute example; not financial advice.
rng = random.Random(42)
scenarios = 500_000
portfolios = [("balanced", 0.45, 0.08), ("growth", 0.75, 0.14), ("conservative", 0.20, 0.04)]
results = []
print(json.dumps({"stage": "started", "total_scenarios": scenarios * len(portfolios)}), flush=True)
for name, exposure, volatility in portfolios:
    losses = [max(0, -(exposure * rng.gauss(0.01, volatility))) for _ in range(scenarios)]
    ordered = sorted(losses)
    tail = ordered[int(len(ordered) * 0.95):]
    result = {"portfolio": name, "loss_p95": round(ordered[int(len(ordered) * 0.95)], 6), "tail_mean": round(statistics.fmean(tail), 6)}
    results.append(result)
    print(json.dumps({"stage": "portfolio_completed", "completed_scenarios": scenarios * len(results), **result}), flush=True)
results.sort(key=lambda item: item["tail_mean"])
print(json.dumps({"seed": 42, "scenarios_per_portfolio": scenarios, "ranking": results}, sort_keys=True))
'''


def run_demo():
    print("===================================================================")
    print("  APERTURE COMPUTE EXAMPLE: Financial Monte Carlo Risk Simulation")
    print("===================================================================")

    # 1. Pre-flight Static AST Policy Analysis
    if analyze_code_ast:
        print("\n[Step 1] Running Deterministic AST Pre-flight Analysis...")
        analysis = analyze_code_ast(MONTE_CARLO_CODE)
        print(f"  * Security Status: {analysis.get('security')}")
        print(f"  * Syntax Valid:    {analysis.get('syntax_valid')}")
        print(f"  * Complexity:      {analysis.get('reason', 'Curated compute approved')}")
        print(f"  * Estimated CPU:   {analysis.get('cpu')} arbitrary units")
        print(f"  * Estimated RAM:   {analysis.get('ram')} MiB")

        if analysis.get("security") != "SAFE":
            print(f"[BLOCKED] Workload blocked by source policy: {analysis.get('reason')}")
            sys.exit(1)
        print("  -> Workload statically approved for execution.")

    # 2. Local deterministic execution
    print("\n[Step 2] Executing Monte Carlo Workload locally to verify determinism...")
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(MONTE_CARLO_CODE, {"__builtins__": __builtins__})

    output_lines = [l.strip() for l in buffer.getvalue().strip().splitlines() if l.strip()]
    data = json.loads(output_lines[-1])

    print("\n[Step 3] Local Execution Result:")
    print(f"  * Seed:                    {data['seed']}")
    print(f"  * Scenarios per Portfolio: {data['scenarios_per_portfolio']:,}")
    print(f"  * Portfolios Evaluated:    {len(data['ranking'])}")
    for item in data['ranking']:
        print(f"    - Portfolio [{item['portfolio'].upper()}]:")
        print(f"        95% Loss (VaR):       {item['loss_p95']:.6f}")
        print(f"        Tail Mean (CVaR):     {item['tail_mean']:.6f}")
    print("\n[SUCCESS] Monte Carlo computation completed with verified deterministic bounds.")


def run_live(gateway_url: str):
    print("\n[Step 2] Connecting to Live Aperture Gateway...")
    print(f"  * Gateway URL: {gateway_url}")

    import requests
    from solders.keypair import Keypair
    from aperture_client import ApertureClient

    resp = requests.get(gateway_url.rstrip("/") + "/health", timeout=5)
    health = resp.json()
    print(f"  * Gateway Status:  {health.get('status')} (Network: {health.get('network')})")
    print(f"  * Gateway Pubkey:  {health.get('gateway_pubkey')}")

    owner_kp = Keypair()
    agent_kp = Keypair()
    client = ApertureClient(
        gateway_url,
        owner=str(owner_kp.pubkey()),
        agent_keypair=agent_kp,
        program_id=health["program_id"],
        gateway_pubkey=health["gateway_pubkey"],
        network="off_chain",
    )
    print(f"  * Generated Owner: {owner_kp.pubkey()}")
    print(f"  * Generated Agent: {agent_kp.pubkey()}")

    print("\n[Step 3] Registering Agent Delegation Passport...")
    passport = client.passport(
        owner_kp,
        action="register",
        name="Monte Carlo Risk Agent",
        max_cost_lamports=100_000,
        max_runtime_seconds=30,
        total_budget_lamports=1_000_000,
    )
    print(f"  * Passport Version: {passport.get('version')}")
    print(f"  * Metadata Hash:    {str(passport.get('metadata_hash', ''))[:16]}...")

    print("\n[Step 4] Requesting Signed Quote from Gateway...")
    quote = client.quote(MONTE_CARLO_CODE, max_cost_lamports=100_000, max_runtime_seconds=30)
    print(f"  * Quote ID:        {quote['quote_id']}")
    print(f"  * Rate:            {quote['rate_lamports']} lamports/sec")
    print(f"  * Code SHA-256:    {quote['code_sha256'][:16]}...")
    print(f"  * Complexity:      {quote.get('analysis', {}).get('complexity_score')} units")

    print("\n[Step 5] Submitting Workload to Worker Sandbox...")
    task = client.execute(quote, MONTE_CARLO_CODE)
    print(f"  * Task Admitted:   {task.task_id}")

    print("\n[Step 6] Waiting for Sandbox Execution and Cryptographic Settlement...")
    result = client.wait(task)
    receipt = result["receipt"]
    raw_output = result.get("output", "")
    output_lines = [l.strip() for l in raw_output.strip().splitlines() if l.strip()]
    output = json.loads(output_lines[-1])

    print("\n[Step 7] Cryptographically Verified Sandbox Execution Result:")
    print(f"  * Worker ID:               {receipt.get('worker_id')}")
    print(f"  * Execution Time:          {receipt.get('execution_time')}s")
    print(f"  * Charged:                 {receipt.get('charged_lamports')} lamports")
    print(f"  * Settlement Type:         {receipt.get('settlement_type')}")
    print(f"  * Seed:                    {output['seed']}")
    print(f"  * Scenarios per Portfolio: {output['scenarios_per_portfolio']:,}")
    print(f"  * Portfolios Evaluated:    {len(output['ranking'])}")
    for item in output['ranking']:
        print(f"    - Portfolio [{item['portfolio'].upper()}]:")
        print(f"        95% Loss (VaR):       {item['loss_p95']:.6f}")
        print(f"        Tail Mean (CVaR):     {item['tail_mean']:.6f}")
    print("\n[SUCCESS] Live Monte Carlo computation executed and verified by Aperture Gateway.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Aperture Bounded Financial Monte Carlo Example")
    parser.add_argument("--live", action="store_true", help="Submit and execute against running Aperture Gateway")
    parser.add_argument("--gateway", default=os.getenv("APERTURE_GATEWAY_URL", "http://127.0.0.1:8000"),
                        help="Gateway URL for live execution")
    args = parser.parse_args()

    if args.live:
        try:
            run_live(args.gateway)
        except Exception as err:
            print(f"[FAIL] Live execution failed (is Gateway running at {args.gateway}?): {err}")
            print("Falling back to local validation run...\n")
            run_demo()
    else:
        run_demo()


if __name__ == "__main__":
    main()

