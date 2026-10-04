"""Reproducible off-chain agent workflow with a disposable, reviewed local worker.

Uses synthetic data, ephemeral keys and no Solana payment. Docker isolation is
not claimed: only the two source templates in this example are approved.
"""
import argparse
import base64
import csv
import importlib.util
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk" / "python"))
from aperture_client import ApertureClient, WorkflowRunner
from aperture_client.client import canonical
from decimal import Decimal
from solders.keypair import Keypair
import requests

spec = importlib.util.spec_from_file_location("batch_pipeline", ROOT / "examples" / "batch_data_workflow.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def stop_demo_services(processes):
    """Stop every service before deleting its temporary databases and logs."""
    errors = []
    for process in reversed(processes):
        try:
            if process.poll() is None:
                if os.name == "nt":
                    # A Windows venv executable can be a redirector: terminating
                    # it alone leaves its Python child holding SQLite files open.
                    result = subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True, timeout=15,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if result.returncode and process.poll() is None:
                        raise RuntimeError(f"Could not stop demo service {process.pid}.")
                else:
                    process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        except Exception as error:
            errors.append(error)
    if errors:
        raise ExceptionGroup("Demo services did not stop cleanly.", errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--mcp-workflow", action="store_true",
                        help="Drive the background MCP workflow controller instead of the synchronous runner.")
    parser.add_argument("--owner-handoff", action="store_true", help="Upload as the owner, assign references, then compute as a different agent.")
    parser.add_argument("--regional-csv", action="store_true", help="Use custom columns, semicolons and comma decimal numbers.")
    parser.add_argument("--console-workflow", action="store_true", help="Approve in the console protocol and recover the dedicated agent receiver.")
    parser.add_argument("--compare-local", action="store_true", help="Run the identical templates and batches in direct Python and compare verified files and elapsed time.")
    args = parser.parse_args()
    if args.console_workflow and args.mcp_workflow:
        parser.error("Choose either the console receiver or the standalone MCP workflow controller.")
    if not 1 <= args.rows <= 500_000:
        raise ValueError("Demonstration rows must be between 1 and 500,000.")
    args.output.mkdir(parents=True, exist_ok=True)
    processes = []
    with tempfile.TemporaryDirectory(prefix="aperture-workflow-demo-") as temporary:
        state = Path(temporary)
        owner, agent, oracle = Keypair(), Keypair(), Keypair()
        port, worker_secret = available_port(), secrets.token_urlsafe(40)
        url = f"http://127.0.0.1:{port}"
        approved = state / "approved"
        approved.mkdir()
        (approved / "batch.py").write_text(pipeline.BATCH_SOURCE, encoding="utf-8", newline="")
        (approved / "merge.py").write_text(pipeline.MERGE_SOURCE, encoding="utf-8", newline="")
        env = {**os.environ, "APERTURE_ENV": "development", "APERTURE_DEMO_MODE": "true",
            "APERTURE_STATE_DB": str(state / "gateway.sqlite3"), "BACKEND_PRIVATE_KEY": json.dumps(list(bytes(oracle))),
            "APERTURE_WORKER_CREDENTIALS": "", "APERTURE_WORKER_TOKEN": worker_secret,
            "APERTURE_NODE_ID": "NODE-WORKFLOW-DEMO", "GATEWAY_API_URL": url,
            "APERTURE_WORKER_STATE_DIR": str(state / "worker"),
            "APERTURE_TRUSTED_SOURCE_DIRECTORY": str(approved), "APERTURE_ALLOW_UNSAFE_LOCAL_EXECUTION": "true"}
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with (state / "gateway.log").open("w", encoding="utf-8") as gateway_log, \
             (state / "worker.log").open("w", encoding="utf-8") as worker_log:
            try:
                processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app",
                    "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT / "backend", env=env,
                    stdout=gateway_log, stderr=subprocess.STDOUT, creationflags=creationflags))
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    try:
                        if requests.get(url + "/health", timeout=1).status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                    if processes[0].poll() is not None:
                        raise RuntimeError("Demo gateway stopped: " + (state / "gateway.log").read_text())
                    time.sleep(0.2)
                else:
                    raise TimeoutError("Demo gateway startup timed out.")
                processes.append(subprocess.Popen([sys.executable, "worker.py"], cwd=ROOT / "backend", env=env,
                    stdout=worker_log, stderr=subprocess.STDOUT, creationflags=creationflags))
                client = ApertureClient(url, owner=str(owner.pubkey()), agent_keypair=agent,
                    program_id="A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ",
                    gateway_pubkey=str(oracle.pubkey()), network="off_chain")
                client.passport(owner, name="Batch data agent", max_cost_lamports=100_000,
                    max_runtime_seconds=60, total_budget_lamports=10_000_000)
                mapping = {"category_column": "Department" if args.regional_csv else "category",
                    "amount_column": "Revenue" if args.regional_csv else "amount",
                    "delimiter": ";" if args.regional_csv else ",",
                    "decimal_separator": "," if args.regional_csv else "."}
                dataset = state / "records.csv"
                expected = {}
                with dataset.open("w", encoding="utf-8", newline="") as target:
                    writer = csv.DictWriter(target, fieldnames=[mapping["category_column"], mapping["amount_column"]], delimiter=mapping["delimiter"])
                    writer.writeheader()
                    for index in range(args.rows):
                        category = ["compute", "storage", "network", "support"][index % 4]
                        amount = "invalid" if index % 1000 == 0 else f"{(index % 971) / 100:.2f}"
                        if amount != "invalid":
                            expected[category] = expected.get(category, Decimal(0)) + Decimal(amount)
                        writer.writerow({mapping["category_column"]: category,
                            mapping["amount_column"]: amount.replace(".", ",") if args.regional_csv else amount})
                owner_client = ApertureClient(url, owner=str(owner.pubkey()), agent_keypair=owner,
                    program_id=client.program_id, gateway_pubkey=client.gateway_pubkey, network="off_chain") if args.owner_handoff else None
                pipeline_started = time.perf_counter()
                inputs, rows = pipeline.upload_csv_batches(owner_client or client, dataset,
                    delimiter=mapping["delimiter"], category_column=mapping["category_column"], amount_column=mapping["amount_column"])
                owner_inputs = list(inputs) if owner_client else []
                if owner_client:
                    inputs = client.assign_inputs(owner_inputs, owner_keypair=owner)
                    if client.assign_inputs(owner_inputs, owner_keypair=owner) != inputs:
                        raise ValueError("Retried owner handoff duplicated its retained references.")
                plan = pipeline.build_plan(inputs, csv_mapping=mapping)
                runner = WorkflowRunner(client, state / "workflow.sqlite3")
                interrupted = False

                def progress(event):
                    print(json.dumps(event), flush=True)

                if args.console_workflow:
                    from aperture_client.agent_tools import ApertureAgentTools
                    approved_plan = {"version": 1, "max_cost_lamports": len(plan) * 100000, "steps": plan}
                    request_id = secrets.token_hex(16)
                    fields = {"owner": client.owner, "agent_pubkey": client.agent,
                        "issued_at": int(time.time()), "nonce": secrets.token_urlsafe(24)}
                    message = "Aperture owner control v1\naudience:aperture-gateway\n" + canonical({
                        "action": "submit-workflow", **fields, "task_id": hashlib.sha256(canonical(approved_plan).encode()).hexdigest(),
                        "limit": approved_plan["max_cost_lamports"], "cursor": request_id,
                        "program_id": client.program_id, "gateway_pubkey": client.gateway_pubkey, "network": "off_chain"})
                    approved = client.request("POST", "/owners/workflows/submit", json={**fields, "request_id": request_id,
                        "plan": approved_plan, "signature": list(bytes(owner.sign_message(message.encode())))}).json()
                    tools = ApertureAgentTools(client, max_cost_lamports=100000, max_runtime_seconds=60,
                        execution_enabled=True, workflow_directory=state / "receiver", max_workflow_cost_lamports=10_000_000)
                    original_execute = ApertureClient.execute_job
                    def interrupted_admission(current_client, *arguments, **options):
                        nonlocal interrupted
                        admitted = original_execute(current_client, *arguments, **options)
                        if not interrupted:
                            interrupted = True
                            print("Assigned task accepted; interrupting before its local journal commit.", flush=True)
                            raise InterruptedError("Assigned workflow admission checkpoint")
                        return admitted
                    try:
                        ApertureClient.execute_job = interrupted_admission
                        tools.inbox.start(approved["workflow_id"])
                        deadline = time.monotonic() + 600
                        while tools.inbox.busy:
                            if time.monotonic() >= deadline:
                                raise TimeoutError("Assigned receiver interruption did not settle.")
                            time.sleep(0.1)
                        if not interrupted or tools.inbox.get()["status"] != "attention":
                            raise ValueError("Assigned admission interruption was not recoverable.")
                    finally:
                        ApertureClient.execute_job = original_execute
                    print("Recovering the same owner request and original receiver journal.", flush=True)
                    tools.inbox.start(approved["workflow_id"])
                    previous = None
                    while tools.inbox.busy:
                        current = tools.inbox.get()
                        if current != previous:
                            print(json.dumps(current), flush=True)
                            previous = current
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Assigned receiver did not complete.")
                        time.sleep(0.2)
                    final = tools.inbox.get()
                    if final["status"] != "completed":
                        raise ValueError("Assigned workflow did not complete: " + str(final))
                    result = {"workflow_id": approved["workflow_id"], "status": "completed",
                        "max_cost_lamports": approved_plan["max_cost_lamports"], "steps": {}}
                    from aperture_client.assigned_workflows import request as assigned_request
                    retained = assigned_request(client, "/agents/workflows/read", "read-assigned-workflow",
                        body={"workflow_id": approved["workflow_id"]}, task_id=approved["workflow_id"])
                    for step in plan:
                        task = client.resume_task(retained["tasks"][step["id"]])
                        result["steps"][step["id"]] = {"task": WorkflowRunner._task_data(task),
                            "result": client.wait(task, timeout_seconds=5, cancel_on_timeout=False)}
                elif args.mcp_workflow:
                    from aperture_client.agent_tools import ApertureAgentTools
                    tools = ApertureAgentTools(client, max_cost_lamports=100_000,
                        max_runtime_seconds=60, execution_enabled=True,
                        workflow_directory=state / "mcp-workflows",
                        max_workflow_cost_lamports=len(plan) * 100_000)
                    prepared = tools.workflows.prepare(plan, len(plan) * 100_000)
                    tools.workflows.start(prepared["workflow_id"])
                    workflow_deadline = time.monotonic() + 120
                    while time.monotonic() < workflow_deadline:
                        snapshot = tools.workflows.get(prepared["workflow_id"])
                        if snapshot["status"] == "completed":
                            break
                        if snapshot["status"] in {"attention", "stopped"}:
                            raise RuntimeError(snapshot.get("detail", snapshot["status"]))
                        time.sleep(0.2)
                    else:
                        raise TimeoutError("Background workflow demonstration timed out.")
                    # A fresh runner reads and verifies the completed journal without admission.
                    result = WorkflowRunner(client, state / "mcp-workflows" / (prepared["workflow_id"] + ".sqlite3")).run(
                        plan, max_cost_lamports=len(plan) * 100_000)
                    print(json.dumps(snapshot, indent=2), flush=True)
                else:
                    execute_job = client.execute_job
                    def interrupt_after_admission(*arguments, **options):
                        admitted = execute_job(*arguments, **options)
                        print("Gateway accepted " + admitted.task_id + "; interrupting before journal commit.", flush=True)
                        raise InterruptedError("Resume checkpoint reached.")
                    client.execute_job = interrupt_after_admission
                    try:
                        runner.run(plan, max_cost_lamports=len(plan) * 100_000, on_progress=progress)
                    except InterruptedError:
                        interrupted = True
                        print("Recovering the admission from signed history and the committed journal.", flush=True)
                    finally:
                        client.execute_job = execute_job
                    result = runner.run(plan, max_cost_lamports=len(plan) * 100_000,
                                        on_progress=lambda event: print(json.dumps(event), flush=True))
                report = result["steps"]["report"]
                task = WorkflowRunner._task(report["task"])
                for name in ("report.json", "categories.csv", "quality.csv"):
                    args.output.joinpath(name).write_bytes(client.download_artifact(task, report["result"]["receipt"], name))
                pipeline_seconds = time.perf_counter() - pipeline_started
                actual = json.loads(args.output.joinpath("report.json").read_text(encoding="utf-8"))
                if actual["valid_rows"] + actual["invalid_rows"] != args.rows or actual["invalid_rows"] != (args.rows + 999) // 1000:
                    raise ValueError("Report row counts differ from the generated input.")
                if {key: Decimal(value["total_decimal"]) for key, value in actual["groups"].items()} != expected:
                    raise ValueError("Report decimal totals differ from the generated input.")
                if owner_client:
                    issued_at, nonce = int(time.time()), secrets.token_urlsafe(24)
                    fields = {"owner": client.owner, "agent_pubkey": client.agent, "issued_at": issued_at, "nonce": nonce}
                    message = "Aperture owner control v1\naudience:aperture-gateway\n" + canonical({
                        "action": "observe-agent", **fields, "task_id": None, "limit": None, "cursor": None,
                        "program_id": client.program_id, "gateway_pubkey": client.gateway_pubkey, "network": "off_chain"})
                    view = client.request("POST", "/owners/agents/observe", json={**fields,
                        "signature": list(bytes(owner.sign_message(message.encode())))}).json()
                    headers = {"X-Aperture-Owner-View": view["view_token"]}
                    overview = client.request("GET", f"/owners/agents/{client.agent}/overview", headers=headers).json()
                    if task.task_id not in {item["task_id"] for item in overview["tasks"]}:
                        raise ValueError("Owner observation missed the delegated report task.")
                    for artifact in report["result"]["receipt"]["artifacts"]:
                        data = client.request("GET", f"/owners/agents/{client.agent}/tasks/{task.task_id}/artifacts/{artifact['object_id']}", headers=headers).content
                        if hashlib.sha256(data).hexdigest() != artifact["sha256"] or data != args.output.joinpath(artifact["name"]).read_bytes():
                            raise ValueError("Owner's result download differs from the verified agent file.")
                    for reference in owner_inputs:
                        owner_client.release_object(reference)
                    if owner_client.storage_usage()["object_count"]:
                        raise ValueError("Owner input storage was not released.")
                if args.mcp_workflow:
                    content = tools.read_compute_artifact(task.task_id, "report.json")
                    if base64.b64decode(content["content_base64"]) != args.output.joinpath("report.json").read_bytes():
                        raise ValueError("MCP artifact bytes differ from the verified SDK download.")
                storage_before = client.storage_usage()
                client.release_object(inputs[0])
                client.release_object(inputs[0])
                storage_after = client.storage_usage()
                summary = {"workflow_id": result["workflow_id"], "status": result["status"],
                    "input_rows": rows, "batch_count": len(inputs), "step_count": len(plan),
                    "resume_checkpoint": "admitted_before_task_journal_commit" if interrupted else None,
                    "background_mcp_controller": args.mcp_workflow, "execution_mode": "reviewed_trusted_local",
                    "settlement": "OFF_CHAIN", "new_tasks": requests.get(url + "/stats", timeout=5).json()["tasks_completed"],
                    "max_cost_lamports": result["max_cost_lamports"],
                    "artifacts": report["result"]["receipt"]["artifacts"]}
                summary["storage_released_bytes"] = storage_before["size_bytes"] - storage_after["size_bytes"]
                summary["mcp_artifact_read_verified"] = args.mcp_workflow
                summary["owner_handoff_verified"] = args.owner_handoff
                summary["regional_csv_verified"] = args.regional_csv
                summary["decimal_totals_verified"] = True
                summary["console_workflow_verified"] = args.console_workflow
                receipts = [item["result"]["receipt"] for item in result["steps"].values()]
                import math
                summary["measurement"] = {
                    "gateway_pipeline_seconds": round(pipeline_seconds, 6),
                    "timing_scope": "CSV batching/upload, handoff, approved execution, intentional admission interruption/recovery and three verified result downloads; excludes service startup and passport setup",
                    "worker_execution_seconds": round(sum(item["execution_time"] for item in receipts), 6),
                    "actual_charged_lamports": sum(item.get("charged_lamports") or 0 for item in receipts),
                    "equivalent_tariff_estimate_lamports": sum(min(item["max_cost_lamports"], math.ceil(item["execution_time"] * item["rate_lamports"])) for item in receipts),
                    "estimate_basis": "Sum of capped worker elapsed-time × quoted tariff, rounded up per task; not a Solana payment or USD cost",
                    "input_batch_bytes": sum(item["size_bytes"] for item in inputs),
                    "compact_reference_bytes": len(canonical(inputs).encode()),
                    "context_scope": "Descriptor bytes only, not measured LLM context or token savings; receiver lists summaries and keeps source/data on its host",
                    "budget_approvals": 1 if args.console_workflow else None,
                    "budget_approval_scope": "Workflow budget approval only; upload, assignment, passport and observation authorizations are separate",
                    "tasks_after_admission_recovery": summary["new_tasks"],
                }
                if args.compare_local:
                    from benchmark_csv_profile import LocalInputs, run_local_plan
                    local = LocalInputs()
                    baseline_inputs, _ = pipeline.upload_csv_batches(local, dataset,
                        delimiter=mapping["delimiter"], category_column=mapping["category_column"], amount_column=mapping["amount_column"])
                    blobs = {}
                    for uploaded, baseline in zip(inputs, baseline_inputs, strict=True):
                        if any(uploaded[field] != baseline[field] for field in ("name", "sha256", "size_bytes")):
                            raise ValueError("Direct Python baseline used different CSV batches.")
                        blobs[uploaded["object_id"]] = local.blobs[baseline["object_id"]]
                    direct, files = run_local_plan(plan, blobs, state / "direct-python")
                    if any(data != args.output.joinpath(name).read_bytes() for name, data in files.items()):
                        raise ValueError("Direct Python and gateway reports differ.")
                    summary["measurement"]["direct_python"] = direct
                    summary["measurement"]["identical_result_bytes"] = True
                    summary["measurement"]["comparison_limit"] = "Same host, input bytes and sources. Direct path excludes uploads, authorization, durable journal, gateway, receipts and recovery; gateway timing includes an intentional fault. No cloud/GPU/market-price or speed superiority claim."
                if summary["new_tasks"] != len(plan):
                    raise ValueError("Recovery admitted more tasks than the approved plan.")
                if owner_client:
                    owner_client.http.close()
                args.output.joinpath("run-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
                print(json.dumps(summary, indent=2), flush=True)
            except Exception:
                print("Gateway diagnostic:\n" + (state / "gateway.log").read_text(encoding="utf-8")[-2500:])
                print("Worker diagnostic:\n" + (state / "worker.log").read_text(encoding="utf-8")[-2500:])
                raise
            finally:
                stop_demo_services(processes)


if __name__ == "__main__":
    main()
