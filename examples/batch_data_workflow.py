"""Agent pipeline: CSV batches -> category summaries -> a merged JSON/CSV report.

The caller selects the dataset and the configured delegated agent. No owner key,
deposit or passport expansion is performed by this pipeline.
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path

from aperture_client import ApertureClient, WorkflowRunner, load_keypair

BATCH_SOURCE = '''from aperture import read_csv, parameters, write_json
import math
cfg = parameters()
groups = {}
valid = 0
invalid = 0
for row in read_csv(cfg["input_name"]):
    category = row.get("category", "").strip() or "uncategorized"
    try:
        amount = float(row["amount"])
    except (ValueError, KeyError):
        invalid += 1
        continue
    if not math.isfinite(amount) or len(category) > 200:
        invalid += 1
        continue
    if category not in groups:
        if len(groups) >= 10000:
            raise ValueError("Too many categories for one bounded batch")
        groups[category] = {"rows": 0, "total": 0, "minimum": amount, "maximum": amount}
    group = groups[category]
    group["rows"] += 1
    group["total"] += amount
    group["minimum"] = min(group["minimum"], amount)
    group["maximum"] = max(group["maximum"], amount)
    valid += 1
write_json(cfg["output_name"], {"valid_rows": valid, "invalid_rows": invalid, "groups": groups})
print("Processed", valid + invalid, "records;", invalid, "invalid records")
'''

MERGE_SOURCE = '''from aperture import read_json, parameters, write_json, write_csv
cfg = parameters()
groups = {}
valid = 0
invalid = 0
for name in cfg["input_names"]:
    report = read_json(name)
    valid += report["valid_rows"]
    invalid += report["invalid_rows"]
    for category, data in report["groups"].items():
        if category not in groups:
            if len(groups) >= 10000:
                raise ValueError("Merged report exceeds its category bound")
            groups[category] = {"rows": 0, "total": 0, "minimum": data["minimum"], "maximum": data["maximum"]}
        group = groups[category]
        group["rows"] += data["rows"]
        group["total"] += data["total"]
        group["minimum"] = min(group["minimum"], data["minimum"])
        group["maximum"] = max(group["maximum"], data["maximum"])
write_json(cfg["output_name"], {"valid_rows": valid, "invalid_rows": invalid, "groups": groups})
if cfg["final"]:
    rows = [{"category": key, "rows": data["rows"], "total": round(data["total"], 4),
             "average": round(data["total"] / data["rows"], 4),
             "minimum": data["minimum"], "maximum": data["maximum"]}
            for key, data in sorted(groups.items())]
    write_csv("categories.csv", rows, ["category", "rows", "total", "average", "minimum", "maximum"])
print("Combined", valid + invalid, "records across", len(groups), "categories")
'''


def upload_csv_batches(client, dataset, *, batch_rows=5000, uploaded=(), on_upload=None):
    if type(batch_rows) is not int or not 1 <= batch_rows <= 100_000:
        raise ValueError("batch_rows must be between 1 and 100,000.")
    references, total_rows = [], 0
    def stage(buffer):
        index = len(references)
        if index >= 200:
            raise ValueError("Dataset requires more than 200 batches; increase batch_rows.")
        data, name = buffer.getvalue().encode(), f"data-{index:04d}.csv"
        if index < len(uploaded):
            item = uploaded[index]
            if (item["name"] != name or item["size_bytes"] != len(data)
                    or item["sha256"] != hashlib.sha256(data).hexdigest()):
                raise ValueError("A retained batch differs from the selected dataset; use a new journal.")
        else:
            item = client.upload_input(data, name=name)
        references.append(item)
        if on_upload:
            on_upload(list(references))
    with Path(dataset).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not {"category", "amount"} <= set(reader.fieldnames):
            raise ValueError("Dataset requires category and amount CSV columns.")
        buffer, writer, count = None, None, 0
        for row in reader:
            if count == 0:
                buffer = io.StringIO(newline="")
                writer = csv.DictWriter(buffer, fieldnames=reader.fieldnames)
                writer.writeheader()
            writer.writerow(row)
            count += 1
            total_rows += 1
            if buffer.tell() > 32 * 1024 * 1024:
                raise ValueError("A CSV batch is too large; reduce batch_rows.")
            if count == batch_rows:
                stage(buffer)
                count = 0
        if count:
            stage(buffer)
    if not references:
        raise ValueError("Dataset contains no records.")
    if len(uploaded) > len(references):
        raise ValueError("Retained batches exceed the selected dataset; use a new journal.")
    return references, total_rows


def build_plan(inputs, *, step_cost=100_000, runtime=60):
    steps, references = [], []
    for index, item in enumerate(inputs):
        identifier, output = f"batch_{index:04d}", f"batch-{index:04d}.json"
        steps.append({"id": identifier, "source": BATCH_SOURCE, "inputs": [item],
            "parameters": {"input_name": item["name"], "output_name": output},
            "max_cost_lamports": step_cost, "max_runtime_seconds": runtime})
        references.append({"from_step": identifier, "artifact": output})
    level = 0
    while len(references) > 16:
        next_level = []
        for offset in range(0, len(references), 16):
            identifier, output = f"merge_{level}_{offset // 16}", f"merge-{level}-{offset // 16}.json"
            group = references[offset:offset + 16]
            steps.append({"id": identifier, "source": MERGE_SOURCE, "inputs": group,
                "parameters": {"input_names": [item["artifact"] for item in group],
                               "output_name": output, "final": False},
                "max_cost_lamports": step_cost, "max_runtime_seconds": runtime})
            next_level.append({"from_step": identifier, "artifact": output})
        references, level = next_level, level + 1
    steps.append({"id": "report", "source": MERGE_SOURCE, "inputs": references,
        "parameters": {"input_names": [item["artifact"] for item in references],
                       "output_name": "report.json", "final": True},
        "max_cost_lamports": step_cost, "max_runtime_seconds": runtime})
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--batch-rows", type=int, default=5000)
    parser.add_argument("--journal", type=Path, default=Path(".aperture-runs/batch-workflow.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path(".aperture-runs/results"))
    parser.add_argument("--workflow-budget-lamports", type=int, required=True)
    args = parser.parse_args()
    client = ApertureClient(os.environ["APERTURE_GATEWAY_URL"],
        owner=os.environ["APERTURE_OWNER_PUBKEY"],
        agent_keypair=load_keypair(os.environ["APERTURE_AGENT_KEYPAIR"]),
        program_id=os.environ["APERTURE_PROGRAM_ID"], gateway_pubkey=os.environ["APERTURE_GATEWAY_PUBKEY"],
        network=os.getenv("APERTURE_NETWORK", "devnet"), treasury=os.getenv("APERTURE_TREASURY_PUBKEY"))
    # Keep the upload plan so rerunning the command does not stage duplicate inputs.
    input_plan = args.journal.with_suffix(".inputs.json")
    args.journal.parent.mkdir(parents=True, exist_ok=True)
    def dataset_digest():
        digest = hashlib.sha256()
        with args.dataset.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    context = {"dataset_sha256": dataset_digest(), "batch_rows": args.batch_rows,
        "owner": client.owner, "agent": client.agent, "gateway_url": client.url,
        "gateway_pubkey": client.gateway_pubkey, "program_id": client.program_id,
        "network": client.network}
    retained = json.loads(input_plan.read_text(encoding="utf-8")) if input_plan.exists() else {}
    if retained and retained.get("context") != context:
        raise ValueError("Dataset, batch size or execution identity changed; select a new journal.")
    def save_inputs(inputs, rows=None):
        temporary = input_plan.with_suffix(".tmp")
        temporary.write_text(json.dumps({"context": context, "inputs": inputs, "rows": rows}), encoding="utf-8")
        temporary.replace(input_plan)
    inputs, rows = upload_csv_batches(client, args.dataset, batch_rows=args.batch_rows,
        uploaded=retained.get("inputs", []), on_upload=save_inputs)
    if dataset_digest() != context["dataset_sha256"]:
        raise ValueError("Dataset changed while staging; select a new journal for the changed data.")
    save_inputs(inputs, rows)
    plan = build_plan(inputs)
    result = WorkflowRunner(client, args.journal).run(plan,
        max_cost_lamports=args.workflow_budget_lamports,
        on_progress=lambda event: print(json.dumps(event), flush=True))
    report = result["steps"]["report"]
    task = WorkflowRunner._task(report["task"])
    args.output.mkdir(parents=True, exist_ok=True)
    for name in ("report.json", "categories.csv"):
        args.output.joinpath(name).write_bytes(client.download_artifact(task, report["result"]["receipt"], name))
    print(f"Workflow complete: {len(plan)} verified jobs; results in {args.output}")


if __name__ == "__main__":
    main()
