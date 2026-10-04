"""Durable agent workflows with explicit data dependencies and a shared spend cap."""
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from .client import (AdmissionUncertainError, Task, canonical, require, sha256,
                     validate_source, verify_receipt, verify_recovered_quote)
from .jobs import NAME, object_reference, workload_manifest
from .retries import retry_throttled

STEP_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def validate_workflow(steps, max_cost_lamports):
    require(type(max_cost_lamports) is int and 0 < max_cost_lamports <= 100_000_000_000,
            "Workflow budget must be a positive integer up to 100 billion lamports")
    require(isinstance(steps, list) and 0 < len(steps) <= 256, "Workflows require 1 to 256 steps")
    normalized, identifiers = [], set()
    for item in steps:
        require(isinstance(item, dict)
                and set(item) <= {"id", "source", "inputs", "parameters", "depends_on",
                                  "max_cost_lamports", "max_runtime_seconds"},
                "Unknown workflow step fields")
        identifier = item.get("id")
        require(isinstance(identifier, str) and STEP_ID.fullmatch(identifier)
                and identifier not in identifiers, "Workflow step IDs must be unique")
        identifiers.add(identifier)
        source = item.get("source")
        validate_source(source)
        cost, runtime = item.get("max_cost_lamports", 100_000), item.get("max_runtime_seconds", 30)
        require(type(cost) is int and 0 < cost <= 1_000_000_000
                and type(runtime) is int and 0 < runtime <= 180, "Invalid workflow step bounds")
        parameters, inputs = item.get("parameters", {}), item.get("inputs", [])
        require(isinstance(inputs, list) and len(inputs) <= 16, "Each step accepts at most 16 inputs")
        dependencies = item.get("depends_on", [])
        require(isinstance(dependencies, list) and all(isinstance(value, str) for value in dependencies),
                "Step dependencies must be an ID list")
        dependencies = set(dependencies)
        references, input_names = [], set()
        for reference in inputs:
            if isinstance(reference, dict) and set(reference) == {"from_step", "artifact"}:
                require(isinstance(reference["from_step"], str) and isinstance(reference["artifact"], str),
                        "Invalid result dependency")
                require(NAME.fullmatch(reference["artifact"]), "Dependency artifacts require safe filenames")
                dependencies.add(reference["from_step"])
                references.append(dict(reference))
                name = reference["artifact"]
            else:
                item = object_reference(reference)
                references.append(item)
                name = item["name"]
            require(name.casefold() not in input_names, "Each workflow step requires unique input filenames")
            input_names.add(name.casefold())
        # Reject known oversized inputs while preparing the entire plan, before
        # earlier steps can consume any budget. Result references are bounded
        # again once their signed sizes become available during execution.
        direct_inputs = [reference for reference in references if "from_step" not in reference]
        parameters = workload_manifest(source, direct_inputs, parameters)["parameters"]
        normalized.append({"id": identifier, "source": source, "inputs": references,
                           "parameters": parameters, "depends_on": sorted(dependencies),
                           "max_cost_lamports": cost, "max_runtime_seconds": runtime})
    require(sum(item["max_cost_lamports"] for item in normalized) <= max_cost_lamports,
            "Sum of step spending caps exceeds the workflow budget")
    for item in normalized:
        require(set(item["depends_on"]) <= identifiers and item["id"] not in item["depends_on"],
                "Workflow contains an unknown or self dependency")
    # Stable topological order accepts branches and joins while preserving caller order.
    ordered, pending, done = [], list(normalized), set()
    while pending:
        ready = next((item for item in pending if set(item["depends_on"]) <= done), None)
        require(ready is not None, "Workflow contains a dependency cycle")
        ordered.append(ready)
        pending.remove(ready)
        done.add(ready["id"])
    return {"version": 1, "max_cost_lamports": max_cost_lamports, "steps": ordered}


