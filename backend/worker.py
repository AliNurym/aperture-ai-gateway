"""Authenticated worker coordinator with isolated jobs and a durable result outbox."""

from __future__ import annotations

import argparse
import codecs
import hashlib
import math
import os
import platform
import socket
import tempfile
import threading
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from worker_journal import WorkerInstanceLock, WorkerJournal, container_name
from worker_identity import WorkerIdentity
from worker_sandbox import DockerSandbox, MAX_OUTPUT_BYTES, MAX_RUNTIME_SECONDS, TrustedLocalExecutor


load_dotenv(Path(__file__).with_name(".env"))
parser = argparse.ArgumentParser(description="Aperture authenticated compute worker")
parser.add_argument("--node-id", default=None)
parser.add_argument("--gateway", default=None, help="Gateway URL; defaults to GATEWAY_API_URL")
parser.add_argument("--token", default=None, help="Prefer APERTURE_WORKER_TOKEN in the environment")
parser.add_argument("--allow-unsafe-local-execution", action="store_true", help="Execute trusted development workloads directly on the host")
parser.add_argument("--trusted-source-directory", type=Path, default=None, help="Limit trusted local execution to exact UTF-8 .py files reviewed before startup")
args, _ = parser.parse_known_args()
API_URL = (args.gateway or os.getenv("GATEWAY_API_URL") or "http://127.0.0.1:8000").rstrip("/")
NODE_ID = args.node_id or os.getenv("APERTURE_NODE_ID") or f"NODE-CPU-{socket.gethostname()}"
WORKER_TOKEN = args.token or os.getenv("APERTURE_WORKER_TOKEN", "")
ALLOW_UNSAFE_LOCAL_EXECUTION = args.allow_unsafe_local_execution or os.getenv("APERTURE_ALLOW_UNSAFE_LOCAL_EXECUTION", "false").lower() == "true"
STATE_ROOT = Path(os.getenv("APERTURE_WORKER_STATE_DIR", str(Path.home() / ".aperture-worker" / hashlib.sha256(NODE_ID.encode()).hexdigest()[:16])))
SANDBOX_IMAGE = os.getenv("APERTURE_SANDBOX_IMAGE", "aperture-task:local")
current_status = "ONLINE (IDLE)"
WORKER_IDENTITY = None


def worker_token_is_configured(token):
    return len((token or "").strip()) >= 16 and (token or "").strip().lower() not in {
        "replace-with-a-long-random-secret", "change-me", "example-token",
    }


def worker_headers():
    return {"X-Aperture-Worker-Token": WORKER_TOKEN, "X-Aperture-Worker-Id": NODE_ID}


def detect_hardware():
    # Task images expose CPU only. A GPU on the coordinator does not mean jobs
    # have access to it, so the advertised execution capability stays honest.
    return f"CPU worker ({platform.processor() or platform.machine()})", 0.0, 0.0


GPU_NAME, VRAM_TOTAL, TFLOPS = detect_hardware()


def register_heartbeat(stop_event, executor=None):
    while not stop_event.is_set():
        try:
            requests.post(f"{API_URL}/register_node", json={
                "node_id": NODE_ID, "gpu_name": GPU_NAME, "vram_total": 0.0,
                "vram_used": None, "gpu_temp": None, "gpu_util": None,
                "power_watts": None, "tflops": 0.0, "status": current_status,
                "worker_pubkey": WORKER_IDENTITY.pubkey if WORKER_IDENTITY else None,
                "execution_mode": "trusted_local" if ALLOW_UNSAFE_LOCAL_EXECUTION else "docker",
                "source_policy": "exact_hash_allowlist" if ALLOW_UNSAFE_LOCAL_EXECUTION and executor and executor.approved_hashes is not None else "operator_trusted" if ALLOW_UNSAFE_LOCAL_EXECUTION else "gateway_ast",
                "approved_source_count": len(executor.approved_hashes) if ALLOW_UNSAFE_LOCAL_EXECUTION and executor and executor.approved_hashes is not None else None,
            }, headers=worker_headers(), timeout=4)
        except requests.RequestException:
            pass
        stop_event.wait(5)


def task_runtime(task, now=None):
    """Use both signed maximum runtime and the server's absolute lease deadline."""
    now = time.time() if now is None else now
    maximum = float(task.get("max_runtime_seconds", MAX_RUNTIME_SECONDS))
    deadline = float(task.get("execution_deadline", task.get("deadline_unix", now + maximum)))
    if not math.isfinite(maximum) or maximum <= 0 or maximum > MAX_RUNTIME_SECONDS or not math.isfinite(deadline):
        raise ValueError("Gateway returned invalid execution bounds.")
    return max(0.0, min(maximum, deadline - now))


