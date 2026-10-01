#!/usr/bin/env python3
"""02_agent_mcp_session.py

Aperture Example 2: AI Agent Session via Model Context Protocol (MCP)
Demonstrates how an LLM agent interacts with Aperture's bounded compute oracle
using MCP tool calls, protecting authentication tokens from context window leakage.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "sdk" / "python"))

from aperture_client.agent_tools import ApertureAgentTools
from aperture_client.client import Task


def run_mcp_agent_simulation():
    print("===================================================================")
    print("  APERTURE MCP SESSION: Model Context Protocol Agent Demonstration")
    print("===================================================================")

    quote_data = {
        "quote_id": "quote-mcp-demo-99281a",
        "rate_lamports": 1250,
        "max_cost_lamports": 50_000,
        "max_runtime_seconds": 15,
        "effective_runtime_seconds": 15,
        "expires_at": 1893456000,
        "code_sha256": "3fa85f647f3b472e924114259d38c22d732f7389c5a3e8d9eb391f5483f0247b",
        "analysis": {
            "security": "SAFE",
            "reason": "Curated mathematical operations approved",
            "complexity_score": 12.5,
            "cpu": 25,
            "ram": 18,
        },
        "network": "devnet",
    }

    # 1. Initialize Mocked Aperture Client for Offline Demonstration
    mock_client = MagicMock()
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
        "output": '{"mean": 0.0452, "stdev": 0.7071}',
        "receipt": {
            "execution_status": "completed",
            "exit_code": 0,
            "execution_time": 0.042,
            "charged_lamports": 1250,
            "settlement_type": "DEVNET",
            "worker_id": "NODE-CPU-LOCAL",
        },
    }

    # 2. Instantiate ApertureAgentTools (MCP Engine)
    tools = ApertureAgentTools(
        client=mock_client,
        max_cost_lamports=100_000,
        max_runtime_seconds=30,
        execution_enabled=True,
    )
    print("\n[Step 1] Initialized ApertureAgentTools for LLM Context:")
    print(f"  * Configured Max Cost Limit:    {tools.max_cost_lamports:,} lamports (0.0001 SOL)")
    print(f"  * Configured Max Runtime Limit: {tools.max_runtime_seconds}s")
    print(f"  * MCP Execution Enabled:        {tools.execution_enabled}")

    # 3. Tool Call 1: quote_python
    agent_code = """
import math
import statistics

data = [math.sin(i * 0.1) for i in range(1000)]
mean_val = statistics.fmean(data)
std_val = statistics.stdev(data)
print(f"Computed: mean={mean_val:.4f}, stdev={std_val:.4f}")
""".strip()

    print("\n[Step 2] Agent issues MCP Tool Call: 'quote_python'")
    quote_result = tools.quote_python(
        source=agent_code,
        max_cost_lamports=50_000,
        max_runtime_seconds=15,
    )
    print("  <- MCP Tool Response to Agent Context:")
    for k, v in quote_result.items():
        print(f"     {k}: {v}")

    # 4. Explain Token Protection Guarantee
    print("\n[Step 3] Security Architecture Notice:")
    print("  🔒 In-Memory Capability Store: The full signed quote token and private")
    print("     signing material remain stored in the MCP process memory.")
    print("     The LLM model ONLY receives the deterministic quote_id and estimated bounds,")
    print("     preventing Prompt Injection attacks from exfiltrating credentials.")

    # 5. Tool Call 2: start_python_task
    print("\n[Step 4] Agent issues MCP Tool Call: 'start_python_task'")
    start_result = tools.start_python_task(quote_result["quote_id"])
    print("  <- MCP Tool Response to Agent Context:")
    for k, v in start_result.items():
        print(f"     {k}: {v}")

    # 6. Tool Call 3: get_python_task
    print("\n[Step 5] Agent issues MCP Tool Call: 'get_python_task'")
    poll_result = tools.get_python_task(start_result["task_id"])
    print("  <- Verified Execution Result Returned to Agent:")
    print(f"     Task ID:        {poll_result.get('task_id')}")
    print(f"     Status:         {poll_result.get('status')}")
    print(f"     Verified:       {poll_result.get('verified')}")
    print(f"     Output:         {poll_result.get('output')}")
    print(f"     Charged:        {poll_result.get('charged_lamports')} lamports")
    print(f"     Execution Time: {poll_result.get('execution_time_seconds')}s")
    print(f"     Settlement:     {poll_result.get('settlement_type')}")

    print("\n✅ MCP Agent Tooling session successfully executed.")


if __name__ == "__main__":
    run_mcp_agent_simulation()
