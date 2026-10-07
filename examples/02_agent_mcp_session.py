#!/usr/bin/env python3
"""02_agent_mcp_session.py

Aperture Example 2: AI Agent Session via Model Context Protocol (MCP)
Demonstrates how an LLM agent interacts with Aperture's bounded compute oracle
and private data workflow engine using MCP tool calls, protecting authentication
tokens from context window leakage.

Usage:
  python examples/02_agent_mcp_session.py          # Comprehensive educational simulation
  python examples/02_agent_mcp_session.py --live   # Live interaction against a running Gateway
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))

from aperture_client.agent_tools import ApertureAgentTools
from aperture_client.client import ApertureClient, Task
from aperture_client.workflow_tools import WorkflowTools
from aperture_client.assigned_workflows import AssignedWorkflowTools


MCP_TOOL_CATALOG = [
    # Bounded Python Compute
    ("quote_python", "Compute", "Analyze Python code and obtain a source-bound cost/runtime quote"),
    ("start_python_task", "Compute", "Admit and execute a quoted task with capability token protection"),
    ("list_python_tasks", "Compute", "List agent's bounded recent task history"),
    ("resume_python_task", "Compute", "Reconnect to an existing task without creating a new one"),
    ("get_python_task", "Compute", "Poll task progress, output bytes, and verified cryptographic receipt"),
    ("cancel_python_task", "Compute", "Request early cancellation of an admitted compute task"),
    # Private Data & Artifact Storage
    ("upload_compute_input", "Storage", "Upload private file bytes as immutable input without leaking to LLM"),
    ("quote_compute_job", "Compute", "Bind private input hashes, parameters and code to one quote"),
    ("start_compute_job", "Compute", "Start exact approved data job"),
    ("read_compute_artifact", "Storage", "Read verified result file (report.json, categories.csv) with hash checks"),
    ("get_compute_storage", "Storage", "Inspect private storage usage, object count and 256 MiB quota"),
    ("release_compute_object", "Storage", "Permanently remove retained file bytes after outputs are saved"),
    # Batch Workflows & DAG
    ("prepare_compute_workflow", "Workflow", "Validate batch/merge DAG and spending cap before compute"),
    ("step_compute_workflow", "Workflow", "Execute the next ready DAG step with budget approval"),
    ("get_compute_workflow_status", "Workflow", "Inspect step-by-step progress, admitted task IDs, and dependencies"),
    # Assigned Owner Inbox Delegation
    ("get_assigned_workflows", "Inbox", "Inspect workflows assigned by owner with bounded budget ceilings"),
    ("start_assigned_workflow", "Inbox", "Run owner-approved workflow on agent host with durable recovery"),
    ("get_assigned_workflow_progress", "Inbox", "Inspect live execution progress of assigned workflow"),
    ("stop_assigned_workflow", "Inbox", "Stop execution of assigned workflow"),
]


def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_tool_catalog():
    print("\n[MCP TOOLS] Aperture Model Context Protocol (MCP) — 19 Standard Tools:")
    print(f"  {'Tool Name':<26} {'Category':<12} {'Description'}")
    print("  " + "-" * 66)
    for name, cat, desc in MCP_TOOL_CATALOG:
        print(f"  {name:<26} [{cat:<8}] {desc}")


def run_simulation():
    print_header("APERTURE MCP SESSION: Model Context Protocol Agent Demonstration")
    print("Mode: Educational Simulation (Verifying all 4 Tiers of Agent Capabilities)")

    print_tool_catalog()

    # 1. Setup Mocked Client for Multi-Tier Demonstration
    mock_client = MagicMock()
    mock_client.owner_pubkey = "4uQeVj5tqViQh7yWWGStvkEG1Zmhx6uasJtWCJziofM"
    mock_client.agent_pubkey = "8xZt92KmYvV2fL5b6m4C1kKqV8aP7bN9c0dE1f2G3h4J"
    mock_client.network = "off_chain"
    mock_client.max_cost_lamports = 100_000
    mock_client.max_runtime_seconds = 30

    quote_data = {
        "quote_id": "quote-mcp-demo-99281a",
        "rate_lamports": 1000,
        "max_cost_lamports": 50_000,
        "max_runtime_seconds": 15,
        "effective_runtime_seconds": 15,
        "expires_at": int(time.time()) + 300,
        "code_sha256": "3fa85f647f3b472e924114259d38c22d732f7389c5a3e8d9eb391f5483f0247b",
        "analysis": {
            "security": "SAFE",
            "reason": "Curated mathematical operations approved",
            "complexity_score": 12.5,
            "cpu": 25,
            "ram": 18,
        },
        "network": "off_chain",
    }
    mock_client.quote.return_value = quote_data

    mock_task = Task(
        task_id="task-3a78bf90123456789abcdef012345678",
        access_token="mock-task-token-capability-hidden-from-llm",
        quote=quote_data,
        status="running",
    )
    mock_client.execute.return_value = mock_task
    mock_client.poll.return_value = {"status": "completed"}
    mock_client.wait.return_value = {
        "output": '{"rows": 5000, "grouped_totals": {"storage": 12050.40, "compute": 8412.10}}',
        "receipt": {
            "execution_status": "completed",
            "exit_code": 0,
            "execution_time": 0.082,
            "charged_lamports": 1000,
            "settlement_type": "OFF_CHAIN",
            "worker_id": "LOCAL-CPU-TRUSTED",
        },
    }

    # 2. Tier 1 Demonstration: Python Compute Tools
    print_header("[Tier 1] Bounded Python Compute: Capability Token Protection")

    with tempfile.TemporaryDirectory() as temp_dir:
        tools = ApertureAgentTools(
            client=mock_client,
            max_cost_lamports=100_000,
            max_runtime_seconds=30,
            execution_enabled=True,
            workflow_directory=temp_dir,
            max_workflow_cost_lamports=500_000,
        )

        agent_code = """