def result_payload(task, output, duration, exit_code, executor):
    return {
        "task_id": task["task_id"], "lease_id": task.get("lease_id"),
        "output": output, "full_log": output, "exit_code": exit_code,
        "execution_time": duration, "source_hash": task.get("source_hash", task.get("code_sha256")),
        "output_hash": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "execution_mode": executor.backend, "isolation": executor.isolation,
    }


def execute_task(task, executor, state_root=STATE_ROOT, http=requests):
    """Stream bounded stdout while a separate monitor checks gateway cancellation.

    Deadline enforcement does not wait for an HTTP request or a line break.
    Docker tasks have no network, host credentials, writable image or Docker socket.
    """
    global current_status
    current_status = "ACTIVE (COMPUTING)"
    code = task["code"]
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    if code_hash != task.get("source_hash", task.get("code_sha256")):
        raise ValueError("Task source does not match the gateway's admitted source hash.")
    allowed_duration = task_runtime(task)
    if allowed_duration <= 0:
        current_status = "ONLINE (IDLE)"
        return result_payload(task, "[EXECUTION_DEADLINE_EXPIRED]\n", 0.0, 124, executor)

    staging = Path(state_root) / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    task_name = container_name(NODE_ID, task["task_id"])
    output = bytearray()
    output_lock = threading.Lock()
    stop_event = threading.Event()
    output_exceeded = threading.Event()
    cancellation = threading.Event()
    process = None
    started = time.perf_counter()
    reason = None
    forced_exit = None

    with tempfile.TemporaryDirectory(prefix="job-", dir=staging) as directory:
        task_directory = Path(directory)
        task_directory.chmod(0o755)
        source = task_directory / "payload.py"
        source.write_text(code, encoding="utf-8", newline="")
        source.chmod(0o444)
        try:
            process = executor.launch(task_directory, task_name)

            def read_output():
                try:
                    while True:
                        chunk = process.stdout.read(4096)
                        if not chunk:
                            break
                        with output_lock:
                            room = MAX_OUTPUT_BYTES - 256 - len(output)
                            output.extend(chunk[:max(0, room)])
                        if len(chunk) > room:
                            output_exceeded.set()
                            break
                finally:
                    process.stdout.close()

            def monitor():
                decoder = codecs.getincrementaldecoder("utf-8")("replace")
                sent = 0
                while not stop_event.wait(0.5):
                    try:
                        response = http.get(
                            f"{API_URL}/worker_task_status/{task['task_id']}",
                            headers=worker_headers(), timeout=1.5,
                        )
                        if response.status_code == 200:
                            status = response.json()
                            if status.get("cancelled") or status.get("terminal") or status.get("budget_exhausted"):
                                cancellation.set()
                                return
                            if task.get("lease_id") and status.get("lease_id", task["lease_id"]) != task["lease_id"]:
                                cancellation.set()
                                return
                        elif response.status_code in {401, 403, 404, 409}:
                            cancellation.set()
                            return
                    except requests.RequestException:
                        pass
                    with output_lock:
                        chunk = bytes(output[sent:])
                        sent = len(output)
                    if chunk:
                        try:
                            response = http.post(
                                f"{API_URL}/stream_log", headers=worker_headers(), timeout=1.5,
                                json={"task_id": task["task_id"], "node_id": NODE_ID,
                                      "lease_id": task.get("lease_id"), "lines": [decoder.decode(chunk)]},
                            )
                            if response.status_code in {401, 403, 404, 409}:
                                cancellation.set()
                                return
                        except requests.RequestException:
                            pass

            reader_thread = threading.Thread(target=read_output, daemon=True)
            monitor_thread = threading.Thread(target=monitor, daemon=True)
            reader_thread.start()
            monitor_thread.start()
            while process.poll() is None:
                elapsed = time.perf_counter() - started
                if output_exceeded.is_set():
                    reason, forced_exit = "[OUTPUT_LIMIT_EXCEEDED]", 137
                elif cancellation.is_set():
                    reason, forced_exit = "[EXECUTION_CANCELLED_BY_GATEWAY]", 130
                elif elapsed >= allowed_duration or time.time() >= float(task.get("execution_deadline", task.get("deadline_unix", math.inf))):
                    reason, forced_exit = "[EXECUTION_DEADLINE_EXCEEDED]", 124
                if reason:
                    executor.stop(process, task_name)
                    break
                time.sleep(0.02)
            process.wait(timeout=12)
            reader_thread.join(timeout=3)
            if output_exceeded.is_set() and not reason:
                reason, forced_exit = "[OUTPUT_LIMIT_EXCEEDED]", 137
        finally:
            stop_event.set()
            if process is not None and process.poll() is None:
                executor.stop(process, task_name)
                process.wait(timeout=12)
            current_status = "ONLINE (IDLE)"

    duration = min(float(task.get("max_runtime_seconds", MAX_RUNTIME_SECONDS)), round(time.perf_counter() - started, 4))
    with output_lock:
        full_output = bytes(output).decode("utf-8", errors="replace")
    full_output = full_output.encode("utf-8")[:MAX_OUTPUT_BYTES - 256].decode("utf-8", errors="ignore")
    if reason:
        full_output += f"\n{reason}\n"
    return result_payload(task, full_output, duration, forced_exit if forced_exit is not None else process.returncode, executor)


