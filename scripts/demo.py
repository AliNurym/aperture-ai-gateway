"""Prepare explicit local development settings or run a real, signed workload.

This helper never deploys a program, deposits funds or reports off-chain work as
a Solana payment. Private settings stay in the ignored .aperture/demo directory.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
STATE = PROJECT / ".aperture" / "demo"
sys.path.insert(0, str(PROJECT / "sdk" / "python"))

from aperture_client import ApertureClient, load_keypair
from solders.keypair import Keypair


def prepare():
    STATE.mkdir(parents=True, exist_ok=True)
    settings = STATE / "gateway.env"
    if settings.exists():
        raise SystemExit("Local settings already exist; reuse them. Existing keys were preserved.")
    if not list((STATE / "approved").glob("*.py")):
        raise SystemExit("Export and review the Python examples in .aperture/demo/approved first.")
    gateway, owner, agent = Keypair(), Keypair(), Keypair()
    for name, key in (("gateway", gateway), ("owner", owner), ("agent", agent)):
        path = STATE / f"{name}.keypair.json"
        with path.open("x", encoding="utf-8") as output:
            json.dump(list(bytes(key)), output)
    public = {
        "gateway_url": "http://127.0.0.1:8000",
        "program_id": "A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ",
        "gateway_pubkey": str(gateway.pubkey()),
        "owner_pubkey": str(owner.pubkey()),
        "agent_pubkey": str(agent.pubkey()),
        "network": "off_chain",
    }
    (STATE / "public.json").write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    values = {
        "APERTURE_ENV": "development",
        "APERTURE_DEMO_MODE": "true",
        "BACKEND_PRIVATE_KEY": json.dumps(list(bytes(gateway)), separators=(",", ":")),
        "APERTURE_WORKER_TOKEN": secrets.token_urlsafe(48),
        "APERTURE_STATE_DB": str(STATE / "gateway.sqlite3"),
        "APERTURE_WORKER_STATE_DIR": str(STATE / "worker"),
        "APERTURE_TRUSTED_SOURCE_DIRECTORY": str(STATE / "approved"),
        "GATEWAY_API_URL": public["gateway_url"],
        "SOLANA_PROGRAM_ID": public["program_id"],
        "CORS_ORIGINS": "http://127.0.0.1:3000,http://localhost:3000",
    }
    with settings.open("x", encoding="utf-8", newline="\n") as output:
        for name, value in values.items():
            output.write(f"{name}={json.dumps(value)}\n")
    print("Prepared local settings and stable development identities.")
    print("Execution uses real Python; settlement is OFF_CHAIN, with no Solana payment.")
    print("Use Docker, or explicitly select a trusted local worker for reviewed sources.")
    print("Gateway signing identity:", public["gateway_pubkey"])


def execute(workload):
    public = json.loads((STATE / "public.json").read_text(encoding="utf-8"))
    if public["network"] != "off_chain":
        raise SystemExit("This helper is scoped to explicit local off-chain development.")
    owner = load_keypair(STATE / "owner.keypair.json")
    agent = load_keypair(STATE / "agent.keypair.json")
    client = ApertureClient(public["gateway_url"], owner=str(owner.pubkey()), agent_keypair=agent,
        program_id=public["program_id"], gateway_pubkey=public["gateway_pubkey"], network="off_chain")
    health = client.request("GET", "/health").json()
    if health.get("status") != "ready" or health.get("gateway_pubkey") != public["gateway_pubkey"]:
        raise SystemExit("Configured gateway and authenticated worker are not ready.")
    policy = client.list_agent_passports(owner)
    if not any(item.get("agent_pubkey") == str(agent.pubkey()) and not item.get("revoked")
               and item.get("expires_at", 0) > time.time() for item in policy):
        client.passport(owner, name="Local risk analysis agent", max_cost_lamports=1_000_000,
            max_runtime_seconds=30, total_budget_lamports=10_000_000)
    code = (STATE / "approved" / f"{workload}.py").read_bytes().decode("utf-8")
    quote = client.quote(code, max_cost_lamports=1_000_000, max_runtime_seconds=30, max_rate_lamports=1_000_000)
    task = client.execute(quote, code, max_rate_lamports=1_000_000)
    print("Accepted real task:", task.task_id, flush=True)
    result = client.wait(task, timeout_seconds=60)
    receipt = result["receipt"]
    folder = STATE / "evidence"
    folder.mkdir(exist_ok=True)
    (folder / f"{task.task_id}.receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    (folder / f"{task.task_id}.output.txt").write_text(result["full_log"], encoding="utf-8", newline="")
    print(result["full_log"], end="" if result["full_log"].endswith("\n") else "\n")
    print(json.dumps({"task_id": task.task_id, "execution_status": receipt["execution_status"],
        "settlement_type": receipt["settlement_type"], "execution_backend": receipt["execution_backend"],
        "execution_seconds": receipt["execution_time"], "worker_id": receipt["worker_id"],
        "source_sha256": receipt["code_sha256"], "output_sha256": receipt["output_sha256"],
        "gateway_and_worker_signatures": "verified", "evidence_directory": str(folder)}, indent=2))
    if receipt["execution_status"] != "completed":
        raise SystemExit("Worker reported a non-successful outcome; inspect the retained evidence.")


def serve(service):
    from dotenv import load_dotenv
    load_dotenv(STATE / "gateway.env", override=True)
    import os
    os.chdir(PROJECT / "backend")
    sys.path.insert(0, str(PROJECT / "backend"))
    if service == "gateway":
        import uvicorn
        uvicorn.run("main:app", host="127.0.0.1", port=8000, access_log=False)
    else:
        import worker
        if not worker.ALLOW_UNSAFE_LOCAL_EXECUTION:
            raise SystemExit("Select Docker through scripts/start.ps1, or explicitly pass --allow-unsafe-local-execution here.")
        worker.main()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "gateway", "worker", "run"))
    parser.add_argument("--off-chain", action="store_true")
    parser.add_argument("--allow-unsafe-local-execution", action="store_true")
    parser.add_argument("--workload", choices=("risk", "math", "statistics"), default="risk")
    arguments = parser.parse_args()
    if arguments.action == "prepare":
        if not arguments.off_chain:
            parser.error("Explicit --off-chain selection is required. This helper does not initialize Devnet.")
        prepare()
    elif arguments.action == "run":
        execute(arguments.workload)
    else:
        serve(arguments.action)
