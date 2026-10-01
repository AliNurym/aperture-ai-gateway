"""Run, inspect or prepare an exported Aperture workflow without exposing task tokens.

The operator selects a plan, an explicit budget and an existing delegated key.
This command never issues a passport, deposits funds or starts a local worker.
"""
import argparse
import hashlib
import json
import os
import signal
import sqlite3
import stat
import sys
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk" / "python"))
from aperture_client import ApertureClient, Task, WorkflowRunner, load_keypair, validate_workflow
from aperture_client.client import canonical, sha256, verify_recovered_quote
from aperture_client.jobs import NAME
from aperture_client.retries import retry_throttled
from aperture_client.workflows import STEP_ID

MAX_PLAN_BYTES = 32 * 1024 * 1024
STATES = {"new", "quoted", "admitting", "running", "completed", "failed"}


class ConfigurationError(ValueError):
    """An operator-readable configuration error containing no credential values."""


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Plan JSON contains duplicate fields.")
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError("Plan numbers must be finite.")


def read_plan(path, budget):
    with path.open("rb") as source:
        encoded = source.read(MAX_PLAN_BYTES + 1)
    if len(encoded) > MAX_PLAN_BYTES:
        raise ValueError("Plan exceeds the 32 MiB file limit.")
    payload = json.loads(encoded.decode("utf-8-sig"), object_pairs_hook=unique_fields,
                         parse_constant=reject_constant)
    if (not isinstance(payload, dict) or set(payload) != {"version", "max_cost_lamports", "steps"}
            or type(payload["version"]) is not int or payload["version"] != 1
            or type(payload["max_cost_lamports"]) is not int):
        raise ValueError("Plan requires exactly version=1, max_cost_lamports and steps.")
    if payload["max_cost_lamports"] != budget:
        raise ValueError("The explicit CLI budget must equal the budget declared in the plan.")
    return validate_workflow(payload["steps"], budget)


def context(client, plan, maximum_rate):
    return {"plan": plan, "owner": client.owner, "agent": client.agent,
            "program_id": client.program_id, "gateway_pubkey": client.gateway_pubkey,
            "network": client.network, "treasury": client.treasury,
            "gateway_url": client.url, "max_rate_lamports": maximum_rate}


def client_from_env():
    def required(name):
        value = os.getenv(name, "").strip()
        if not value:
            raise ConfigurationError("Missing required configuration: " + name)
        return value
    values = {name: required(name) for name in ("APERTURE_GATEWAY_URL", "APERTURE_OWNER_PUBKEY",
        "APERTURE_AGENT_KEYPAIR", "APERTURE_PROGRAM_ID", "APERTURE_GATEWAY_PUBKEY", "APERTURE_NETWORK")}
    try:
        key = load_keypair(values["APERTURE_AGENT_KEYPAIR"])
    except Exception as error:
        raise ConfigurationError("APERTURE_AGENT_KEYPAIR must select a readable valid local keypair file.") from error
    try:
        return ApertureClient(values["APERTURE_GATEWAY_URL"], owner=values["APERTURE_OWNER_PUBKEY"],
            agent_keypair=key, program_id=values["APERTURE_PROGRAM_ID"],
            gateway_pubkey=values["APERTURE_GATEWAY_PUBKEY"], network=values["APERTURE_NETWORK"].lower(),
            treasury=os.getenv("APERTURE_TREASURY_PUBKEY", "").strip() or None,
            rpc_url=os.getenv("SOLANA_RPC_URL", "").strip() or None)
    except ValueError as error:
        raise ConfigurationError("Check the gateway URL, deployment keys, network and treasury/RPC pins.") from error


def journal_status(path, plan):
    if not path.exists():
        return {"status": "not_started", "completed_steps": 0, "total_steps": len(plan["steps"])}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"metadata", "steps"} <= tables:
            return {"status": "initializing", "total_steps": len(plan["steps"])}
        saved = db.execute("SELECT value FROM metadata WHERE key='plan'").fetchone()
        if saved is not None and json.loads(saved[0]).get("plan") != plan:
            raise ValueError("The selected journal belongs to a different plan.")
        rows = db.execute("SELECT id,state,data FROM steps ORDER BY rowid").fetchall()
    summaries = []
    for identifier, state, encoded in rows:
        if not isinstance(identifier, str) or not STEP_ID.fullmatch(identifier) or state not in STATES:
            raise ValueError("Journal contains an invalid step record.")
        data = json.loads(encoded)
        task_id = data.get("task", {}).get("task_id")
        item = {"step_id": identifier, "state": state}
        if ApertureClient._valid_task_id(task_id):
            item["task_id"] = task_id
        summaries.append(item)
    completed = sum(item["state"] == "completed" for item in summaries)
    status = ("failed" if any(item["state"] == "failed" for item in summaries) else
              "completed" if completed == len(plan["steps"]) else "pending")
    return {"status": status, "completed_steps": completed, "total_steps": len(plan["steps"]), "steps": summaries}


