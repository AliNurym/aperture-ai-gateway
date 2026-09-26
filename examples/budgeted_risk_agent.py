"""Run a small, reproducible Monte Carlo risk job through Aperture.

This synthetic example demonstrates delegated, capped Python compute. It is
not investment analysis. It never generates keys, sends a deposit, or chooses
an execution budget for you.
"""
import argparse
import json
import os
from pathlib import Path

from aperture_client import ApertureClient, load_keypair


CODE = '''
import json
import math
import random
import statistics

random.seed(20260927)
portfolio_value = 100_000.0
daily_return = 0.0003
daily_volatility = 0.012
days = 30
simulations = 50_000
losses = []
for _ in range(simulations):
    value = portfolio_value
    for _ in range(days):
        draw = random.gauss(daily_return, daily_volatility)
        value *= math.exp(draw - daily_volatility * daily_volatility / 2)
    losses.append(portfolio_value - value)
losses.sort()
var_index = int(0.95 * len(losses))
var_95 = losses[var_index]
tail = losses[var_index:]
summary = {
    "model": "synthetic lognormal daily returns",
    "seed": 20260927,
    "portfolio_value": portfolio_value,
    "days": days,
    "simulations": simulations,
    "probability_of_loss": sum(loss > 0 for loss in losses) / simulations,
    "loss_var_95": var_95,
    "loss_expected_shortfall_95": statistics.fmean(tail),
    "currency": "illustrative units",
    "caveat": "Synthetic assumptions only; not investment advice or a forecast.",
}
print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
'''.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize", action="store_true", help="owner signs a one-day, capped agent passport")
    parser.add_argument("--max-cost-lamports", type=int, default=100_000)
    parser.add_argument("--max-runtime-seconds", type=int, default=30)
    parser.add_argument("--deposit-lamports", type=int, help="explicit owner Devnet payment-channel deposit; never sent automatically")
    parser.add_argument("--output", type=Path, default=Path("aperture-receipt.json"))
    args = parser.parse_args()

    owner_path = os.environ.get("APERTURE_OWNER_KEYPAIR")
    agent_path = os.environ.get("APERTURE_AGENT_KEYPAIR")
    network = os.getenv("APERTURE_NETWORK", "devnet")
    treasury = os.getenv("APERTURE_TREASURY_PUBKEY")
    required = ("APERTURE_GATEWAY_URL", "APERTURE_PROGRAM_ID", "APERTURE_GATEWAY_PUBKEY", owner_path, agent_path)
    if network == "devnet":
        required += (treasury,)
    if not all(required):
        parser.error("Set gateway/program/gateway-signer/treasury public keys and local owner/agent keypair file paths first")
    owner_key = load_keypair(owner_path)
    agent_key = load_keypair(agent_path)
    client = ApertureClient(os.environ["APERTURE_GATEWAY_URL"], owner=str(owner_key.pubkey()), agent_keypair=agent_key,
        program_id=os.environ["APERTURE_PROGRAM_ID"], gateway_pubkey=os.environ["APERTURE_GATEWAY_PUBKEY"],
        network=network, treasury=treasury,
        rpc_url=os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com"))

    if args.authorize:
        passport = client.passport(owner_key, max_cost_lamports=args.max_cost_lamports,
            max_runtime_seconds=args.max_runtime_seconds, total_budget_lamports=args.max_cost_lamports * 10)
        print("Owner delegation confirmed:", passport["agent_pubkey"], passport["attestation"])
    if args.deposit_lamports is not None:
        if client.network != "devnet":
            parser.error("Channel deposits are available only for the explicitly selected Devnet")
        signature = client.fund_channel(owner_key, args.deposit_lamports)
        print("Owner-signed channel deposit:", signature)
    quote = client.quote(CODE, max_cost_lamports=args.max_cost_lamports, max_runtime_seconds=args.max_runtime_seconds)
    print(f"Quote: {quote['rate_lamports']} lamports/s, capped at {quote['max_cost_lamports']} lamports and {quote['max_runtime_seconds']} s")
    task = client.execute(quote, CODE)
    print("Task accepted:", task.task_id)
    result = client.wait(task)
    receipt = result["receipt"]
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Worker output:\n" + result["full_log"])
    print("Receipt:", args.output.resolve())
    print("Settlement:", receipt["settlement_type"], receipt["settlement_signature"])
    print("This receipt verifies signed attribution and hashes; it is not proof the worker ran the source faithfully.")


if __name__ == "__main__":
    main()
