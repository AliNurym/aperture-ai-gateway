"""Resume a partially completed local workflow after restarting gateway and worker."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

import requests
from solders.keypair import Keypair

from soak_workflow import available_port, pipeline, save_json, start_workspace, stop_demo_services
from aperture_client import ApertureClient, WorkflowRunner


def finished_tasks(client):
    response = requests.get(client.url + "/stats", timeout=5)
    response.raise_for_status()
    return response.json()["tasks_finished"]


def check(output):
    process, client = None, None
    summary = {"status": "running", "settlement": "OFF_CHAIN"}
    try:
        port = available_port()
        process, configuration = start_workspace(output, port)
        owner, agent = Keypair(), Keypair()
        client = ApertureClient(configuration["gateway_url"], owner=str(owner.pubkey()), agent_keypair=agent,
            program_id=configuration["program_id"], gateway_pubkey=configuration["gateway_pubkey"], network="off_chain")
        client.passport(owner, name="Synthetic restart agent", max_cost_lamports=100000,
                        max_runtime_seconds=60, total_budget_lamports=1000000)
        reference = client.upload_input(b"category,amount\nalpha,1.25\nalpha,3.75\nbeta,missing\n", name="input.csv")
        plan = pipeline.build_plan([reference])
        journal = output / "workflow.sqlite3"
        runner = WorkflowRunner(client, journal)
        checkpoint = []

        def interrupt(event):
            if event["state"] == "completed":
                checkpoint.append(event["task_id"])
                raise InterruptedError("Intentional restart after the first completed step.")

        try:
            runner.run(plan, max_cost_lamports=200000, wait_seconds=60, on_progress=interrupt)
        except InterruptedError:
            if len(checkpoint) != 1:
                raise
        else:
            raise ValueError("The partial workflow did not stop at its completed step.")
        if finished_tasks(client) != 1:
            raise ValueError("A downstream task was admitted before the restart checkpoint.")
        with sqlite3.connect(journal) as database:
            records = database.execute("SELECT state,data FROM steps").fetchall()
        if len(records) != 1 or records[0][0] != "completed":
            raise ValueError("The partial workflow did not persist its completed first step.")
        original = json.loads(records[0][1])
        first_task = WorkflowRunner._task(original["task"])
        artifact = original["result"]["receipt"]["artifacts"][0]
        original_bytes = client.download_artifact(first_task, original["result"]["receipt"], artifact["name"])

        stop_demo_services([process])
        process = None
        process, resumed = start_workspace(output, port)
        if resumed["gateway_pubkey"] != configuration["gateway_pubkey"]:
            raise ValueError("Workspace identity changed across restart.")
        restored = client.resume_task(checkpoint[0])
        restored_result = client.wait(restored, timeout_seconds=10)
        if client.download_artifact(restored, restored_result["receipt"], artifact["name"]) != original_bytes:
            raise ValueError("The completed intermediate file changed after restart.")
        result = runner.run(plan, max_cost_lamports=200000, wait_seconds=60)
        if result["steps"][plan[0]["id"]]["task"]["task_id"] != checkpoint[0] or finished_tasks(client) != 2:
            raise ValueError("Resuming the dependent step duplicated the completed first task.")
        final = result["steps"]["report"]
        final_task = WorkflowRunner._task(final["task"])
        files = {}
        for item in final["result"]["receipt"]["artifacts"]:
            data = client.download_artifact(final_task, final["result"]["receipt"], item["name"])
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("The final artifact hash differs from its descriptor.")
            files[item["name"]] = data
            (output / item["name"]).write_bytes(data)
        report = json.loads(files["report.json"])
        group = report.get("groups", {}).get("alpha", {})
        if (report.get("valid_rows") != 2
                or report.get("invalid_rows") != 1
                or group.get("rows") != 2
                or group.get("total") != 5.0
                or group.get("minimum") != 1.25
                or group.get("maximum") != 3.75):
            raise ValueError("The resumed report differs from the independent expected result.")

        stop_demo_services([process])
        process = None
        process, resumed = start_workspace(output, port)
        if resumed["gateway_pubkey"] != configuration["gateway_pubkey"]:
            raise ValueError("Workspace identity changed across its second restart.")
        replayed = runner.run(plan, max_cost_lamports=200000, wait_seconds=60)
        if replayed != result or finished_tasks(client) != 2:
            raise ValueError("Replaying the completed journal changed its result or created a task.")
        restored = client.resume_task(final_task.task_id)
        restored_result = client.wait(restored, timeout_seconds=10)
        for name, data in files.items():
            if client.download_artifact(restored, restored_result["receipt"], name) != data:
                raise ValueError("A final artifact changed after the second restart.")
        for item in client.storage_usage()["objects"]:
            client.release_object({key: item[key] for key in ["object_id", "name", "sha256", "size_bytes"]})
        usage = client.storage_usage()
        if usage["object_count"] or usage["size_bytes"]:
            raise ValueError("Synthetic restart files were not fully released.")
        summary.update(status="completed", service_restarts=2, workflow_steps=2, new_tasks=2,
            first_completed_task_reused=True, intermediate_bytes_preserved=True,
            final_bytes_preserved=True, completed_journal_reused=True, storage_bytes_after_release=0)
    except BaseException as error:
        summary.update(status="failed", detail=type(error).__name__ + ": " + str(error))
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "summary.json").exists():
        raise ValueError("Preserve the prior run and choose a new output directory.")
    check(output)


if __name__ == "__main__":
    main()