def progress(event):
    # Do not print quotes, capabilities, source or task output.
    print(json.dumps({key: event[key] for key in
        ("step_id", "state", "task_id", "completed_steps", "total_steps")}, ensure_ascii=True), flush=True)


def file_matches(path, artifact):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_size != artifact["size_bytes"]:
        raise FileExistsError("An output destination already contains a different file.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != artifact["sha256"]:
        raise FileExistsError("An output destination already contains different bytes.")
    return True


def safe_directory(path, root):
    try:
        info = path.lstat()
    except FileNotFoundError:
        path.mkdir()
        info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.resolve().parent != root:
        raise ValueError("Output step directory must be a direct regular child of the selected output root.")


def publish_file(destination, data, artifact):
    if file_matches(destination, artifact):
        return "verified_existing"
    descriptor, temporary = tempfile.mkstemp(prefix=".aperture-", suffix=".incoming", dir=destination.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        try:
            if os.name == "nt":
                # Windows rename atomically refuses an existing destination.
                os.rename(temporary, destination)
            else:
                # POSIX rename would overwrite; linking publishes without replacement.
                os.link(temporary, destination)
        except FileExistsError:
            if not file_matches(destination, artifact):
                raise
            return "verified_existing"
        return "downloaded"
    finally:
        temporary.unlink(missing_ok=True)


def download_sinks(client, result, plan, output, stop):
    output.mkdir(parents=True, exist_ok=True)
    root = output.resolve()
    consumed = {dependency for step in plan["steps"] for dependency in step["depends_on"]}
    pending = []
    for index, step in enumerate(plan["steps"]):
        if step["id"] in consumed:
            continue
        retained = result["steps"][step["id"]]
        task = Task(**retained["task"])
        directory = root / (f"{index + 1:03d}-" + step["id"])
        safe_directory(directory, root)
        names = set()
        for artifact in retained["result"]["receipt"].get("artifacts", []):
            name = artifact["name"]
            folded = name.casefold()
            if not NAME.fullmatch(name) or name.endswith(".") or folded in names:
                raise ValueError("Sink artifact filenames collide or are unsafe for a portable output directory.")
            names.add(folded)
            destination = directory / name
            file_matches(destination, artifact)  # Refuse collisions before downloading any files.
            pending.append((task, retained["result"]["receipt"], artifact, destination))
    files = []
    for task, receipt, artifact, destination in pending:
        if stop.is_set():
            raise InterruptedError("Result downloads stopped; completed jobs remain in the journal.")
        data = client.download_artifact(task, receipt, artifact["name"])
        disposition = publish_file(destination, data, artifact)
        files.append({"path": str(destination), "size_bytes": artifact["size_bytes"], "status": disposition})
        print(json.dumps({"state": "artifact_verified", **files[-1]}), flush=True)
    return files


def cancel_retained(client, runner, plan, seconds):
    """Recover and cancel recorded admissions without submitting any new work."""
    if not runner.path.exists():
        return True
    deadline = time.monotonic() + seconds
    handle = runner._lock()
    try:
        with closing(sqlite3.connect(runner.path)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='steps'").fetchone() is None:
                return True
            saved = db.execute("SELECT value FROM metadata WHERE key='fingerprint'").fetchone()
            if saved is None:
                return True
            if saved[0] != sha256(canonical(context(client, plan, runner.max_rate))):
                raise ValueError("Cancellation journal differs from the approved execution context.")
            rows = db.execute("SELECT id,state,data FROM steps WHERE state IN ('running','admitting')").fetchall()
            steps = {step["id"]: step for step in plan["steps"]}
            for identifier, state, encoded in rows:
                data, step = json.loads(encoded), steps[identifier]
                quote = data["quote"]
                verify_recovered_quote(quote, owner=client.owner, agent=client.agent,
                    program_id=client.program_id, gateway_pubkey=client.gateway_pubkey,
                    network=client.network, treasury=client.treasury, max_rate_lamports=runner.max_rate)
                if (quote["code_sha256"] != sha256(step["source"])
                        or quote["max_cost_lamports"] != step["max_cost_lamports"]
                        or quote["max_runtime_seconds"] != step["max_runtime_seconds"]):
                    raise ValueError("Cancellation task differs from its approved step.")
                task = Task(**data["task"]) if state == "running" else None
                while task is None and time.monotonic() < deadline:
                    cursor = None
                    for _ in range(200):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        page = retry_throttled(lambda: client.list_agent_tasks(limit=50, cursor=cursor), seconds=remaining)
                        match = next((item for item in page["tasks"] if item["quote_id"] == quote["quote_id"]), None)
                        if match:
                            task = retry_throttled(lambda: client.resume_task(match["task_id"]),
                                                   seconds=max(0, deadline - time.monotonic()))
                            if task.quote != quote:
                                raise ValueError("Recovered cancellation task changed its authorization.")
                            data["task"] = runner._task_data(task)
                            runner._save(db, identifier, "running", data)
                            break
                        cursor = page["next_cursor"]
                        if cursor is None:
                            break
                    if task is None:
                        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
                if task is None or time.monotonic() >= deadline:
                    return False
                retry_throttled(lambda: client.cancel(task), seconds=max(0, deadline - time.monotonic()))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                final = client.wait(task, timeout_seconds=remaining, cancel_on_timeout=False, should_stop=lambda: True)
                data["result"] = final
                state = "completed" if final["receipt"]["execution_status"] == "completed" else "failed"
                runner._save(db, identifier, state, data)
                print(json.dumps({"step_id": identifier, "task_id": task.task_id, "state": state,
                                  "cancellation_confirmed": True}), flush=True)
        return True
    finally:
        handle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--workflow-budget-lamports", type=int, required=True,
                        help="Must exactly equal the declared plan budget; no limit is raised automatically.")
    parser.add_argument("--journal", type=Path, help="Private durable journal; rerun with the same plan and journal.")
    parser.add_argument("--output", type=Path, help="Result root; each sink gets its own step directory.")
    parser.add_argument("--max-rate-lamports", type=int, default=25_000)
    parser.add_argument("--wait-seconds", type=int, default=600)
    parser.add_argument("--cancel-wait-seconds", type=int, default=90)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true", help="Validate and show bounds locally without signing or executing.")
    mode.add_argument("--status", action="store_true", help="Read sanitized local journal status without contacting the gateway.")
    args = parser.parse_args()
    client, runner, stop, handlers = None, None, threading.Event(), {}
    phase = "preparation"
    try:
        if not 1 <= args.max_rate_lamports <= 1_000_000_000 or not 1 <= args.wait_seconds <= 3600:
            raise ValueError("Invalid rate ceiling or wait duration.")
        if not 1 <= args.cancel_wait_seconds <= 600:
            raise ValueError("Cancellation wait must be 1 to 600 seconds.")
        plan = read_plan(args.plan, args.workflow_budget_lamports)
        digest = sha256(canonical(plan))
        journal = args.journal or Path(".aperture-runs/workflows") / (digest + ".sqlite3")
        output = args.output or Path(".aperture-runs/results") / digest[:24]
        print(json.dumps({"status": "prepared", "plan_sha256": digest, "total_steps": len(plan["steps"]),
            "maximum_cost_lamports": plan["max_cost_lamports"], "max_rate_lamports": args.max_rate_lamports,
            "journal": str(journal.resolve()), "output": str(output.resolve())}), flush=True)
        if args.prepare:
            return 0
        print(json.dumps(journal_status(journal, plan)), flush=True)
        if args.status:
            return 0
        phase = "configuration"
        client = client_from_env()
        runner = WorkflowRunner(client, journal, max_rate_lamports=args.max_rate_lamports)
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            number = getattr(signal, name, None)
            if number is not None:
                handlers[number] = signal.signal(number, lambda *_: stop.set())
        phase = "execution"
        result = runner.run(plan["steps"], max_cost_lamports=plan["max_cost_lamports"],
            on_progress=progress, wait_seconds=args.wait_seconds, should_stop=stop.is_set)
        phase = "result_download"
        files = download_sinks(client, result, plan, output, stop)
        print(json.dumps({"status": "completed", "verified_steps": len(result["steps"]),
                          "verified_files": len(files), "output": str(output.resolve())}), flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        interrupted = stop.is_set() or isinstance(error, (KeyboardInterrupt, InterruptedError))
        if interrupted:
            stop.set()
        confirmed = None
        if interrupted and client is not None and runner is not None:
            try:
                confirmed = cancel_retained(client, runner, plan, args.cancel_wait_seconds)
            except Exception:
                confirmed = False
        # Exception messages may contain workload output or private configuration.
        response = getattr(error, "response", None)
        message = {"status": "stopped" if interrupted else "paused", "phase": phase,
                   "error_type": type(error).__name__, "resume_same_journal": True}
        if phase == "preparation":
            message["validation_detail"] = str(error)[:300]
        elif isinstance(error, ConfigurationError):
            message["configuration_detail"] = str(error)
        if response is not None:
            message["http_status"] = response.status_code
        if confirmed is not None:
            message["cancellation_confirmed"] = confirmed
        print(json.dumps(message), file=sys.stderr, flush=True)
        print("Keep the journal. Use --status; inspect the selected plan/configuration and rerun the same command. "
              "A terminal failed step needs a revised plan. Unconfirmed cancellation requires recovery before new work.",
              file=sys.stderr, flush=True)
        return 130 if interrupted and confirmed is not False else 3 if confirmed is False else 1
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)
        if client is not None:
            client.http.close()


if __name__ == "__main__":
    raise SystemExit(main())
