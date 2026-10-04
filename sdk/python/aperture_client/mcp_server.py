"""Local stdio MCP server that exposes Aperture's bounded Python compute tools."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .agent_tools import ApertureAgentTools
from .client import ApertureClient, load_keypair


@dataclass(frozen=True)
class MCPSettings:
    gateway_url: str
    owner_pubkey: str
    agent_keypair_path: str
    program_id: str
    gateway_pubkey: str
    network: str
    treasury_pubkey: str | None
    rpc_url: str | None
    max_cost_lamports: int
    max_runtime_seconds: int
    max_rate_lamports: int
    execution_enabled: bool
    max_pending_quotes: int
    max_tracked_tasks: int
    workflow_directory: str | None = None
    max_workflow_cost_lamports: int | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "MCPSettings":
        env = os.environ if environ is None else environ

        def required(name: str) -> str:
            value = env.get(name, "").strip()
            if not value:
                raise ValueError(f"Set {name} in the MCP host environment.")
            return value

        def integer(name: str, *, minimum: int, maximum: int, default: int | None = None) -> int:
            raw = env.get(name, "") if default is None else env.get(name, str(default))
            try:
                value = int(raw)
            except (TypeError, ValueError) as error:
                raise ValueError(f"{name} must be an integer.") from error
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}.")
            return value

        network = required("APERTURE_NETWORK").lower()
        if network not in {"devnet", "off_chain"}:
            raise ValueError("APERTURE_NETWORK must be devnet or off_chain.")
        treasury = env.get("APERTURE_TREASURY_PUBKEY", "").strip() or None
        if network == "devnet" and treasury is None:
            raise ValueError("Set APERTURE_TREASURY_PUBKEY for Devnet.")
        allow_execution = env.get("APERTURE_MCP_EXECUTION_ENABLED", "false").strip().lower()
        if allow_execution not in {"true", "false"}:
            raise ValueError("APERTURE_MCP_EXECUTION_ENABLED must be true or false.")

        return cls(
            gateway_url=required("APERTURE_GATEWAY_URL"),
            owner_pubkey=required("APERTURE_OWNER_PUBKEY"),
            agent_keypair_path=required("APERTURE_AGENT_KEYPAIR"),
            program_id=required("APERTURE_PROGRAM_ID"),
            gateway_pubkey=required("APERTURE_GATEWAY_PUBKEY"),
            network=network,
            treasury_pubkey=treasury,
            rpc_url=env.get("SOLANA_RPC_URL", "").strip() or None,
            max_cost_lamports=integer("APERTURE_MCP_MAX_COST_LAMPORTS", minimum=1, maximum=1_000_000_000),
            max_runtime_seconds=integer("APERTURE_MCP_MAX_RUNTIME_SECONDS", minimum=1, maximum=180),
            max_rate_lamports=integer("APERTURE_MCP_MAX_RATE_LAMPORTS", minimum=1,
                                      maximum=1_000_000_000, default=25_000),
            execution_enabled=allow_execution == "true",
            max_pending_quotes=integer("APERTURE_MCP_MAX_PENDING_QUOTES", minimum=1, maximum=64, default=8),
            max_tracked_tasks=integer("APERTURE_MCP_MAX_TRACKED_TASKS", minimum=1, maximum=256, default=64),
            workflow_directory=env.get("APERTURE_MCP_WORKFLOW_DIRECTORY", "").strip() or None,
            max_workflow_cost_lamports=integer("APERTURE_MCP_MAX_WORKFLOW_COST_LAMPORTS",
                minimum=1, maximum=100_000_000_000,
                default=integer("APERTURE_MCP_MAX_COST_LAMPORTS", minimum=1, maximum=1_000_000_000)),
        )


def create_mcp_server(tools: ApertureAgentTools):
    """Register the agent tools with the optional official MCP Python SDK."""
    try:
        from mcp.server import MCPServer
    except ImportError as error:
        raise RuntimeError("Install the MCP extra with: python -m pip install -e 'sdk[mcp]'.") from error

    server = MCPServer(
        "Aperture Compute",
        instructions=(
            "Aperture runs bounded data jobs and dependent compute workflows on remote workers. "
            "Use upload_compute_input for data, then quote_compute_job and start_compute_job. "
            "For batches or chains, prepare_compute_workflow validates the DAG and total budget; "
            "start_compute_workflow runs or resumes it in the background. Poll get_compute_workflow "
            "for outputs, and read_compute_artifact to obtain small verified result files. "
            "For source-only jobs, first call quote_python. "
            "Only start a task when the returned source hash and budget are appropriate. After a "
            "server restart, use list_python_tasks and resume_python_task to reconnect without a "
            "new admission. If a start response is uncertain, recover the task for that quote_id "
            "through history before requesting another workload. Poll with get_python_task until "
            "ready; use only output marked verified. "
            "Owner-issued agent "
            "limits and the MCP server's local cost/runtime ceilings apply. A verified receipt "
            "attributes signed evidence; it does not prove correct remote computation."
        ),
    )

    @server.tool(name="quote_python", title="Quote bounded Python compute")
    def quote_python(source: str, max_cost_lamports: int | None = None,
                     max_runtime_seconds: int | None = None) -> dict:
        """Inspect source policy and maximum charge without running the Python.

        Optional cost/runtime values can lower, but cannot exceed, the local
        MCP server ceilings. The exact source stays in this process for the
        short quote lifetime so start_python_task can run what was reviewed.
        """
        return tools.quote_python(source, max_cost_lamports, max_runtime_seconds)

    @server.tool(name="start_python_task", title="Start quoted Python compute")
    def start_python_task(quote_id: str) -> dict:
        """Run the exact source identified by a quote, within all configured limits.

        Execution requires the local operator to enable it. Repeating the same
        quote_id returns the same task instead of creating another admission.
        """
        return tools.start_python_task(quote_id)

    @server.tool(name="list_python_tasks", title="List this agent's recent tasks")
    def list_python_tasks(limit: int = 20, cursor: str | None = None) -> dict:
        """List recent tasks for the configured owner and agent keys.

        The response contains bounded metadata, not task capabilities or source.
        Pass next_cursor back as cursor to read an older page.
        """
        return tools.list_python_tasks(limit, cursor)

    @server.tool(name="resume_python_task", title="Resume an existing Python task")
    def resume_python_task(task_id: str) -> dict:
        """Recover access to an existing task without repeating task admission."""
        return tools.resume_python_task(task_id)

    @server.tool(name="get_python_task", title="Get Python task result")
    def get_python_task(task_id: str) -> dict:
        """Poll task status; final output appears only after receipt verification.

        Poll again after the returned retry_after_seconds while status is not
        ready. Do not treat pending output as a completed task.
        """
        return tools.get_python_task(task_id)

    @server.tool(name="cancel_python_task", title="Cancel Python task")
    def cancel_python_task(task_id: str) -> dict:
        """Request cancellation of a running task. Poll afterward for its final receipt."""
        return tools.cancel_python_task(task_id)

    @server.tool(name="upload_compute_input", title="Stage data for an agent compute job")
    def upload_compute_input(name: str, content_base64: str) -> dict:
        """Upload up to 1 MiB of agent-provided bytes as a private immutable input.

        This tool never opens a path on the MCP host. Use the Python SDK to upload
        caller-selected larger datasets, then pass their object references here.
        """
        return tools.upload_compute_input(name, content_base64)

    @server.tool(name="quote_compute_job", title="Quote an agent job with data and parameters")
    def quote_compute_job(source: str, inputs: list[dict], parameters: dict | None = None,
                          max_cost_lamports: int | None = None,
                          max_runtime_seconds: int | None = None) -> dict:
        """Bind input hashes, parameters and source to one spend-bounded quote.

        Source can import aperture to read_csv/read_json and write_csv/write_json.
        A completed task exposes signed artifact references. Pass those references
        as inputs to a later job to build a chain without copying data into chat.
        Start using start_compute_job, then poll get_python_task.
        """
        return tools.quote_compute_job(source, inputs, parameters, max_cost_lamports, max_runtime_seconds)

    @server.tool(name="start_compute_job", title="Start the exact approved data job")
    def start_compute_job(quote_id: str) -> dict:
        """Start the source, immutable inputs and parameters held for this quote."""
        return tools.start_python_task(quote_id)

    @server.tool(name="read_compute_artifact", title="Read a verified compute result file")
    def read_compute_artifact(task_id: str, name: str, max_bytes: int = 65536) -> dict:
        """Return verified file bytes as base64, up to the caller's limit (at most 1 MiB).

        Task ownership, both receipt signatures and the file hash are checked.
        Larger files remain reusable references for downstream computation.
        This tool never writes a path on the MCP host.
        """
        return tools.read_compute_artifact(task_id, name, max_bytes)

    @server.tool(name="get_compute_storage", title="Inspect private compute storage")
    def get_compute_storage() -> dict:
        """List this agent's retained input/result references and storage quota."""
        return tools.get_compute_storage()

    @server.tool(name="release_compute_object", title="Release retained compute data")
    def release_compute_object(reference: dict) -> dict:
        """Permanently remove selected retained file bytes after needed outputs are saved.

        Requires explicit caller intent to discard this object. Active jobs and
        unexpired unused quotes block removal. Historical signed receipt metadata
        remains, but the removed file cannot be downloaded or used again.
        """
        return tools.release_compute_object(reference)

    def workflow_tools():
        if tools.workflows is None:
            raise PermissionError("Configure APERTURE_MCP_WORKFLOW_DIRECTORY for durable agent workflows.")
        return tools.workflows

    @server.tool(name="prepare_compute_workflow", title="Prepare a bounded batch or dependent workflow")
    def prepare_compute_workflow(steps: list[dict], max_cost_lamports: int) -> dict:
        """Validate a DAG and its total spending cap without starting computation.

        Steps contain id, source, inputs, parameters, optional depends_on, and
        max_cost_lamports/max_runtime_seconds. Inputs may reference an immutable
        object or use from_step and artifact to consume a preceding result.
        """
        return workflow_tools().prepare(steps, max_cost_lamports)

    @server.tool(name="get_assigned_workflows", title="Get console-approved agent work")
    def get_assigned_workflows() -> dict:
        """List owner-approved jobs for this agent without putting dataset bytes in chat.

        Owner signatures and plan/budget hashes are verified locally. Full plans
        stay in the agent host. Starting applies the existing local execution,
        cost, runtime and workflow ceilings; console approval cannot expand them.
        """
        workflow_tools()
        return {"workflows": [tools.inbox.summary(value) for value in tools.inbox.list()]}

    @server.tool(name="start_assigned_workflow", title="Run a console-approved workflow")
    def start_assigned_workflow(workflow_id: str) -> dict:
        """Start or recover this owner's approved plan on its original agent host.

        Progress, settled charges and results are visible in the console. The
        owner can stop the whole workflow there. No owner key is needed here.
        """
        workflow_tools()
        return tools.inbox.start(workflow_id)

    @server.tool(name="get_assigned_workflow_progress", title="Get this host's assigned workflow progress")
    def get_assigned_workflow_progress() -> dict:
        """Inspect the non-blocking assigned runner; execution must finish before claiming results."""
        workflow_tools()
        return tools.inbox.get()

    @server.tool(name="start_compute_workflow", title="Start or resume the prepared workflow")
    def start_compute_workflow(workflow_id: str) -> dict:
        """Run in the background. Return promptly; poll get_compute_workflow.

        Calling again resumes the same durable journal. No owner key, deposit
        or expanded passport is used. Uncertain admissions retain their quote.
        """
        return workflow_tools().start(workflow_id)

    @server.tool(name="get_compute_workflow", title="Inspect workflow progress and named results")
    def get_compute_workflow(workflow_id: str) -> dict:
        """Read progress. Completed results include reusable signed artifact refs."""
        return workflow_tools().get(workflow_id)

    @server.tool(name="cancel_compute_workflow", title="Stop admitting steps and cancel active work")
    def cancel_compute_workflow(workflow_id: str) -> dict:
        """Request a stop; poll afterward to confirm terminal execution state."""
        return workflow_tools().cancel(workflow_id)

    return server


