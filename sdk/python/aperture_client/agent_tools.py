"""Bounded MCP-facing operations built on Aperture's verified Python client."""
from __future__ import annotations

import threading
import base64
import time
from collections import OrderedDict

from .client import MAX_SOURCE_BYTES, ApertureClient, Task, validate_source
from .jobs import workload_manifest


MAX_SOURCE_CHARS = MAX_SOURCE_BYTES  # Also bounded by the UTF-8 byte limit below.
MAX_OUTPUT_CHARS = 16_000


class ApertureAgentTools:
    """Hold short-lived quotes and task capabilities for one local MCP process."""

    def __init__(self, client: ApertureClient, *, max_cost_lamports: int,
                 max_runtime_seconds: int, max_rate_lamports: int = 25_000,
                 execution_enabled: bool = False, max_pending_quotes: int = 8,
                 max_tracked_tasks: int = 64, workflow_directory=None,
                 max_workflow_cost_lamports=None):
        self.client = client
        self.max_cost_lamports = self._positive_int(max_cost_lamports, "max_cost_lamports")
        self.max_runtime_seconds = self._positive_int(max_runtime_seconds, "max_runtime_seconds")
        self.max_rate_lamports = self._positive_int(max_rate_lamports, "max_rate_lamports")
        self.max_pending_quotes = self._positive_int(max_pending_quotes, "max_pending_quotes")
        self.max_tracked_tasks = self._positive_int(max_tracked_tasks, "max_tracked_tasks")
        if self.max_rate_lamports > 1_000_000_000:
            raise ValueError("Maximum rate cannot exceed 1,000,000,000 lamports per second.")
        if self.max_runtime_seconds > 180:
            raise ValueError("Maximum runtime cannot exceed the gateway's 180 second limit.")
        if self.max_cost_lamports > 1_000_000_000:
            raise ValueError("Maximum cost cannot exceed the gateway's 1 SOL limit.")
        if type(execution_enabled) is not bool:
            raise ValueError("execution_enabled must be a boolean.")
        if self.max_pending_quotes > 64 or self.max_tracked_tasks > 256:
            raise ValueError("MCP quote and task tracking limits are too large.")
        self.execution_enabled = execution_enabled
        self._lock = threading.RLock()
        self._quotes: OrderedDict[str, tuple[str, dict]] = OrderedDict()
        self._tasks: OrderedDict[str, Task] = OrderedDict()
        self._results: OrderedDict[str, dict] = OrderedDict()
        self._task_quotes: dict[str, str] = {}
        self._started_quotes: OrderedDict[str, str] = OrderedDict()
        self._last_poll: dict[str, float] = {}
        self.workflows = None
        if workflow_directory is not None:
            from .workflow_tools import WorkflowTools
            ceiling = self._positive_int(max_workflow_cost_lamports or self.max_cost_lamports,
                                         "max_workflow_cost_lamports")
            if ceiling > 100_000_000_000:
                raise ValueError("Workflow spending ceiling exceeds 100 billion lamports.")
            self.workflows = WorkflowTools(self, workflow_directory, ceiling)

    @staticmethod
    def _positive_int(value, name: str) -> int:
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
        return value

    def _requested_limit(self, value, configured: int, name: str) -> int:
        if value is None:
            return configured
        value = self._positive_int(value, name)
        if value > configured:
            raise ValueError(f"{name} exceeds this Aperture MCP server's configured limit ({configured}).")
        return value

    @staticmethod
    def _quote_summary(quote: dict) -> dict:
        analysis = quote.get("analysis") or {}
        return {
            "quote_id": quote["quote_id"],
            "code_sha256": quote["code_sha256"],
            "rate_lamports_per_second": quote["rate_lamports"],
            "maximum_charge_lamports": quote["max_cost_lamports"],
            "maximum_runtime_seconds": quote["max_runtime_seconds"],
            "effective_runtime_seconds": quote.get("effective_runtime_seconds"),
            "expires_at": quote["expires_at"],
            "source_policy": analysis.get("security"),
            "complexity_score": analysis.get("complexity_score"),
            "network": quote.get("network"),
            **({"workload_sha256": quote["workload_sha256"],
                "inputs": quote["workload"]["inputs"]} if "workload" in quote else {}),
        }

    def _expire_quotes(self) -> None:
        now = int(time.time())
        expired = [quote_id for quote_id, (_, quote) in self._quotes.items()
                   if type(quote.get("expires_at")) is int and quote["expires_at"] <= now]
        for quote_id in expired:
            self._quotes.pop(quote_id, None)

    def _task_room_to_free(self) -> str | None:
        if len(self._tasks) + len(self._results) < self.max_tracked_tasks:
            return None
        if not self._results:
            raise RuntimeError(
                "Aperture MCP is tracking its maximum number of active tasks. "
                "Collect a result before starting another task."
            )
        return next(iter(self._results))

    def _free_cached_result(self, task_id: str) -> None:
        self._results.pop(task_id, None)
        quote_id = self._task_quotes.pop(task_id, None)
        self._last_poll.pop(task_id, None)
        if quote_id:
            self._started_quotes.pop(quote_id, None)

    def quote_python(self, source: str, max_cost_lamports: int | None = None,
                     max_runtime_seconds: int | None = None) -> dict:
        """Estimate a Python task. This does not execute code or spend SOL."""
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty Python program.")
        if len(source) > MAX_SOURCE_CHARS:
            raise ValueError(f"source exceeds the gateway limit of {MAX_SOURCE_CHARS} characters.")
        validate_source(source)
        cost = self._requested_limit(max_cost_lamports, self.max_cost_lamports, "max_cost_lamports")
        runtime = self._requested_limit(max_runtime_seconds, self.max_runtime_seconds, "max_runtime_seconds")

        with self._lock:
            self._expire_quotes()
            if len(self._quotes) >= self.max_pending_quotes:
                raise RuntimeError(
                    "Too many unused Aperture quotes are pending. "
                    "Start or let an earlier quote expire first."
                )
            quote = self.client.quote(source, max_cost_lamports=cost,
                                      max_runtime_seconds=runtime, max_rate_lamports=self.max_rate_lamports)
            quote_id = quote["quote_id"]
            self._quotes[quote_id] = (source, quote)
            return self._quote_summary(quote)

    def start_python_task(self, quote_id: str) -> dict:
        """Start the exact quoted source within the configured owner-delegated limits."""
        if not self.execution_enabled:
            raise PermissionError(
                "Task execution is disabled. Set APERTURE_MCP_EXECUTION_ENABLED=true only after "
                "reviewing the agent passport and MCP budget limits."
            )
        if not isinstance(quote_id, str) or not quote_id:
            raise ValueError("quote_id must be the identifier returned by quote_python.")

        with self._lock:
            self._expire_quotes()
            existing_task_id = self._started_quotes.get(quote_id)
            if existing_task_id:
                if existing_task_id in self._tasks:
                    task = self._tasks[existing_task_id]
                    return {"task_id": task.task_id, "status": "already_started",
                            "quote": self._quote_summary(task.quote)}
                if existing_task_id in self._results:
                    cached = self._results[existing_task_id]
                    return {"task_id": existing_task_id, "status": "already_completed",
                            "execution_status": cached["status"],
                            "quote": cached["quote"]}

            entry = self._quotes.get(quote_id)
            if not entry:
                raise ValueError("Quote is unknown or expired in this MCP process. Request a fresh quote.")
            source, quote = entry
            if type(quote.get("expires_at")) is not int or quote["expires_at"] <= int(time.time()):
                self._quotes.pop(quote_id, None)
                raise ValueError("Quote expired before task admission. Request a fresh quote.")

            eviction_candidate = self._task_room_to_free()
            # ApertureClient retries this exact signed admission after an ambiguous
            # response. The gateway keys admission by quote_id, preventing duplicates.
            if "workload" in quote:
                task = self.client.execute_job(quote, source, inputs=quote["workload"]["inputs"],
                    parameters=quote["workload"]["parameters"], max_rate_lamports=self.max_rate_lamports)
            else:
                task = self.client.execute(quote, source, max_rate_lamports=self.max_rate_lamports)
            if eviction_candidate is not None:
                self._free_cached_result(eviction_candidate)
            self._quotes.pop(quote_id, None)
            self._tasks[task.task_id] = task
            self._task_quotes[task.task_id] = quote_id
            self._started_quotes[quote_id] = task.task_id
            return {"task_id": task.task_id, "status": task.status, "quote": self._quote_summary(quote)}

    def list_python_tasks(self, limit: int = 20, cursor: str | None = None) -> dict:
        """List this configured agent's bounded recent task history."""
        with self._lock:
            page = self.client.list_agent_tasks(limit=limit, cursor=cursor)
            return {
                "tasks": page["tasks"], "limit": limit, "cursor": cursor,
                "next_cursor": page["next_cursor"],
            }

    def resume_python_task(self, task_id: str) -> dict:
        """Reconnect to this agent's existing task without creating a new one."""
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be returned by list_python_tasks.")

        with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                return {"task_id": task_id, "status": "already_tracked",
                        "task_status": task.status,
                        "quote": self._quote_summary(task.quote)}
            if task_id in self._results:
                cached = self._results[task_id]
                self._results.move_to_end(task_id)
                return {"task_id": task_id, "status": "already_completed",
                        "execution_status": cached["status"],
                        "quote": cached["quote"]}

            eviction_candidate = self._task_room_to_free()
            task = self.client.resume_task(task_id)
            if eviction_candidate is not None:
                self._free_cached_result(eviction_candidate)
            self._tasks[task.task_id] = task
            self._task_quotes[task.task_id] = task.quote["quote_id"]
            self._started_quotes[task.quote["quote_id"]] = task.task_id
            return {
                "task_id": task.task_id,
                "status": "resumed",
                "task_status": task.status,
                "quote": self._quote_summary(task.quote),
                "next_step": "Poll get_python_task; this does not start or charge another job.",
            }

    def get_python_task(self, task_id: str) -> dict:
        """Poll a task and return output only after the SDK verifies its receipt."""
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be the identifier returned by start_python_task.")

        with self._lock:
            cached = self._results.get(task_id)
            if cached is not None:
                self._results.move_to_end(task_id)
                return cached
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(
                    "Task is not tracked by this MCP process. "
                    "Use list_python_tasks and resume_python_task to recover an existing task."
                )

            now = time.monotonic()
            if now - self._last_poll.get(task_id, 0.0) < 0.5:
                return {"task_id": task_id, "status": "pending", "retry_after_seconds": 0.5}
            self._last_poll[task_id] = now
            snapshot = self.client.poll(task)
            if snapshot.get("status") != "completed":
                return {"task_id": task_id, "status": snapshot.get("status", "unknown"),
                        "ready": False, "retry_after_seconds": 1}

            try:
                # wait() performs the gateway/worker signature checks and, for
                # Devnet, independently verifies the on-chain task receipt.
                result = self.client.wait(task, timeout_seconds=0.1, cancel_on_timeout=False)
            except TimeoutError:
                return {"task_id": task_id, "status": "settlement_pending",
                        "ready": False, "retry_after_seconds": 1}

            receipt = result["receipt"]
            output = result.get("output")
            if not isinstance(output, str):
                output = result.get("full_log", "")
            truncated = len(output) > MAX_OUTPUT_CHARS
            output = output[:MAX_OUTPUT_CHARS]
            summary = {
                "task_id": task_id,
                "status": receipt.get("execution_status", "unknown"),
                "ready": True,
                "verified": True,
                "output": output,
                "output_truncated": truncated,
                "exit_code": receipt.get("exit_code"),
                "execution_time_seconds": receipt.get("execution_time"),
                "charged_lamports": receipt.get("charged_lamports"),
                "settlement_type": receipt.get("settlement_type"),
                "settlement_signature": receipt.get("settlement_signature"),
                "full_log_sha256": receipt.get("output_sha256"),
                "receipt": receipt,
                "artifacts": receipt.get("artifacts", []),
                "verification_note": (
                    "Signatures and hashes were checked; they do not prove that remote hardware "
                    "faithfully executed the source."
                ),
                "quote": self._quote_summary(task.quote),
            }
            self._tasks.pop(task_id, None)
            self._last_poll.pop(task_id, None)
            self._results[task_id] = summary
            self._results.move_to_end(task_id)
            return summary

    def upload_compute_input(self, name: str, content_base64: str) -> dict:
        """Stage bounded agent-provided data without opening arbitrary host files."""
        if not self.execution_enabled:
            raise PermissionError("Data uploads require the configured MCP execution permission.")
        if not isinstance(content_base64, str) or len(content_base64) > 1_400_000:
            raise ValueError("Inline MCP inputs are limited to 1 MiB; use the SDK for larger files.")
        data = base64.b64decode(content_base64, validate=True)
        if len(data) > 1_048_576:
            raise ValueError("Inline MCP inputs are limited to 1 MiB.")
        with self._lock:
            return self.client.upload_input(data, name=name)

    def get_compute_storage(self):
        with self._lock:
            return self.client.storage_usage()

    def release_compute_object(self, reference: dict):
        if not self.execution_enabled:
            raise PermissionError("Object release requires the configured MCP execution permission.")
        with self._lock:
            return self.client.release_object(reference)

    def quote_compute_job(self, source: str, inputs: list[dict], parameters: dict | None = None,
                          max_cost_lamports: int | None = None, max_runtime_seconds: int | None = None):
        validate_source(source)
        workload_manifest(source, inputs, parameters)
        cost = self._requested_limit(max_cost_lamports, self.max_cost_lamports, "max_cost_lamports")
        runtime = self._requested_limit(max_runtime_seconds, self.max_runtime_seconds, "max_runtime_seconds")
        with self._lock:
            self._expire_quotes()
            if len(self._quotes) >= self.max_pending_quotes:
                raise RuntimeError("Too many unused compute quotes are pending.")
            quote = self.client.quote_job(source, inputs=inputs, parameters=parameters,
                max_cost_lamports=cost, max_runtime_seconds=runtime, max_rate_lamports=self.max_rate_lamports)
            self._quotes[quote["quote_id"]] = (source, quote)
            return self._quote_summary(quote)

    def read_compute_artifact(self, task_id: str, name: str, max_bytes: int = 65536) -> dict:
        """Read a small final result only after ownership, receipt and byte verification."""
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1_048_576:
            raise ValueError("Artifact reads allow a limit of 1 byte to 1 MiB.")
        with self._lock:
            task = self.client.resume_task(task_id)
            result = self.client.wait(task, timeout_seconds=1, cancel_on_timeout=False)
            item = next((item for item in result["receipt"].get("artifacts", [])
                         if item["name"] == name), None)
            if item is None:
                raise ValueError("Named file is absent from the verified result.")
            if item["size_bytes"] > max_bytes:
                return {"task_id": task_id, "artifact": item, "ready": True, "verified": True,
                        "content_available": False,
                        "next_step": "Consume this reference in another compute step or download it with the SDK."}
            content = self.client.download_artifact(task, result["receipt"], name)
            return {"task_id": task_id, "artifact": item, "ready": True, "verified": True,
                    "content_available": True, "encoding": "base64",
                    "content_base64": base64.b64encode(content).decode("ascii")}

    def cancel_python_task(self, task_id: str) -> dict:
        """Request cancellation of a tracked task; fetch its receipt separately."""
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be the identifier returned by start_python_task.")
        with self._lock:
            if task_id in self._results:
                return {"task_id": task_id, "status": "already_completed"}
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError("Task is not tracked by this MCP process.")
            self.client.cancel(task)
            return {"task_id": task_id, "status": "cancellation_requested",
                    "ready": False, "next_step": "Poll get_python_task for the verified final receipt."}
