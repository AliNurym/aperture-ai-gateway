"""Receive signed console workflows on this configured dedicated agent host.

Uses the same environment and operator ceilings as the MCP server. Private agent
keys stay here. Ctrl+C stops receiving; restart with the same directory to recover.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python"))
from aperture_client import ApertureClient, load_keypair
from aperture_client.agent_tools import ApertureAgentTools
from aperture_client.mcp_server import MCPSettings


def main():
    settings = MCPSettings.from_env()
    if not settings.execution_enabled or not settings.workflow_directory:
        raise ValueError("Enable MCP execution and configure a durable workflow directory before receiving work.")
    client = ApertureClient(settings.gateway_url, owner=settings.owner_pubkey,
        agent_keypair=load_keypair(settings.agent_keypair_path), program_id=settings.program_id,
        gateway_pubkey=settings.gateway_pubkey, network=settings.network,
        treasury=settings.treasury_pubkey, rpc_url=settings.rpc_url)
    if client.owner == client.agent:
        raise ValueError("The receiver requires a dedicated agent key and an owner-issued passport.")
    tools = ApertureAgentTools(client, max_cost_lamports=settings.max_cost_lamports,
        max_runtime_seconds=settings.max_runtime_seconds, max_rate_lamports=settings.max_rate_lamports,
        execution_enabled=True, workflow_directory=settings.workflow_directory,
        max_workflow_cost_lamports=settings.max_workflow_cost_lamports)
    attempted, previous = set(), None
    print("Receiver ready for owner-approved workflows. Agent: " + client.agent, flush=True)
    try:
        while True:
            current = tools.inbox.get()
            encoded = json.dumps(current, sort_keys=True)
            if encoded != previous:
                print(encoded, flush=True); previous = encoded
            if not tools.inbox.busy:
                for flow in tools.inbox.list():
                    identifier = flow["workflow_id"]
                    if identifier not in attempted and not flow.get("stop_requested"):
                        attempted.add(identifier)
                        try:
                            print(json.dumps(tools.inbox.start(identifier)), flush=True)
                        except Exception as error:
                            print(json.dumps({"workflow_id": identifier, "status": "attention", "detail": str(error)[:1500]}), flush=True)
                        break
            time.sleep(2)
    except KeyboardInterrupt:
        tools.inbox.stop()
        print("Receiver stopped. Restart with the same workflow directory to recover retained progress.", flush=True)
    finally:
        client.http.close()


if __name__ == "__main__":
    main()
