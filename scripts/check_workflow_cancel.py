"""Check SDK and background-controller cancellation on local synthetic jobs."""
import argparse
import json
from pathlib import Path
import sqlite3
import threading
import time

import requests
from solders.keypair import Keypair

from soak_workflow import ROOT, available_port, pipeline, save_json, start_workspace, stop_demo_services
from aperture_client import ApertureClient, WorkflowRunner
from aperture_client.agent_tools import ApertureAgentTools


def finished_tasks(client):
    response = requests.get(client.url + "/stats", timeout=5)
    response.raise_for_status()
    return response.json()["tasks_finished"]


def check_sdk(client, output):
    reference = client.upload_input(b"category,amount\nalpha,2.5\n", name="sdk.csv")
    plan = pipeline.build_plan([reference])
    stop = threading.Event()
    journal = output / "sdk-workflow.sqlite3"
    baseline = finished_tasks(client)
    accepted = []

    def progress(event):
        if event["state"] == "admitted":
            accepted.append(event["task_id"])
            stop.set()

    try:
        WorkflowRunner(client, journal).run(plan, max_cost_lamports=200000,
            should_stop=stop.is_set, on_progress=progress, wait_seconds=30)
    except RuntimeError as error:
        if "downstream steps were withheld" not in str(error):
            raise
    else:
        raise ValueError("A stopped SDK chain reported successful completion.")
    with sqlite3.connect(journal) as database:
        records = database.execute("SELECT id,state,data FROM steps").fetchall()
    if len(accepted) != 1 or len(records) != 1 or records[0][1] != "failed":
        raise ValueError("The SDK chain continued into another step after its stop request.")
    receipt = json.loads(records[0][2])["result"]["receipt"]
    if receipt["execution_status"] != "cancelled" or finished_tasks(client) - baseline != 1:
        raise ValueError("The SDK stop request did not produce one cancelled task.")
    recovered = client.resume_task(accepted[0])
    result = client.wait(recovered, timeout_seconds=10)
    if result["receipt"]["execution_status"] != "cancelled" or finished_tasks(client) - baseline != 1:
        raise ValueError("Recovering the cancelled task changed its outcome or admitted another task.")
    client.release_object(reference)
    return {"scenario": "sdk_after_admission", "status": "passed", "accepted_tasks": 1,
            "receipt_outcome": "cancelled", "downstream_tasks": 0, "recovered_without_new_task": True}


def check_background(client, output):
    reference = client.upload_input(b"category,amount\nbeta,4\n", name="background.csv")
    plan = pipeline.build_plan([reference])
    tools = ApertureAgentTools(client, max_cost_lamports=100000, max_runtime_seconds=60,
        execution_enabled=True, workflow_directory=output / "mcp-workflows", max_workflow_cost_lamports=200000)
    identifier = tools.workflows.prepare(plan, 200000)["workflow_id"]
    baseline = finished_tasks(client)
    tools.workflows.start(identifier)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        snapshot = tools.workflows.get(identifier)
        if snapshot.get("task_id"):
            break
        if snapshot["status"] in {"completed", "failed", "stopped", "attention"}:
            raise ValueError("The background chain stopped before the admission checkpoint.")
        time.sleep(0.02)
    else:
        raise TimeoutError("The background task was not admitted.")
    requested = tools.workflows.cancel(identifier)
    while time.monotonic() < deadline:
        snapshot = tools.workflows.get(identifier)
        if snapshot["status"] == "stopped" and not snapshot["cancellation_pending"]:
            break
        time.sleep(0.05)
    else:
        raise TimeoutError("The background cancellation did not reach a terminal state.")
    if finished_tasks(client) - baseline != 1:
        raise ValueError("The background chain admitted a downstream task after cancellation.")
    recovered = client.resume_task(snapshot["task_id"])
    result = client.wait(recovered, timeout_seconds=10)
    if result["receipt"]["execution_status"] != "cancelled":
        raise ValueError("The background stop request did not cancel its admitted task.")
    thread = tools.workflows.active.get(identifier)
    if thread is not None:
        thread.join(timeout=5)
        if thread.is_alive():
            raise TimeoutError("The background controller did not finish after cancellation.")
    client.release_object(reference)
    return {"scenario": "background_after_admission", "status": "passed", "accepted_tasks": 1,
            "receipt_outcome": "cancelled", "downstream_tasks": 0,
            "cancellation_pending": False, "request_status": requested["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "summary.json").exists():
        raise ValueError("Preserve the prior result and choose another output directory.")
    process, client = None, None
    summary = {"status": "running", "settlement": "OFF_CHAIN", "scenarios": []}
    try:
        process, configuration = start_workspace(output, available_port())
        owner, agent = Keypair(), Keypair()
        client = ApertureClient(configuration["gateway_url"], owner=str(owner.pubkey()), agent_keypair=agent,
            program_id=configuration["program_id"], gateway_pubkey=configuration["gateway_pubkey"], network="off_chain")
        client.passport(owner, name="Synthetic cancellation agent", max_cost_lamports=100000,
                        max_runtime_seconds=60, total_budget_lamports=1000000)
        for check in (check_sdk, check_background):
            summary["scenarios"].append(check(client, output))
            save_json(output / "summary.json", summary)
        usage = client.storage_usage()
        if usage["object_count"] != 0:
            raise ValueError("Cancelled synthetic inputs were not released.")
        summary.update(status="completed", storage_bytes_after_release=usage["size_bytes"])
    except BaseException as error:
        summary.update(status="failed", detail=str(error))
        raise
    finally:
        try:
            if process is not None:
                stop_demo_services([process])
        except Exception as error:
            summary.update(status="failed", cleanup_detail=str(error))
            raise
        finally:
            if client is not None:
                client.http.close()
            save_json(output / "summary.json", summary)
            print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
