"""Exercise data workflows through a real local MCP stdio subprocess."""
import argparse
import asyncio
import base64
import csv
import hashlib
import io
import json
import secrets
from pathlib import Path
import sys
import time

from mcp import Client
from mcp.client.stdio import StdioServerParameters
import requests
from solders.keypair import Keypair

from soak_workflow import ROOT, available_port, pipeline, save_json, start_workspace, stop_demo_services
from aperture_client import ApertureClient
from aperture_client.client import canonical
from aperture_client.assigned_workflows import request as assigned_request


async def call(client, name, arguments=None):
    result = await client.call_tool(name, arguments or {})
    if result.is_error:
        raise RuntimeError("MCP call failed: " + name + " " + str(result.content)[:500])
    value = result.structured_content
    if not isinstance(value, dict):
        text = [item.text for item in result.content if item.type == "text"]
        if len(text) != 1:
            raise ValueError("MCP tool returned no single JSON object: " + name)
        value = json.loads(text[0])
        if not isinstance(value, dict):
            raise ValueError("MCP tool returned no JSON object: " + name)
    if set(value) == {"result"} and isinstance(value["result"], dict):
        value = value["result"]
    if value.get("status") == "error":
        raise RuntimeError("MCP tool reported an error: " + name + " " + str(value.get("error")))
    return value


def error_detail(error):
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(error_detail(item) for item in error.exceptions)
    return type(error).__name__ + ": " + str(error)


