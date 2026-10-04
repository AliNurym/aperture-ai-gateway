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

_SOURCES = json.loads((Path(__file__).resolve().parents[1] / "backend" / "workloads" / "csv_sources.json").read_text(encoding="utf-8"))
BATCH_SOURCE = _SOURCES["batch"]
MERGE_SOURCE = _SOURCES["merge"]


def upload_csv_batches(client, dataset, *, batch_rows=5000, uploaded=(), on_upload=None,
                       delimiter=",", category_column="category", amount_column="amount"):
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
        reader = csv.DictReader(source, delimiter=delimiter, strict=True)
        if not reader.fieldnames or not {category_column, amount_column} <= set(reader.fieldnames):
            raise ValueError("Selected grouping and amount columns are missing from the dataset.")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("Dataset CSV columns must have unique names.")
        buffer, writer, count = None, None, 0
        for row in reader:
            if None in row:
                raise ValueError(f"Dataset CSV line {reader.line_num} has more fields than its header.")
            if count == 0:
                buffer = io.StringIO(newline="")
                writer = csv.DictWriter(buffer, fieldnames=reader.fieldnames, delimiter=delimiter)
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


def build_plan(inputs, *, step_cost=100_000, runtime=60, csv_mapping=None):
    steps, references = [], []
    for index, item in enumerate(inputs):
        identifier, output = f"batch_{index:04d}", f"batch-{index:04d}.json"
        steps.append({"id": identifier, "source": BATCH_SOURCE, "inputs": [item],
            "parameters": {**(csv_mapping or {}), "input_name": item["name"], "output_name": output, "csv_output": False},
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
    parser.add_argument("--category-column", default="category")
    parser.add_argument("--amount-column", default="amount")
    parser.add_argument("--delimiter", choices=[",", ";", "\t", "|"], default=",")
    parser.add_argument("--decimal-separator", choices=[".", ","], default=".")
    parser.add_argument("--thousands-separator", choices=["", ".", ",", " "], default="")
    parser.add_argument("--missing-category", choices=["uncategorized", "reject"], default="uncategorized")
    parser.add_argument("--journal", type=Path, default=Path(".aperture-runs/batch-workflow.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path(".aperture-runs/results"))
    parser.add_argument("--workflow-budget-lamports", type=int, required=True)
    args = parser.parse_args()
    mapping = {"category_column": args.category_column, "amount_column": args.amount_column,
        "delimiter": args.delimiter, "decimal_separator": args.decimal_separator,
        "thousands_separator": args.thousands_separator, "missing_category": args.missing_category}
    if (not args.category_column or not args.amount_column or args.category_column == args.amount_column
            or args.decimal_separator == args.thousands_separator):
        parser.error("Choose distinct columns and numeric separators.")
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
    context = {"dataset_sha256": dataset_digest(), "batch_rows": args.batch_rows, "csv_mapping": mapping,
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
        uploaded=retained.get("inputs", []), on_upload=save_inputs, delimiter=args.delimiter,
        category_column=args.category_column, amount_column=args.amount_column)
    if dataset_digest() != context["dataset_sha256"]:
        raise ValueError("Dataset changed while staging; select a new journal for the changed data.")
    save_inputs(inputs, rows)
    plan = build_plan(inputs, csv_mapping=mapping)
    result = WorkflowRunner(client, args.journal).run(plan,
        max_cost_lamports=args.workflow_budget_lamports,
        on_progress=lambda event: print(json.dumps(event), flush=True))
    report = result["steps"]["report"]
    task = WorkflowRunner._task(report["task"])
    args.output.mkdir(parents=True, exist_ok=True)
    for name in ("report.json", "categories.csv", "quality.csv"):
        args.output.joinpath(name).write_bytes(client.download_artifact(task, report["result"]["receipt"], name))
    print(f"Workflow complete: {len(plan)} verified jobs; results in {args.output}")


if __name__ == "__main__":
    main()
