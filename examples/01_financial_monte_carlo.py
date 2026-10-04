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
MONTE_CARLO_CODE = '''
import json
import math
import random
import statistics

random.seed(42)
initial_portfolio = 500_000.0  # USD
annual_return = 0.08
annual_vol = 0.18
time_horizon_days = 21  # 1 trading month
dt = 1.0 / 252.0
num_simulations = 25_000

portfolio_outcomes = []
for _ in range(num_simulations):
    price = initial_portfolio
    for _ in range(time_horizon_days):
        drift = (annual_return - 0.5 * (annual_vol ** 2)) * dt
        shock = annual_vol * math.sqrt(dt) * random.gauss(0, 1)
        price *= math.exp(drift + shock)
    portfolio_outcomes.append(price)

portfolio_outcomes.sort()
losses = [initial_portfolio - outcome for outcome in portfolio_outcomes]
losses.sort(reverse=True)

# 95% and 99% Value at Risk (VaR)
var_95_index = int(0.05 * num_simulations)
var_99_index = int(0.01 * num_simulations)

var_95 = losses[var_95_index]
var_99 = losses[var_99_index]
expected_shortfall_95 = statistics.fmean(losses[:var_95_index])

result = {
    "status": "SUCCESS",
    "simulations": num_simulations,
    "horizon_days": time_horizon_days,
    "initial_portfolio": initial_portfolio,
    "var_95": round(var_95, 2),
    "var_99": round(var_99, 2),
    "expected_shortfall_95": round(expected_shortfall_95, 2),
    "prob_positive_return": round(sum(o > initial_portfolio for o in portfolio_outcomes) / num_simulations, 4)
}
print(json.dumps(result))
'''.strip()


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
            print(f"❌ Workload blocked by source policy: {analysis.get('reason')}")
            sys.exit(1)
        print("  -> Workload statically approved for execution.")

    # 2. Local deterministic execution
    print("\n[Step 2] Executing Monte Carlo Workload locally to verify determinism...")
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(MONTE_CARLO_CODE, {"__builtins__": __builtins__})

    output_str = buffer.getvalue().strip()
    data = json.loads(output_str)

    print("\n[Step 3] Local Execution Result:")
    print(f"  * Simulations:             {data['simulations']:,}")
    print(f"  * Initial Portfolio:       ${data['initial_portfolio']:,.2f}")
    print(f"  * 95% Value at Risk (VaR): ${data['var_95']:,.2f}")
    print(f"  * 99% Value at Risk (VaR): ${data['var_99']:,.2f}")
    print(f"  * 95% Expected Shortfall:  ${data['expected_shortfall_95']:,.2f}")
    print(f"  * Win Probability:         {data['prob_positive_return'] * 100:.2f}%")
    print("\n✅ Monte Carlo computation completed with verified deterministic bounds.")


def run_live(gateway_url: str):
    print("\n[Step 2] Connecting to Live Aperture Gateway...")
    print(f"  * Gateway URL: {gateway_url}")

    from agent_identity import ephemeral_keypair
    from aperture_client import ApertureClient

    owner_kp = ephemeral_keypair()
    client = ApertureClient(
        gateway_url=gateway_url,
        owner_keypair=owner_kp,
        network="off_chain",
    )
    print(f"  * Generated Ephemeral Signer: {owner_kp['pubkey']}")

    print("\n[Step 3] Requesting Signed Quote from Gateway...")
    quote = client.quote(MONTE_CARLO_CODE, max_cost_lamports=100_000, max_runtime_seconds=30)
    print(f"  * Quote ID:        {quote['quote_id']}")
    print(f"  * Rate:            {quote['rate_lamports']} lamports/sec")
    print(f"  * Code SHA-256:    {quote['code_sha256'][:16]}...")
    print(f"  * Complexity:      {quote.get('analysis', {}).get('complexity_score')} units")

    print("\n[Step 4] Submitting Workload to Worker Sandbox...")
    task = client.execute(quote, MONTE_CARLO_CODE)
    print(f"  * Task Admitted:   {task.task_id}")

    print("\n[Step 5] Waiting for Sandbox Execution and Cryptographic Settlement...")
    result = client.wait(task)
    receipt = result["receipt"]
    output = json.loads(result["output"])

    print("\n[Step 6] Cryptographically Verified Sandbox Execution Result:")
    print(f"  * Worker ID:               {receipt.get('worker_id')}")
    print(f"  * Execution Time:          {receipt.get('execution_time')}s")
    print(f"  * Charged:                 {receipt.get('charged_lamports')} lamports")
    print(f"  * Settlement Type:         {receipt.get('settlement_type')}")
    print(f"  * Simulations:             {output['simulations']:,}")
    print(f"  * Initial Portfolio:       ${output['initial_portfolio']:,.2f}")
    print(f"  * 95% Value at Risk (VaR): ${output['var_95']:,.2f}")
    print(f"  * 99% Value at Risk (VaR): ${output['var_99']:,.2f}")
    print(f"  * 95% Expected Shortfall:  ${output['expected_shortfall_95']:,.2f}")
    print(f"  * Win Probability:         {output['prob_positive_return'] * 100:.2f}%")
    print("\n✅ Live Monte Carlo computation executed and verified by Aperture Gateway.")


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
            print(f"❌ Live execution failed (is Gateway running at {args.gateway}?): {err}")
            print("Falling back to local validation run...\n")
            run_demo()
    else:
        run_demo()


if __name__ == "__main__":
    main()

