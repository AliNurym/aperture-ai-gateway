"""Run the real frontend's exported batch plan through the public Python CLI."""
import argparse
import csv
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import requests
from solders.keypair import Keypair

from soak_workflow import ROOT, available_port, save_json, start_workspace, stop_demo_services
from aperture_client import ApertureClient


def check(output):
    process, client = None, None
    summary = {"status": "running", "settlement": "OFF_CHAIN"}
    try:
        process, configuration = start_workspace(output, available_port())
        owner, agent = Keypair(), Keypair()
        agent_path = output / "agent.keypair.json"
        save_json(agent_path, list(bytes(agent)))
        client = ApertureClient(configuration["gateway_url"], owner=str(owner.pubkey()), agent_keypair=agent,
            program_id=configuration["program_id"], gateway_pubkey=configuration["gateway_pubkey"], network="off_chain")
        client.passport(owner, name="Synthetic exported plan agent", max_cost_lamports=100000,
                        max_runtime_seconds=60, total_budget_lamports=10000000)
        references, expected = [], {}
        for index in range(17):
            category = "alpha" if index % 2 == 0 else "beta"
            amount = Decimal(index - 8) / 4
            references.append(client.upload_input(
                f"category,amount\n{category},{amount}\n{category},missing\n".encode(), name=f"batch-{index}.csv"))
            group = expected.setdefault(category, {"rows": 0, "total": Decimal(0), "minimum": amount, "maximum": amount})
            group["rows"] += 1
            group["total"] += amount
            group["minimum"] = min(group["minimum"], amount)
            group["maximum"] = max(group["maximum"], amount)
        inputs, plan_path = output / "inputs.json", output / "aperture-workflow.json"
        save_json(inputs, references)
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js is required to build the actual frontend plan.")
        subprocess.run([node, "--input-type=module", "-e",
            "import {readFileSync,writeFileSync} from 'node:fs'; "
            "import {createBatchPlan} from './frontend/src/utils/workflowPlan.js'; "
            "const inputs=JSON.parse(readFileSync(process.argv[1],'utf8')); "
            "writeFileSync(process.argv[2],JSON.stringify(createBatchPlan(inputs,100000,60),null,2));",
            str(inputs), str(plan_path)], cwd=ROOT, check=True, timeout=30, capture_output=True)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if len(plan["steps"]) != 20 or plan["max_cost_lamports"] != 2000000:
            raise ValueError("The actual frontend did not produce the expected 17-batch hierarchical plan.")
        environment = {**os.environ, "APERTURE_GATEWAY_URL": configuration["gateway_url"],
            "APERTURE_OWNER_PUBKEY": str(owner.pubkey()), "APERTURE_AGENT_KEYPAIR": str(agent_path),
            "APERTURE_PROGRAM_ID": configuration["program_id"], "APERTURE_GATEWAY_PUBKEY": configuration["gateway_pubkey"],
            "APERTURE_NETWORK": "off_chain", "APERTURE_TREASURY_PUBKEY": "", "SOLANA_RPC_URL": ""}
        command = [sys.executable, "-X", "utf8", str(ROOT / "examples" / "run_workflow.py"),
            str(plan_path), "--workflow-budget-lamports", "2000000", "--journal", str(output / "workflow.sqlite3"),
            "--output", str(output / "results"), "--wait-seconds", "60"]

        def run(label, extra=()):
            completed = subprocess.run(command + list(extra), cwd=ROOT, env=environment,
                timeout=150, capture_output=True, text=True, encoding="utf-8")
            (output / (label + ".log")).write_text(completed.stdout + completed.stderr, encoding="utf-8")
            completed.check_returncode()
            return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]

        prepared = run("prepare", ["--prepare"])
        if prepared[-1]["status"] != "prepared" or client.list_agent_tasks()["tasks"]:
            raise ValueError("Local plan preparation submitted a job or did not finish.")
        initial = run("execute")
        replay = run("replay")
        if initial[-1]["status"] != "completed" or replay[-1]["status"] != "completed":
            raise ValueError("The exported CLI workflow or its replay did not complete.")
        verified = [event for event in replay if event.get("state") == "artifact_verified"]
        if len(verified) != 3 or any(item["status"] != "verified_existing" for item in verified):
            raise ValueError("Replaying the CLI did not verify all three existing final files.")
        status = run("status", ["--status"])[-1]
        if status["status"] != "completed" or status["completed_steps"] != 20:
            raise ValueError("The CLI journal status did not include all completed steps.")
        result_dir = output / "results" / "020-report"
        report = json.loads((result_dir / "report.json").read_text(encoding="utf-8"))
        groups = {name: {"rows": data["rows"], "total": data["total"], "minimum": data["minimum"], "maximum": data["maximum"]} for name, data in expected.items()}
        actual_groups = {name: {"rows": data["rows"], "total": Decimal(data["total_decimal"]),
            "minimum": Decimal(str(data["minimum"])), "maximum": Decimal(str(data["maximum"]))} for name, data in report["groups"].items()}
        if report["version"] != 2 or (report["valid_rows"], report["invalid_rows"]) != (17, 17) or actual_groups != groups:
            raise ValueError("The exported frontend JSON differs from the independent expected result.")
        if report["quality"]["invalid_reasons"] != {"invalid_amount": 17} or report["quality"]["missing_category_rows"] != 0:
            raise ValueError("The exported frontend quality accounting differs from the invalid input rows.")
        rows = list(csv.DictReader(io.StringIO((result_dir / "categories.csv").read_text(encoding="utf-8"))))
        if [(row["category"], int(row["rows"]), Decimal(row["total_decimal"]), Decimal(row["average"])) for row in rows] != [
                (name, item["rows"], item["total"], item["total"] / item["rows"]) for name, item in sorted(expected.items())]:
            raise ValueError("The exported frontend CSV differs from the independent expected result.")
        quality_rows = list(csv.DictReader(io.StringIO((result_dir / "quality.csv").read_text(encoding="utf-8"))))
        if quality_rows != [{"reason": "invalid_amount", "rows": "17"}]:
            raise ValueError("The exported quality CSV differs from the independent expected exclusions.")
        stats = requests.get(client.url + "/stats", timeout=5)
        stats.raise_for_status()
        if stats.json()["tasks_finished"] != 20:
            raise ValueError("The CLI workflow replay created duplicate tasks.")
        for item in client.storage_usage()["objects"]:
            client.release_object({key: item[key] for key in ["object_id", "name", "sha256", "size_bytes"]})
        usage = client.storage_usage()
        if usage["object_count"] or usage["size_bytes"]:
            raise ValueError("Synthetic exported-plan files were not fully released.")
        summary.update(status="completed", csv_batches=17, workflow_steps=20, new_tasks=20,
            frontend_plan_executed_by_cli=True, intermediate_merges=2, prepared_without_jobs=True,
            replay_verified_existing_files=True, independent_json_csv_match=True, storage_bytes_after_release=0)
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