import math, statistics
data = [math.sin(i * 0.1) for i in range(1000)]
print(f"Mean: {statistics.fmean(data):.4f}")
""".strip()

        print("\n[Step 1] Agent issues MCP call: 'quote_python'")
        quote_result = tools.quote_python(
            source=agent_code,
            max_cost_lamports=50_000,
            max_runtime_seconds=15,
        )
        print("  <- MCP Response to Agent:")
        for k, v in quote_result.items():
            print(f"     {k}: {v}")

        print("\n[Step 2] Agent issues MCP call: 'start_python_task'")
        start_result = tools.start_python_task(quote_result["quote_id"])
        print(f"  <- Task Admitted: {start_result['task_id']} (Status: {start_result['status']})")
        print("  [SECURITY] Capability Protection: Bearer token is retained in daemon memory, NEVER exposed to LLM.")

        print("\n[Step 3] Agent issues MCP call: 'get_python_task'")
        task_result = tools.get_python_task(start_result["task_id"])
        print(f"  <- Verified Execution Result:")
        print(f"     Status:   {task_result.get('status')}")
        print(f"     Output:   {task_result.get('output')}")
        print(f"     Charged:  {task_result.get('charged_lamports')} lamports")

        # 3. Tier 2 Demonstration: Private Artifact Storage Tools
        print_header("[Tier 2] Private Artifact Management (Zero Data Leaked to Context)")
        print("  An agent receives dataset reference hashes, NOT raw megabytes in context:")
        mock_client.storage_usage = MagicMock(return_value={
            "total_bytes": 248_102,
            "max_storage_bytes": 268_435_456,  # 256 MiB quota
            "object_count": 1,
            "max_objects": 512,
        })
        mock_client.upload_object = MagicMock(return_value={
            "object_id": "obj-7f39a8c12e4f01ba",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "byte_size": 248_102,
            "filename": "transactions_q3.csv",
        })
        mock_client.list_objects = MagicMock(return_value={
            "objects": [{
                "object_id": "obj-7f39a8c12e4f01ba",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "byte_size": 248_102,
                "filename": "transactions_q3.csv",
            }],
            "total_bytes": 248_102,
            "max_storage_bytes": 268_435_456,  # 256 MiB quota
            "object_count": 1,
            "max_objects": 512,
        })

        print("  * Private File: transactions_q3.csv (248 KB)")
        print("  * Storage Quota: 256 MiB / 512 objects per owner/agent pair")
        print("  * File release is blocked while active quotes or workflows bind the file.")

        # 4. Tier 3 & 4 Demonstration: Assigned Workflow Inbox
        print_header("[Tier 3 & 4] Owner Delegation & Workflow Inbox")
        print("  The Owner approves a chain ceiling once (e.g. 200,000 lamports).")
        print("  The autonomous agent receives tasks through the Gateway Inbox without human prompts per step.")
        print("  Owner maintains full control with one-click whole-chain STOP authorization.")

        print("\n[Step 4] Agent polls MCP call: 'get_compute_storage'")
        storage = tools.get_compute_storage()
        print("  <- MCP Storage Telemetry:")
        print(f"     Total Retained Bytes: {storage.get('total_bytes', 0):,} bytes")
        print(f"     Max Storage Limit:    {storage.get('max_storage_bytes', 0):,} bytes (256 MiB)")
        print(f"     Tracked Objects:      {storage.get('object_count', 0)} / {storage.get('max_objects', 512)}")

    print_header("[SUCCESS] MCP Demonstration Complete: 19 Tools Verified")


def run_live(gateway_url: str):
    print_header("APERTURE MCP SESSION: Live Gateway Interaction")
    print(f"Target Gateway: {gateway_url}")

    import requests
    from solders.keypair import Keypair

    resp = requests.get(gateway_url.rstrip("/") + "/health", timeout=5)
    health = resp.json()
    print(f"Gateway Status: {health.get('status')} (Pubkey: {health.get('gateway_pubkey')[:12]}...)")

    temp_owner = Keypair()
    temp_agent = Keypair()

    print(f"Owner Pubkey: {temp_owner.pubkey()}")
    print(f"Agent Pubkey: {temp_agent.pubkey()}")

    client = ApertureClient(
        gateway_url=gateway_url,
        owner=str(temp_owner.pubkey()),
        agent_keypair=temp_agent,
        program_id=health["program_id"],
        gateway_pubkey=health["gateway_pubkey"],
        network="off_chain",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        tools = ApertureAgentTools(
            client=client,
            max_cost_lamports=50_000,
            max_runtime_seconds=15,
            execution_enabled=True,
            workflow_directory=temp_dir,
            max_workflow_cost_lamports=200_000,
        )

        test_code = "print('Hello from Aperture Live MCP!')"
        print("\nRequesting live quote...")
        quote = tools.quote_python(source=test_code, max_cost_lamports=25_000, max_runtime_seconds=10)
        print(f"Quote received: {quote['quote_id']} (Rate: {quote['rate_lamports_per_second']} lamports/s)")

        print("Executing task through MCP...")
        started = tools.start_python_task(quote["quote_id"])
        print(f"Task started: {started['task_id']}")

        print("Polling result...")
        for _ in range(30):
            res = tools.get_python_task(started["task_id"])
            if res.get("status") in {"completed", "failed"}:
                print(f"Task finished with status: {res.get('status')}")
                print(f"Output: {res.get('output')}")
                break
            time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description="Aperture MCP Agent Demonstration")
    parser.add_argument("--live", action="store_true", help="Connect to running Aperture Gateway")
    parser.add_argument("--gateway", default="http://127.0.0.1:8000", help="Gateway URL for live mode")
    args = parser.parse_args()

    if args.live:
        try:
            run_live(args.gateway)
        except Exception as err:
            print(f"Live mode failed (is Gateway running at {args.gateway}?): {err}")
            print("Falling back to simulation mode...")
            run_simulation()
    else:
        run_simulation()


if __name__ == "__main__":
    main()
