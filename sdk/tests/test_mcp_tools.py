import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "python"))

from aperture_client.agent_tools import ApertureAgentTools, MAX_SOURCE_CHARS
from aperture_client.client import Task
from aperture_client.mcp_server import MCPSettings, create_mcp_server


class FakeClient:
    def __init__(self):
        self.quote_calls = []
        self.execute_calls = []
        self.poll_status = "queued"
        self.wait_result = None
        self.cancel_result = {"status": "stopped", "tx_sig": "settlement-signature"}

    def quote(self, source, **kwargs):
        self.quote_calls.append((source, kwargs))
        quote = {
            "quote_id": f"quote-{len(self.quote_calls)}",
            "code_sha256": "a" * 64,
            "rate_lamports": 2_000,
            "max_cost_lamports": kwargs["max_cost_lamports"],
            "max_runtime_seconds": kwargs["max_runtime_seconds"],
            "effective_runtime_seconds": kwargs["max_runtime_seconds"],
            "expires_at": 4_000_000_000,
            "network": "off_chain",
            "analysis": {"security": "SAFE", "complexity_score": 17},
        }
        return quote

    def execute(self, quote, source, **kwargs):
        self.execute_calls.append((quote, source, kwargs))
        return Task("task-1", "private-task-capability", quote)

    def poll(self, task):
        return {"task_id": task.task_id, "status": self.poll_status}

    def wait(self, task, **kwargs):
        return self.wait_result

    def cancel(self, task):
        return self.cancel_result


def make_tools(*, execution_enabled=True, max_tracked_tasks=4):
    client = FakeClient()
    tools = ApertureAgentTools(client, max_cost_lamports=100_000, max_runtime_seconds=30,
                               execution_enabled=execution_enabled, max_tracked_tasks=max_tracked_tasks)
    return client, tools