def main() -> int:
    """Start the local stdio server for an MCP-compatible agent host."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = MCPSettings.from_env()
        agent_keypair = load_keypair(Path(settings.agent_keypair_path))
        client = ApertureClient(
            settings.gateway_url,
            owner=settings.owner_pubkey,
            agent_keypair=agent_keypair,
            program_id=settings.program_id,
            gateway_pubkey=settings.gateway_pubkey,
            network=settings.network,
            treasury=settings.treasury_pubkey,
            rpc_url=settings.rpc_url,
        )
        if client.agent == client.owner:
            raise ValueError(
                "The MCP server requires a dedicated agent key distinct from "
                "APERTURE_OWNER_PUBKEY; issue that key an owner-approved passport."
            )
        tools = ApertureAgentTools(
            client,
            max_cost_lamports=settings.max_cost_lamports,
            max_runtime_seconds=settings.max_runtime_seconds,
            max_rate_lamports=settings.max_rate_lamports,
            execution_enabled=settings.execution_enabled,
            max_pending_quotes=settings.max_pending_quotes,
            max_tracked_tasks=settings.max_tracked_tasks,
            workflow_directory=settings.workflow_directory,
            max_workflow_cost_lamports=settings.max_workflow_cost_lamports,
        )
        server = create_mcp_server(tools)
        server.run(transport="stdio")
    except (OSError, ValueError, RuntimeError) as error:
        logging.getLogger("aperture.mcp").error("MCP server could not start: %s", error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