def recover_interrupted(journal, executor, identity=None):
    for task, started in journal.running():
        executor.recover(container_name(NODE_ID, task["task_id"]))
        duration = min(float(task.get("max_runtime_seconds", MAX_RUNTIME_SECONDS)), max(0, time.time() - started))
        payload = result_payload(
            task, "[WORKER_RESTARTED: execution interrupted; task was not re-executed]\n",
            round(duration, 4), 125, executor,
        )
        journal.finish(task["task_id"], identity.attest(task, payload, NODE_ID) if identity else payload)


def flush_results(journal, http=requests):
    global current_status
    for payload in journal.pending():
        current_status = "ACTIVE (SETTLEMENT PENDING)"
        try:
            response = http.post(f"{API_URL}/submit_result", json=payload, headers=worker_headers(), timeout=10)
            if response.status_code == 200:
                journal.acknowledge(payload["task_id"])
                print(f"[SETTLED] {payload['task_id']} ({payload['execution_time']}s)")
            else:
                journal.retry(payload["task_id"], f"gateway HTTP {response.status_code}")
        except requests.RequestException as exc:
            journal.retry(payload["task_id"], type(exc).__name__)
    if not journal.blocked():
        current_status = "ONLINE (IDLE)"


def main():
    global WORKER_IDENTITY
    if not worker_token_is_configured(WORKER_TOKEN):
        raise SystemExit("Set APERTURE_WORKER_TOKEN to a unique 16+ character secret; example values are rejected.")
    approved_sources = args.trusted_source_directory or os.getenv("APERTURE_TRUSTED_SOURCE_DIRECTORY")
    executor = TrustedLocalExecutor(Path(approved_sources) if approved_sources else None) if ALLOW_UNSAFE_LOCAL_EXECUTION else DockerSandbox(
        SANDBOX_IMAGE, STATE_ROOT, os.getenv("APERTURE_SANDBOX_HOST_ROOT"),
    )
    executor.preflight()
    instance_lock = WorkerInstanceLock(STATE_ROOT)
    journal = WorkerJournal(STATE_ROOT)
    WORKER_IDENTITY = WorkerIdentity(STATE_ROOT)
    stop_event = threading.Event()
    try:
        recover_interrupted(journal, executor, WORKER_IDENTITY)
        print(f"Aperture worker {NODE_ID} | {executor.backend} | gateway {API_URL}")
        if ALLOW_UNSAFE_LOCAL_EXECUTION:
            print("TRUSTED LOCAL DEVELOPMENT: Python executes on this host without a security sandbox.")
            if executor.approved_hashes is not None:
                print(f"Exact source approval: {len(executor.approved_hashes)} reviewed workloads; restart worker after reviewing changes.")
        threading.Thread(target=register_heartbeat, args=(stop_event, executor), daemon=True).start()
        while True:
            try:
                flush_results(journal)
                if journal.blocked():
                    stop_event.wait(1)
                    continue
                response = requests.get(f"{API_URL}/get_task", headers=worker_headers(), timeout=5)
                if response.status_code == 200:
                    task = response.json()
                    if task and task.get("task_id"):
                        if not task.get("source_hash", task.get("code_sha256")):
                            raise ValueError("Gateway is incompatible: admitted source hash is required.")
                        journal_task = {key: value for key, value in task.items() if key != "code"}
                        journal.begin(journal_task)
                        try:
                            payload = execute_task(task, executor)
                        except Exception as exc:
                            payload = result_payload(task, f"[EXECUTION_FAILED: {type(exc).__name__}]\n", 0.0, 125, executor)
                        journal.finish(task["task_id"], WORKER_IDENTITY.attest(task, payload, NODE_ID))
                        flush_results(journal)
            except requests.RequestException:
                pass
            except Exception as exc:
                print(f"[WORKER] {type(exc).__name__}: {exc}")
            stop_event.wait(1)
    except KeyboardInterrupt:
        print("Worker stopping; unresolved execution/results will recover from the journal.")
    finally:
        stop_event.set()
        journal.close()
        instance_lock.close()


if __name__ == "__main__":
    main()