async def check(output, assigned=False):
    process, sdk = None, None
    summary = {"status": "running", "transport": "stdio", "settlement": "OFF_CHAIN"}
    try:
        process, configuration = start_workspace(output, available_port())
        owner, agent = Keypair(), Keypair()
        agent_path = output / "agent.keypair.json"
        save_json(agent_path, list(bytes(agent)))
        sdk = ApertureClient(configuration["gateway_url"], owner=str(owner.pubkey()), agent_keypair=agent,
            program_id=configuration["program_id"], gateway_pubkey=configuration["gateway_pubkey"], network="off_chain")
        sdk.passport(owner, name="Synthetic stdio agent", max_cost_lamports=100000,
                     max_runtime_seconds=60, total_budget_lamports=1000000)
        environment = {"PYTHONPATH": str(ROOT / "sdk" / "python"), "PYTHONIOENCODING": "utf-8",
            "APERTURE_GATEWAY_URL": configuration["gateway_url"], "APERTURE_OWNER_PUBKEY": str(owner.pubkey()),
            "APERTURE_AGENT_KEYPAIR": str(agent_path), "APERTURE_PROGRAM_ID": configuration["program_id"],
            "APERTURE_GATEWAY_PUBKEY": configuration["gateway_pubkey"], "APERTURE_NETWORK": "off_chain",
            "APERTURE_MCP_EXECUTION_ENABLED": "true", "APERTURE_MCP_MAX_COST_LAMPORTS": "100000",
            "APERTURE_MCP_MAX_RUNTIME_SECONDS": "60", "APERTURE_MCP_MAX_WORKFLOW_COST_LAMPORTS": "300000",
            "APERTURE_MCP_WORKFLOW_DIRECTORY": str(output / "workflows")}
        parameters = StdioServerParameters(command=sys.executable,
            args=["-X", "utf8", "-m", "aperture_client.mcp_server"], cwd=ROOT, env=environment)
        async with Client(parameters, read_timeout_seconds=30) as host:
            listed = await host.list_tools()
            expected_inbox = {"get_assigned_workflows", "start_assigned_workflow", "get_assigned_workflow_progress"}
            if len(listed.tools) != 19 or not expected_inbox <= {item.name for item in listed.tools}:
                raise ValueError("The stdio server did not advertise all 19 tools, including assigned workflows.")
            references = []
            for name, data in [("first.csv", b"category,amount\nalpha,1.25\nbeta,2.50\nalpha,missing\n"),
                               ("second.csv", b"category,amount\nalpha,3.75\nbeta,-0.50\n")]:
                references.append(await call(host, "upload_compute_input",
                    {"name": name, "content_base64": base64.b64encode(data).decode("ascii")}))
            plan = {"version": 1, "steps": pipeline.build_plan(references), "max_cost_lamports": 300000}
            if assigned:
                request_id = secrets.token_hex(16)
                fields = {"owner": sdk.owner, "agent_pubkey": sdk.agent, "issued_at": int(time.time()), "nonce": secrets.token_urlsafe(24)}
                message = "Aperture owner control v1\naudience:aperture-gateway\n" + canonical({"action": "submit-workflow", **fields,
                    "task_id": hashlib.sha256(canonical(plan).encode()).hexdigest(), "limit": plan["max_cost_lamports"], "cursor": request_id,
                    "program_id": sdk.program_id, "gateway_pubkey": sdk.gateway_pubkey, "network": sdk.network})
                prepared = sdk.request("POST", "/owners/workflows/submit", json={**fields, "plan": plan, "request_id": request_id,
                    "signature": list(bytes(owner.sign_message(message.encode())))}).json()
                inbox = await call(host, "get_assigned_workflows")
                if len(inbox["workflows"]) != 1 or any("plan" in flow or "source" in flow for flow in inbox["workflows"]):
                    raise ValueError("Assigned MCP inbox did not return compact verified metadata.")
            else:
                prepared = await call(host, "prepare_compute_workflow", {"steps": plan["steps"], "max_cost_lamports": 300000})
            identifier = prepared["workflow_id"]
            start_tool = "start_assigned_workflow" if assigned else "start_compute_workflow"
            progress_tool = "get_assigned_workflow_progress" if assigned else "get_compute_workflow"
            progress_arguments = {} if assigned else {"workflow_id": identifier}
            def assigned_state():
                return assigned_request(sdk, "/agents/workflows/read", "read-assigned-workflow", body={"workflow_id": identifier}, task_id=identifier)
            await call(host, start_tool, {"workflow_id": identifier})
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                snapshot = await call(host, progress_tool, progress_arguments)
                admitted = assigned_state()["tasks"].get("batch_0000") if assigned else snapshot.get("task_id")
                if admitted:
                    checkpoint = admitted
                    break
                if snapshot["status"] in {"completed", "failed", "attention", "stopped"}:
                    raise ValueError("The first MCP process did not reach the admission checkpoint.")
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("The first stdio task was not admitted.")
        # A new Client(parameters) launches a separate MCP server process.
        async with Client(parameters, read_timeout_seconds=30) as host:
            restored = next(flow for flow in (await call(host, "get_assigned_workflows"))["workflows"] if flow["workflow_id"] == identifier) if assigned else await call(host, progress_tool, progress_arguments)
            summary["status_before_resume"] = restored["status"]
            await call(host, start_tool, {"workflow_id": identifier})
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                snapshot = await call(host, progress_tool, progress_arguments)
                if snapshot["status"] == "completed":
                    break
                if snapshot["status"] in {"failed", "attention", "stopped"}:
                    raise RuntimeError("Restored MCP workflow did not finish: " + str(snapshot.get("detail")))
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("Restored stdio workflow did not finish.")
            if assigned:
                retained = assigned_state()
                snapshot["steps"] = [{"task_id": retained["tasks"][step["id"]]} for step in plan["steps"]]
                snapshot["final_task_id"] = retained["tasks"]["report"]
            if len(snapshot["steps"]) != 3 or snapshot["steps"][0]["task_id"] != checkpoint:
                raise ValueError("MCP restart did not preserve the admitted first task.")
            final_task = snapshot["final_task_id"]
            sdk_task = sdk.resume_task(final_task)
            sdk_result = sdk.wait(sdk_task, timeout_seconds=10)
            files = {}
            for name in ["report.json", "categories.csv", "quality.csv"]:
                returned = await call(host, "read_compute_artifact", {"task_id": final_task, "name": name})
                if not returned.get("content_available"):
                    raise ValueError("The stdio result file was not available.")
                data = base64.b64decode(returned["content_base64"], validate=True)
                if data != sdk.download_artifact(sdk_task, sdk_result["receipt"], name):
                    raise ValueError("MCP and SDK downloads returned different bytes.")
                if hashlib.sha256(data).hexdigest() != returned["artifact"]["sha256"]:
                    raise ValueError("The stdio result hash differs from its descriptor.")
                (output / name).write_bytes(data)
                files[name] = data
            report = json.loads(files["report.json"])
            if (report["valid_rows"], report["invalid_rows"], report["groups"]["alpha"]["total"],
                    report["groups"]["beta"]["total"]) != (4, 1, 5, 2):
                raise ValueError("The stdio JSON result differs from the independent expected values.")
            rows = list(csv.DictReader(io.StringIO(files["categories.csv"].decode())))
            if [(row["category"], float(row["average"])) for row in rows] != [("alpha", 2.5), ("beta", 1)]:
                raise ValueError("The stdio CSV averages differ from the expected values.")
            usage = await call(host, "get_compute_storage")
            for item in usage["objects"]:
                reference = {key: item[key] for key in ["object_id", "name", "sha256", "size_bytes"]}
                await call(host, "release_compute_object", {"reference": reference})
            usage = await call(host, "get_compute_storage")
            if usage["object_count"] or usage["size_bytes"]:
                raise ValueError("Synthetic stdio files were not fully released.")
            response = requests.get(configuration["gateway_url"] + "/stats", timeout=5)
            response.raise_for_status()
            if response.json()["tasks_finished"] != 3:
                raise ValueError("The restarted stdio workflow created duplicate tasks.")
            summary.update(status="completed", advertised_tools=19, workflow_steps=3, new_tasks=3,
                console_assigned_workflow=assigned,
                mcp_processes_started=2, first_admitted_task_reused=True,
                json_csv_match_expected=True, sdk_mcp_bytes_match=True, storage_bytes_after_release=0)
    except BaseException as error:
        summary.update(status="failed", detail=error_detail(error))
        raise
    finally:
        try:
            if process is not None:
                stop_demo_services([process])
        except Exception as error:
            summary.update(status="failed", cleanup_detail=str(error))
            raise
        finally:
            if sdk is not None:
                sdk.http.close()
            save_json(output / "summary.json", summary)
            print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assigned", action="store_true", help="Receive an owner-approved console workflow through the real MCP transport.")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "summary.json").exists():
        raise ValueError("Preserve the prior run and choose a new output directory.")
    asyncio.run(check(output, args.assigned))


if __name__ == "__main__":
    main()
