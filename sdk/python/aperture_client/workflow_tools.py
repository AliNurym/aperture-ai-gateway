"""Non-blocking MCP workflow control; all authorization remains in the local host."""
import json
import secrets
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from .client import ApertureClient, Task, canonical, require, sha256
from .workflows import WorkflowRunner, validate_workflow


class WorkflowTools:
    def __init__(self, tools, directory, max_cost_lamports):
        self.tools = tools
        self.root = Path(directory).resolve()
        self.maximum_cost = max_cost_lamports
        self.lock = threading.RLock()
        self.active = {}

    def _path(self, identifier, suffix):
        require(isinstance(identifier, str) and re.fullmatch(r"[0-9a-f]{64}", identifier),
                "Invalid workflow ID")
        return self.root / (identifier + suffix)

    def _write(self, path, value):
        with self.lock:
            temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
            temporary.write_text(canonical(value), encoding="utf-8")
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            try:
                deadline = time.monotonic() + 3
                while True:
                    try:
                        temporary.replace(path)
                        break
                    except PermissionError:
                        # Windows readers may briefly deny rename while polling.
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.02)
            finally:
                temporary.unlink(missing_ok=True)

    def _context(self):
        client = self.tools.client
        return {"owner": client.owner, "agent": client.agent, "program_id": client.program_id,
                "gateway_pubkey": client.gateway_pubkey, "network": client.network,
                "treasury": client.treasury, "gateway_url": client.url,
                "max_step_cost": self.tools.max_cost_lamports, "max_runtime": self.tools.max_runtime_seconds,
                "max_rate": self.tools.max_rate_lamports, "max_workflow_cost": self.maximum_cost}

    def prepare(self, steps, max_cost_lamports):
        require(max_cost_lamports <= self.maximum_cost, "Workflow budget exceeds the operator's local ceiling")
        plan = validate_workflow(steps, max_cost_lamports)
        for step in plan["steps"]:
            require(step["max_cost_lamports"] <= self.tools.max_cost_lamports
                    and step["max_runtime_seconds"] <= self.tools.max_runtime_seconds,
                    "Workflow step exceeds the configured MCP execution limits")
        payload = {"context": self._context(), "plan": plan}
        identifier = sha256(canonical(payload))
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self._path(identifier, ".plan.json")
            status_path = self._path(identifier, ".status.json")
            try:
                handle = WorkflowRunner(self.tools.client, self._path(identifier, ".sqlite3"))._lock()
            except RuntimeError:
                if path.exists() and status_path.exists():
                    return self.get(identifier)
                raise RuntimeError("This workflow is being prepared by another host. Retry preparation.") from None
            try:
                if not path.exists():
                    require(len(list(self.root.glob("*.plan.json"))) < 32,
                            "Workflow journal capacity reached; archive finished local workflows first")
                    self._write(path, payload)
                require(self._load(identifier) == plan, "The retained workflow differs from this plan")
                if not status_path.exists():
                    # A crash after writing the plan must not strand its identity.
                    # Preserve the journal: start recovers any retained admissions.
                    self._write(status_path, {"workflow_id": identifier, "status": "prepared",
                        "completed_steps": 0, "total_steps": len(plan["steps"]),
                        "max_cost_lamports": max_cost_lamports})
            finally:
                handle.close()
        return self.get(identifier)

    def _load(self, identifier):
        payload = json.loads(self._path(identifier, ".plan.json").read_text(encoding="utf-8"))
        require(payload["context"] == self._context() and sha256(canonical(payload)) == identifier,
                "Workflow plan or operator execution configuration changed")
        return payload["plan"]

    def get(self, identifier):
        with self.lock:
            self._load(identifier)
            status_path = self._path(identifier, ".status.json")
            status = json.loads(status_path.read_text(encoding="utf-8"))
            thread = self.active.get(identifier)
            if status["status"] != "running" or (thread is not None and thread.is_alive()):
                return {**status, "cancellation_pending": self._cancellation_pending(identifier)}
            try:
                # This exact lock also covers another host's thread startup and
                # final status write, so a live workflow cannot appear abandoned.
                handle = WorkflowRunner(self.tools.client, self._path(identifier, ".sqlite3"))._lock()
            except RuntimeError:
                return {**status, "cancellation_pending": self._cancellation_pending(identifier)}
            try:
                # Re-read under the process lock in case the other host finished
                # between our initial read and acquiring the journal lock.
                status = json.loads(status_path.read_text(encoding="utf-8"))
                if status["status"] != "running":
                    return status
                terminal_failure = bool(self._journal_rows(identifier, "failed"))
                status = {**status, "status": "failed" if terminal_failure else "attention",
                    "detail": "The workflow host stopped. Start the same workflow ID to recover its journal."
                              if not terminal_failure else "The retained journal contains a terminal failed step.",
                    "requires_resume": not terminal_failure, "resume_available": not terminal_failure,
                    "cancellation_pending": self._cancellation_pending(identifier)}
                self._write(status_path, status)
                return status
            finally:
                handle.close()

    def _journal_rows(self, identifier, state):
        journal = self._path(identifier, ".sqlite3")
        if not journal.exists():
            return []
        with closing(sqlite3.connect(journal.as_uri() + "?mode=ro", uri=True)) as db:
            # The runner creates the database before installing its schema.
            # An immediate cancellation still records the stop flag below.
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='steps'").fetchone() is None:
                return []
            return db.execute("SELECT state,data FROM steps WHERE state=?", (state,)).fetchall()

    def _cancellation_pending(self, identifier):
        # A retained stop flag is intent, not evidence that a cancellation is
        # still pending. Final verified results are saved as completed/failed.
        return self._path(identifier, ".stop").exists() and bool(
            self._journal_rows(identifier, "running") or self._journal_rows(identifier, "admitting"))

    def _client(self):
        original = self.tools.client
        return ApertureClient(original.url, owner=original.owner, agent_keypair=original.key,
            program_id=original.program_id, gateway_pubkey=original.gateway_pubkey,
            network=original.network, treasury=original.treasury, rpc_url=original.rpc_url)

    def start(self, identifier):
        if not self.tools.execution_enabled:
            raise PermissionError("Workflow execution requires APERTURE_MCP_EXECUTION_ENABLED=true.")
        with self.lock:
            plan = self._load(identifier)
            if identifier in self.active and self.active[identifier].is_alive():
                return self.get(identifier)
            require(not any(thread.is_alive() for thread in self.active.values()),
                    "This MCP host already has an active workflow on its payment channel")
            current = self.get(identifier)
            if current["status"] == "completed":
                return current
            require(current.get("resume_available", True),
                    "This workflow has a terminal failed step; prepare a revised workflow instead of resuming it")
            try:
                handle = WorkflowRunner(self.tools.client, self._path(identifier, ".sqlite3"))._lock()
            except RuntimeError:
                return {**self.get(identifier), "status": "running", "requires_resume": False,
                        "running_on_other_host": True}
            try:
                self._path(identifier, ".stop").unlink(missing_ok=True)
                thread = threading.Thread(target=self._run, args=(identifier, plan, handle), daemon=True)
                self.active = {identifier: thread}
                self._write(self._path(identifier, ".status.json"),
                    {**current, "status": "running", "requires_resume": False,
                     "cancellation_pending": False})
                thread.start()
            except BaseException:
                handle.close()
                raise
            return self.get(identifier)

    def _run(self, identifier, plan, journal_handle):
        client = None
        status_path = self._path(identifier, ".status.json")
        stop_path = self._path(identifier, ".stop")
        try:
            client = self._client()
            def progress(event):
                self._write(status_path, {"workflow_id": identifier, "status": "running",
                    "max_cost_lamports": plan["max_cost_lamports"], **event})
            result = WorkflowRunner(client, self._path(identifier, ".sqlite3"),
                                    max_rate_lamports=self.tools.max_rate_lamports).run(
                plan["steps"], max_cost_lamports=plan["max_cost_lamports"], on_progress=progress,
                should_stop=stop_path.exists, _journal_handle=journal_handle)
            final_step = result["steps"][plan["steps"][-1]["id"]]
            consumed = {dependency for step in plan["steps"] for dependency in step["depends_on"]}
            outputs = [{"step_id": key, "task_id": value["task"]["task_id"],
                        "artifacts": value["result"]["receipt"].get("artifacts", [])}
                       for key, value in result["steps"].items() if key not in consumed]
            self._write(status_path, {"workflow_id": identifier, "status": "completed",
                "completed_steps": len(plan["steps"]), "total_steps": len(plan["steps"]),
                "max_cost_lamports": plan["max_cost_lamports"],
                "final_task_id": final_step["task"]["task_id"],
                "artifacts": final_step["result"]["receipt"].get("artifacts", []),
                "outputs": outputs,
                "steps": [{"id": key, "task_id": value["task"]["task_id"]}
                          for key, value in result["steps"].items()]})
        except Exception as error:
            # Keep the admission/task journal. Another explicit start resumes it.
            previous = json.loads(status_path.read_text(encoding="utf-8"))
            terminal_failure = bool(self._journal_rows(identifier, "failed"))
            status = "stopped" if stop_path.exists() else "failed" if terminal_failure else "attention"
            self._write(status_path, {**previous, "status": status,
                "detail": str(error)[:1500], "resume_available": not terminal_failure,
                "requires_resume": not terminal_failure,
                "cancellation_pending": self._cancellation_pending(identifier)})
        finally:
            try:
                if client is not None:
                    client.http.close()
            finally:
                journal_handle.close()

    def cancel(self, identifier):
        with self.lock:
            self._load(identifier)
            self._path(identifier, ".stop").touch()
            requested = []
            for _, encoded in self._journal_rows(identifier, "running"):
                task = Task(**json.loads(encoded)["task"])
                self.tools.client.cancel(task)
                requested.append(task.task_id)
            return {"workflow_id": identifier, "status": "stop_requested",
                    "cancellation_requested_for": requested,
                    "next_step": "Poll get_compute_workflow for terminal state and retained results."}
