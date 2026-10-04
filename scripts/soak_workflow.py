"""Exercise local CSV workflows, journal replay and service restarts over time.

Uses synthetic data and the existing OFF_CHAIN preview. Results and service logs
are retained in a caller-selected directory. No external wallet is used.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time

import requests
from solders.keypair import Keypair

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk" / "python"))
from aperture_client import ApertureClient, WorkflowRunner
from demo_workflow import available_port, stop_demo_services

spec = importlib.util.spec_from_file_location("soak_batch_pipeline", ROOT / "examples" / "batch_data_workflow.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def start_workspace(output, port):
    manifest = output / "services" / "processes.json"
    previous_version = manifest.stat().st_mtime_ns if manifest.exists() else None
    with (output / "launcher.log").open("ab") as log:
        process = subprocess.Popen([
            sys.executable, "-X", "utf8", str(ROOT / "scripts" / "preview_workflows.py"),
            "--supervise", "--port", str(port),
            "--database", str(output / "tasks.sqlite3"),
            "--state-directory", str(output / "services"),
        ], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("The local preview stopped during startup; see launcher.log.")
            if manifest.exists() and manifest.stat().st_mtime_ns != previous_version:
                try:
                    configuration = json.loads(manifest.read_text(encoding="utf-8"))
                    response = requests.get(configuration["gateway_url"] + "/health", timeout=2)
                    response.raise_for_status()
                    health = response.json()
                    if health.get("status") == "ready" and health.get("demo_mode") is True:
                        return process, configuration
                except (requests.RequestException, ValueError):
                    pass
            time.sleep(0.2)
        raise TimeoutError("Local preview startup did not finish within 45 seconds.")
    except BaseException:
        stop_demo_services([process])
        raise


def check_cycle(client, directory, sequence):
    directory.mkdir()
    inputs = [client.upload_input(data, name=name) for name, data in [
        ("first.csv", b"category,amount\nalpha,1.25\nbeta,2.50\nalpha,missing\n"),
        ("second.csv", b"category,amount\nalpha,3.75\nbeta,-0.50\n"),
    ]]
    plan = pipeline.build_plan(inputs)
    runner = WorkflowRunner(client, directory / "workflow.sqlite3")
    baseline = requests.get(client.url + "/stats", timeout=5).json()["tasks_completed"]
    started = time.monotonic()
    result = runner.run(plan, max_cost_lamports=len(plan) * 100000, wait_seconds=90)
    first_ids = [step["task"]["task_id"] for step in result["steps"].values()]
    repeated = runner.run(plan, max_cost_lamports=len(plan) * 100000, wait_seconds=90)
    if [step["task"]["task_id"] for step in repeated["steps"].values()] != first_ids:
        raise ValueError("Replaying a completed workflow changed its task IDs.")
    completed = requests.get(client.url + "/stats", timeout=5).json()["tasks_completed"]
    if completed - baseline != len(plan):
        raise ValueError("The workflow or its replay created an unexpected number of tasks.")
    final = result["steps"]["report"]
    task = WorkflowRunner._task(final["task"])
    files = {}
    for artifact in final["result"]["receipt"]["artifacts"]:
        data = client.download_artifact(task, final["result"]["receipt"], artifact["name"])
        if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise ValueError("Downloaded report hash differs from its descriptor.")
        directory.joinpath(artifact["name"]).write_bytes(data)
        files[artifact["name"]] = data
    report = json.loads(files["report.json"])
    expected = {"alpha": {"rows": 2, "total": 5.0, "minimum": 1.25, "maximum": 3.75},
                "beta": {"rows": 2, "total": 2.0, "minimum": -0.5, "maximum": 2.5}}
    if report != {"valid_rows": 4, "invalid_rows": 1, "groups": expected}:
        raise ValueError("The category report differs from the independent expected result.")
    rows = list(csv.DictReader(io.StringIO(files["categories.csv"].decode())))
    if [(row["category"], float(row["total"]), float(row["average"])) for row in rows] != [
            ("alpha", 5.0, 2.5), ("beta", 2.0, 1.0)]:
        raise ValueError("The CSV report differs from the independent expected result.")
    references = inputs + [artifact for step in result["steps"].values()
                           for artifact in step["result"]["receipt"].get("artifacts", [])]
    for reference in references:
        client.release_object(reference)
    usage = client.storage_usage()
    if usage["object_count"] != 0 or usage["size_bytes"] != 0:
        raise ValueError("Completed synthetic files were not fully released.")
    return {"cycle": sequence, "finished_at": utc_now(), "task_ids": first_ids,
            "elapsed_seconds": round(time.monotonic() - started, 3), "new_tasks": len(plan),
            "accepted_rows": 4, "skipped_rows": 1, "storage_bytes_after_release": 0,
            "journal_replay_reused_tasks": True, "file_hashes_match": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    schedule = parser.add_mutually_exclusive_group()
    schedule.add_argument("--duration-seconds", type=int, default=300)
    schedule.add_argument("--until", help="UTC deadline in ISO 8601, including its timezone")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--restart-every", type=int, default=10)
    args = parser.parse_args()
    if args.until:
        until = datetime.fromisoformat(args.until.replace("Z", "+00:00"))
        if until.tzinfo is None:
            parser.error("--until requires an explicit timezone")
        duration = (until - datetime.now(timezone.utc)).total_seconds()
    else:
        duration = args.duration_seconds
    if not 1 <= duration <= 86400 or not 1 <= args.interval_seconds <= 600 or not 1 <= args.restart_every <= 1000:
        parser.error("Use a duration of 1–86400 seconds, interval of 1–600 seconds and restart cadence of 1–1000 cycles")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "summary.json").exists() or (output / "cycles.jsonl").exists():
        raise ValueError("Preserve the previous run and choose a new output directory.")
    started = time.monotonic()
    deadline = started + duration
    summary = {"status": "running", "started_at": utc_now(), "requested_seconds": round(duration, 3),
               "settlement": "OFF_CHAIN", "completed_cycles": 0, "service_restarts": 0, "new_tasks": 0}
    save_json(output / "summary.json", summary)
    process, client, failure = None, None, None
    port = available_port()
    owner, agent = Keypair(), Keypair()
    try:
        process, configuration = start_workspace(output, port)
        client = ApertureClient(configuration["gateway_url"], owner=str(owner.pubkey()), agent_keypair=agent,
            program_id=configuration["program_id"], gateway_pubkey=configuration["gateway_pubkey"], network="off_chain")
        client.passport(owner, name="Synthetic soak agent", max_cost_lamports=100000,
                        max_runtime_seconds=60, total_budget_lamports=100000000)
        while time.monotonic() < deadline:
            cycle = summary["completed_cycles"] + 1
            outcome = check_cycle(client, output / f"cycle-{cycle:04d}", cycle)
            with (output / "cycles.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(outcome) + "\n")
            summary.update(completed_cycles=cycle, new_tasks=summary["new_tasks"] + outcome["new_tasks"],
                           last_cycle=outcome, elapsed_seconds=round(time.monotonic() - started, 3))
            save_json(output / "summary.json", summary)
            print(json.dumps({"status": "running", **outcome}), flush=True)
            if cycle % args.restart_every == 0 and time.monotonic() < deadline:
                stop_demo_services([process])
                process = None
                process, resumed = start_workspace(output, port)
                if resumed["gateway_pubkey"] != configuration["gateway_pubkey"]:
                    raise ValueError("The local preview identity changed across its restart.")
                summary["service_restarts"] += 1
            next_cycle = min(deadline, time.monotonic() + args.interval_seconds)
            next_health_check = 0
            while time.monotonic() < next_cycle:
                if process.poll() is not None:
                    raise RuntimeError("The supervised preview exited between cycles.")
                if time.monotonic() >= next_health_check:
                    response = requests.get(configuration["gateway_url"] + "/health", timeout=3)
                    response.raise_for_status()
                    if response.json().get("status") != "ready":
                        raise RuntimeError("The local worker became unavailable between cycles.")
                    next_health_check = time.monotonic() + 10
                time.sleep(min(1, max(0, next_cycle - time.monotonic())))
        summary["status"] = "completed"
    except (Exception, KeyboardInterrupt) as error:
        summary.update(status="failed", detail=str(error) or type(error).__name__)
        failure = error
    finally:
        if process is not None:
            try:
                stop_demo_services([process])
            except Exception as error:
                summary.update(status="failed", cleanup_detail=str(error))
                failure = failure or error
        if client is not None:
            client.http.close()
        summary.update(finished_at=utc_now(), elapsed_seconds=round(time.monotonic() - started, 3))
        save_json(output / "summary.json", summary)
        print(json.dumps(summary, indent=2), flush=True)
    if failure is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
