"""Reproducible off-chain agent workflow with a disposable, reviewed local worker.

Uses synthetic data, ephemeral keys and no Solana payment. Docker isolation is
not claimed: only the two source templates in this example are approved.
"""
import argparse
import base64
import csv
import importlib.util
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
from solders.keypair import Keypair
import requests

spec = importlib.util.spec_from_file_location("batch_pipeline", ROOT / "examples" / "batch_data_workflow.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--mcp-workflow", action="store_true",
                        help="Drive the background MCP workflow controller instead of the synchronous runner.")
    args = parser.parse_args()
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
                dataset = state / "records.csv"
                with dataset.open("w", encoding="utf-8", newline="") as target:
                    writer = csv.DictWriter(target, fieldnames=["category", "amount"])
                    writer.writeheader()
                    for index in range(args.rows):
                        writer.writerow({"category": ["compute", "storage", "network", "support"][index % 4],
                                         "amount": "invalid" if index % 1000 == 0 else f"{(index % 971) / 100:.2f}"})
                inputs, rows = pipeline.upload_csv_batches(client, dataset)
                plan = pipeline.build_plan(inputs)
                runner = WorkflowRunner(client, state / "workflow.sqlite3")
                interrupted = False

                def progress(event):
                    print(json.dumps(event), flush=True)

                if args.mcp_workflow:
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
                for name in ("report.json", "categories.csv"):
                    args.output.joinpath(name).write_bytes(client.download_artifact(task, report["result"]["receipt"], name))
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
                args.output.joinpath("run-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
                print(json.dumps(summary, indent=2), flush=True)
            except Exception:
                print("Gateway diagnostic:\n" + (state / "gateway.log").read_text(encoding="utf-8")[-2500:])
                print("Worker diagnostic:\n" + (state / "worker.log").read_text(encoding="utf-8")[-2500:])
                raise
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=15)


if __name__ == "__main__":
    main()