class ApertureAgentToolsTests(unittest.TestCase):
    def test_quote_is_preview_only_and_cannot_exceed_local_caps(self):
        client, tools = make_tools(execution_enabled=False)
        quote = tools.quote_python("print('bounded')", max_cost_lamports=50_000, max_runtime_seconds=10)
        self.assertEqual(client.quote_calls[0][1]["max_cost_lamports"], 50_000)
        self.assertEqual(client.quote_calls[0][1]["max_runtime_seconds"], 10)
        self.assertEqual(quote["source_policy"], "SAFE")
        self.assertNotIn("message", quote)
        with self.assertRaisesRegex(ValueError, "configured limit"):
            tools.quote_python("print('too much')", max_cost_lamports=100_001)

    def test_quote_rejects_empty_and_oversized_source(self):
        _, tools = make_tools()
        with self.assertRaises(ValueError):
            tools.quote_python("  \n")
        with self.assertRaisesRegex(ValueError, "gateway limit"):
            tools.quote_python("x" * (MAX_SOURCE_CHARS + 1))

    def test_execution_is_opt_in_and_task_capability_never_leaves_adapter(self):
        client, tools = make_tools(execution_enabled=False)
        quote = tools.quote_python("print('bounded')")
        with self.assertRaisesRegex(PermissionError, "disabled"):
            tools.start_python_task(quote["quote_id"])
        self.assertEqual(client.execute_calls, [])

    def test_quote_start_retry_is_idempotent_and_hides_access_token(self):
        client, tools = make_tools()
        quote = tools.quote_python("print('bounded')")
        first = tools.start_python_task(quote["quote_id"])
        second = tools.start_python_task(quote["quote_id"])
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(len(client.execute_calls), 1)
        self.assertNotIn("private-task-capability", repr(first))

    def test_task_output_is_returned_only_after_client_verification(self):
        client, tools = make_tools()
        quote = tools.quote_python("print('result')")
        task = tools.start_python_task(quote["quote_id"])
        client.poll_status = "completed"
        client.wait_result = {
            "output": "result\n", "full_log": "worker log\n",
            "receipt": {"execution_status": "completed", "exit_code": 0,
                        "execution_time": 0.25, "charged_lamports": 400,
                        "settlement_type": "OFF_CHAIN", "output_sha256": "b" * 64},
        }
        result = tools.get_python_task(task["task_id"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["output"], "result\n")
        self.assertEqual(result["full_log_sha256"], "b" * 64)
        self.assertNotIn("private-task-capability", repr(result))
        self.assertEqual(tools.get_python_task(task["task_id"]), result)

    def test_pending_task_does_not_expose_output(self):
        client, tools = make_tools()
        quote = tools.quote_python("print('not ready')")
        task = tools.start_python_task(quote["quote_id"])
        client.poll_status = "running"
        result = tools.get_python_task(task["task_id"])
        self.assertFalse(result["ready"])
        self.assertNotIn("output", result)
        self.assertIsNone(client.wait_result)

    def test_cancel_returns_no_task_capability(self):
        _, tools = make_tools()
        quote = tools.quote_python("print('bounded')")
        task = tools.start_python_task(quote["quote_id"])
        result = tools.cancel_python_task(task["task_id"])
        self.assertEqual(result["status"], "cancellation_requested")
        self.assertNotIn("settlement_signature", result)
        self.assertNotIn("private-task-capability", repr(result))

    def test_active_task_limit_fails_closed(self):
        _, tools = make_tools(max_tracked_tasks=1)
        first = tools.quote_python("print(1)")
        tools.start_python_task(first["quote_id"])
        second = tools.quote_python("print(2)")
        with self.assertRaisesRegex(RuntimeError, "maximum number of active tasks"):
            tools.start_python_task(second["quote_id"])


class MCPSettingsTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "APERTURE_GATEWAY_URL": "http://127.0.0.1:8000",
            "APERTURE_OWNER_PUBKEY": "owner-public-key",
            "APERTURE_AGENT_KEYPAIR": "C:/keys/agent.json",
            "APERTURE_PROGRAM_ID": "program-public-key",
            "APERTURE_GATEWAY_PUBKEY": "gateway-public-key",
            "APERTURE_NETWORK": "off_chain",
            "APERTURE_MCP_MAX_COST_LAMPORTS": "100000",
            "APERTURE_MCP_MAX_RUNTIME_SECONDS": "30",
        }

    def test_requires_explicit_local_execution_enablement(self):
        settings = MCPSettings.from_env(self.env)
        self.assertFalse(settings.execution_enabled)
        self.assertEqual(settings.max_cost_lamports, 100_000)

    def test_devnet_requires_pinned_treasury(self):
        self.env["APERTURE_NETWORK"] = "devnet"
        with self.assertRaisesRegex(ValueError, "TREASURY"):
            MCPSettings.from_env(self.env)

    def test_rejects_runtime_above_gateway_limit(self):
        self.env["APERTURE_MCP_MAX_RUNTIME_SECONDS"] = "181"
        with self.assertRaisesRegex(ValueError, "between 1 and 180"):
            MCPSettings.from_env(self.env)


class MCPServerRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_advertises_python_data_and_workflow_tools(self):
        try:
            from mcp import Client
        except ImportError:
            self.skipTest("Install the optional sdk[mcp] extra to test MCP protocol registration.")

        _, tools = make_tools(execution_enabled=False)
        server = create_mcp_server(tools)
        async with Client(server) as client:
            listed = await client.list_tools()
            quote = await client.call_tool("quote_python", {"source": "print('agent')"})
        self.assertEqual(
            {tool.name for tool in listed.tools},
            {"quote_python", "start_python_task", "list_python_tasks", "resume_python_task",
             "get_python_task", "cancel_python_task", "upload_compute_input", "quote_compute_job",
             "start_compute_job", "read_compute_artifact", "get_compute_storage", "release_compute_object",
             "prepare_compute_workflow", "start_compute_workflow", "get_compute_workflow", "cancel_compute_workflow",
             "get_assigned_workflows", "start_assigned_workflow", "get_assigned_workflow_progress"},
        )
        self.assertFalse(quote.is_error)
        self.assertIn("quote-1", repr(quote.structured_content) + repr(quote.content))


if __name__ == "__main__":
    unittest.main()