class WorkflowRunner:
    """Execute a DAG serially on the wallet's payment channel and resume its journal.

    A single owner channel currently permits one active task. Branches are durable
    data dependencies; this class does not pretend to execute them in parallel.
    Uncertain admissions retain their quote instead of silently creating a new job.
    """
    def __init__(self, client, journal_path, *, max_rate_lamports=25_000):
        self.client, self.path = client, Path(journal_path)
        require(type(max_rate_lamports) is int and 0 < max_rate_lamports <= 1_000_000_000,
                "Workflow rate ceiling must be between 1 and 1,000,000,000")
        self.max_rate = max_rate_lamports

    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(str(self.path) + ".lock", "a+b")
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeError("This workflow journal is already running.") from None
        return handle

    @staticmethod
    def _save(db, identifier, state, data):
        with db:
            db.execute("INSERT INTO steps VALUES(?,?,?) ON CONFLICT(id) "
                       "DO UPDATE SET state=excluded.state,data=excluded.data",
                       (identifier, state, canonical(data)))

    @staticmethod
    def _task(data):
        return Task(**data)

    @staticmethod
    def _task_data(task):
        return {"task_id": task.task_id, "access_token": task.access_token,
                "quote": task.quote, "status": task.status}

    def _recover_admission(self, quote, should_stop=None):
        cursor, seen = None, set()
        for _ in range(200):
            page = retry_throttled(lambda: self.client.list_agent_tasks(limit=50, cursor=cursor),
                                   should_stop=should_stop)
            match = next((item for item in page["tasks"] if item["quote_id"] == quote["quote_id"]), None)
            if match:
                task = retry_throttled(lambda: self.client.resume_task(match["task_id"]),
                                       should_stop=should_stop)
                require(task.quote == quote, "Recovered workflow task changed its authorization")
                return task
            cursor = page["next_cursor"]
            if cursor is None:
                return None
            require(cursor not in seen, "Task history cursor repeated during recovery")
            seen.add(cursor)
        raise RuntimeError("Task history recovery exceeded its bounded page count.")

    def run(self, steps, *, max_cost_lamports, on_progress=None, wait_seconds=600, should_stop=None,
            _journal_handle=None):
        plan = validate_workflow(steps, max_cost_lamports)
        context = {"plan": plan, "owner": self.client.owner, "agent": self.client.agent,
                   "program_id": self.client.program_id, "gateway_pubkey": self.client.gateway_pubkey,
                   "network": self.client.network, "treasury": self.client.treasury,
                   "gateway_url": self.client.url, "max_rate_lamports": self.max_rate}
        if getattr(self.client, "assigned_workflow_id", None):
            context["assigned_workflow_id"] = self.client.assigned_workflow_id
        fingerprint = sha256(canonical(context))
        owns_handle = _journal_handle is None
        handle, db = (self._lock() if owns_handle else _journal_handle), None
        try:
            db = sqlite3.connect(self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
                             "CREATE TABLE IF NOT EXISTS steps(id TEXT PRIMARY KEY,state TEXT NOT NULL,data TEXT NOT NULL);")
            existing = db.execute("SELECT value FROM metadata WHERE key='fingerprint'").fetchone()
            require(existing is None or existing[0] == fingerprint,
                    "Workflow plan or execution identity changed; use a new journal for a new workflow")
            if existing is None:
                with db:
                    db.execute("INSERT INTO metadata VALUES('fingerprint',?)", (fingerprint,))
                    db.execute("INSERT INTO metadata VALUES('plan',?)", (canonical(context),))
            completed = {}
            for step in plan["steps"]:
                if should_stop and should_stop():
                    raise InterruptedError("Workflow stopped before admitting another step.")
                if getattr(self.client, "assigned_workflow_id", None):
                    self.client.workflow_binding = {"workflow_id": self.client.assigned_workflow_id, "step_id": step["id"]}
                row = db.execute("SELECT state,data FROM steps WHERE id=?", (step["id"],)).fetchone()
                state, data = (row[0], json.loads(row[1])) if row else ("new", {})
                if state == "failed":
                    raise RuntimeError(f"Workflow step {step['id']} failed previously; inspect its retained result.")
                inputs = []
                for reference in step["inputs"]:
                    if "from_step" in reference:
                        previous = completed[reference["from_step"]]["result"]["receipt"]
                        item = next((item for item in previous.get("artifacts", [])
                                     if item["name"] == reference["artifact"]), None)
                        require(item is not None, f"Missing dependency artifact {reference['artifact']}")
                        inputs.append(item)
                    else:
                        inputs.append(reference)
                spec = workload_manifest(step["source"], inputs, step["parameters"])
                if state == "completed":
                    task = self._task(data["task"])
                    self._verify_step(task, step, spec)
                    result = data["result"]
                    verify_receipt(result["receipt"], quote=task.quote,
                                   task_id=task.task_id, full_log=result["full_log"])
                    if result["receipt"]["settlement_type"] == "DEVNET":
                        self.client.verify_devnet_task_receipt(task, result["receipt"])
                    completed[step["id"]] = data
                    self._progress(on_progress, step, "completed", completed, plan, task)
                    continue
                if state == "new" or (state == "quoted" and data["quote"]["expires_at"] <= time.time()):
                    quote = retry_throttled(lambda: self.client.quote_job(step["source"], inputs=inputs, parameters=step["parameters"],
                        max_cost_lamports=step["max_cost_lamports"], max_runtime_seconds=step["max_runtime_seconds"],
                        max_rate_lamports=self.max_rate), should_stop=should_stop)
                    data, state = {"quote": quote}, "quoted"
                    self._save(db, step["id"], state, data)
                if state in {"quoted", "admitting"}:
                    self._verify_quote_step(data["quote"], step, spec)
                    task = self._recover_admission(data["quote"], should_stop) if state == "admitting" else None
                    if task is None:
                        if data["quote"]["expires_at"] <= time.time():
                            raise AdmissionUncertainError(data["quote"]["quote_id"])
                        self._save(db, step["id"], "admitting", data)
                        if should_stop and should_stop():
                            raise InterruptedError("Workflow stopped before task admission.")
                        task = retry_throttled(lambda: self.client.execute_job(data["quote"], step["source"], inputs=inputs,
                            parameters=step["parameters"], max_rate_lamports=self.max_rate),
                            seconds=min(75, data["quote"]["expires_at"] - time.time() - 2), should_stop=should_stop)
                    data, state = {"quote": data["quote"], "task": self._task_data(task)}, "running"
                    self._save(db, step["id"], state, data)
                    self._progress(on_progress, step, "admitted", completed, plan, task)
                task = self._task(data["task"])
                self._verify_step(task, step, spec)
                self._progress(on_progress, step, "running", completed, plan, task)
                result = self.client.wait(task, timeout_seconds=wait_seconds, cancel_on_timeout=False,
                                          should_stop=should_stop)
                data["result"] = result
                successful = result["receipt"]["execution_status"] == "completed"
                self._save(db, step["id"], "completed" if successful else "failed", data)
                if not successful:
                    self._progress(on_progress, step, "failed", completed, plan, task)
                    raise RuntimeError(f"Workflow step {step['id']} did not complete; downstream steps were withheld. "
                                       + result["full_log"][-500:])
                completed[step["id"]] = data
                self._progress(on_progress, step, "completed", completed, plan, task)
            return {"workflow_id": fingerprint, "status": "completed", "max_cost_lamports": max_cost_lamports,
                    "steps": completed}
        finally:
            if db:
                db.close()
            if owns_handle:
                handle.close()

    def _verify_step(self, task, step, spec):
        self._verify_quote_step(task.quote, step, spec)

    def _verify_quote_step(self, quote, step, spec):
        verify_recovered_quote(quote, owner=self.client.owner, agent=self.client.agent,
            program_id=self.client.program_id, gateway_pubkey=self.client.gateway_pubkey,
            network=self.client.network, treasury=self.client.treasury, max_rate_lamports=self.max_rate)
        require(quote.get("workload") == spec
                and quote["max_cost_lamports"] == step["max_cost_lamports"]
                and quote["max_runtime_seconds"] == step["max_runtime_seconds"],
                "Workflow journal task differs from its approved step")
        expected = {"workflow_id": self.client.assigned_workflow_id, "step_id": step["id"]} if getattr(self.client, "assigned_workflow_id", None) else None
        require(quote.get("workflow") == expected, "Workflow journal task belongs to a different owner-approved run")

    @staticmethod
    def _progress(callback, step, state, completed, plan, task):
        if callback:
            callback({"step_id": step["id"], "state": state, "task_id": task.task_id,
                      "completed_steps": len(completed), "total_steps": len(plan["steps"])})
