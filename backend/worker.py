"""Authenticated worker coordinator with isolated jobs and a durable result outbox."""

from __future__ import annotations

import argparse
import codecs
from contextlib import contextmanager
import hashlib
import ipaddress
import math
import os
import platform
import socket
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

from worker_journal import WorkerInstanceLock, WorkerJournal, container_name
from worker_identity import WorkerIdentity
from worker_sandbox import DockerSandbox, MAX_OUTPUT_BYTES, MAX_RUNTIME_SECONDS, TrustedLocalExecutor
from worker_data import ResultFrames, prepare_job, publish_artifacts
from security_config import worker_id_is_valid, worker_token_is_configured


load_dotenv(Path(__file__).with_name(".worker.env"))
parser = argparse.ArgumentParser(description="Aperture authenticated compute worker")
parser.add_argument("--node-id", default=None)
parser.add_argument("--gateway", default=None, help="Gateway URL; defaults to GATEWAY_API_URL")
parser.add_argument("--token", default=None, help="Prefer APERTURE_WORKER_TOKEN in the environment")
parser.add_argument("--allow-unsafe-local-execution", action="store_true", help="Execute trusted development workloads directly on the host")
parser.add_argument("--trusted-source-directory", type=Path, default=None, help="Limit trusted local execution to exact UTF-8 .py files reviewed before startup")
args, _ = parser.parse_known_args()
API_URL = (args.gateway or os.getenv("GATEWAY_API_URL") or "http://127.0.0.1:8000").rstrip("/")
NODE_ID = args.node_id or os.getenv("APERTURE_NODE_ID") or f"NODE-CPU-{socket.gethostname()}"
WORKER_TOKEN = (args.token or os.getenv("APERTURE_WORKER_TOKEN", "")).strip()
ALLOW_UNSAFE_LOCAL_EXECUTION = args.allow_unsafe_local_execution or os.getenv("APERTURE_ALLOW_UNSAFE_LOCAL_EXECUTION", "false").lower() == "true"
STATE_ROOT = Path(os.getenv("APERTURE_WORKER_STATE_DIR", str(Path.home() / ".aperture-worker" / hashlib.sha256(NODE_ID.encode()).hexdigest()[:16])))
SANDBOX_IMAGE = os.getenv("APERTURE_SANDBOX_IMAGE", "aperture-task:local")
current_status = "ONLINE (IDLE)"
WORKER_IDENTITY = None
last_auth_warning_at = 0.0
registration_ready = threading.Event()


def worker_headers():
    return {"X-Aperture-Worker-Token": WORKER_TOKEN, "X-Aperture-Worker-Id": NODE_ID}


def report_auth_rejection(operation, status_code):
    global last_auth_warning_at
    if status_code not in {400, 401, 403, 409, 422, 503}:
        return
    now = time.monotonic()
    if now - last_auth_warning_at < 30:
        return
    print(
        f"[WORKER] Gateway rejected {NODE_ID} during {operation} (HTTP {status_code}); "
        "check the worker ID, its configured token, and its persisted signing key.",
        flush=True,
    )
    last_auth_warning_at = now


def gateway_url_uses_secure_transport(url):
    """Require TLS for remote gateways; allow loopback and Compose service traffic."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        parsed.port  # Validate malformed ports before starting the worker.
    except (AttributeError, ValueError):
        return False
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    if parsed.scheme.lower() == "https":
        return True
    if parsed.scheme.lower() != "http":
        return False
    host = host.rstrip(".").lower()
    if host == "localhost":
        return True
    if host == "gateway":
        return os.getenv("APERTURE_ALLOW_INSECURE_COMPOSE_GATEWAY", "false").lower() == "true"
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def detect_hardware():
    # Task images expose CPU only. A GPU on the coordinator does not mean jobs
    # have access to it, so the advertised execution capability stays honest.
    return f"CPU worker ({platform.processor() or platform.machine()})", 0.0, 0.0


GPU_NAME, VRAM_TOTAL, TFLOPS = detect_hardware()


def register_heartbeat(stop_event, executor=None):
    while not stop_event.is_set():
        try:
            response = requests.post(f"{API_URL}/register_node", json={
                "node_id": NODE_ID, "gpu_name": GPU_NAME, "vram_total": 0.0,
                "vram_used": None, "gpu_temp": None, "gpu_util": None,
                "power_watts": None, "tflops": 0.0, "status": current_status,
                "worker_pubkey": WORKER_IDENTITY.pubkey if WORKER_IDENTITY else None,
                "execution_mode": "trusted_local" if ALLOW_UNSAFE_LOCAL_EXECUTION else "docker",
                "source_policy": "exact_hash_allowlist" if ALLOW_UNSAFE_LOCAL_EXECUTION and executor and executor.approved_hashes is not None else "operator_trusted" if ALLOW_UNSAFE_LOCAL_EXECUTION else "gateway_ast",
                "approved_source_count": len(executor.approved_hashes) if ALLOW_UNSAFE_LOCAL_EXECUTION and executor and executor.approved_hashes is not None else None,
            }, headers=worker_headers(), timeout=4, allow_redirects=False)
            if response.status_code == 200:
                registration_ready.set()
            else:
                registration_ready.clear()
                report_auth_rejection("registration", response.status_code)
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
        **({"workload_sha256": task["workload_sha256"], "artifacts": []} if "workload" in task else {}),
    }


@contextmanager
def task_staging_directory(staging):
    directory = tempfile.TemporaryDirectory(prefix="job-", dir=staging)
    path = Path(directory.name).resolve()
    path.relative_to(staging.resolve())
    try:
        yield path
    finally:
        # Windows may briefly retain a working-directory handle after process exit.
        # Retry only this worker-created directory, without ignoring failed cleanup.
        for attempt in range(6):
            try:
                directory.cleanup()
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.02 * 2 ** min(attempt, 3))


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
    reason = None
    forced_exit = None
    frames = None

    with task_staging_directory(staging) as directory:
        task_directory = Path(directory)
        task_directory.chmod(0o755)
        source = task_directory / "payload.py"
        source.write_text(code, encoding="utf-8", newline="")
        source.chmod(0o444)
        try:
            if "workload" in task:
                prepare_job(task, task_directory, http=http, api_url=API_URL, headers=worker_headers())
            allowed_duration = task_runtime(task)
            if allowed_duration <= 0:
                current_status = "ONLINE (IDLE)"
                return result_payload(task, "[EXECUTION_DEADLINE_EXPIRED]\n", 0.0, 124, executor)
            started = time.perf_counter()
            process = executor.launch(task_directory, task_name)

            def append_log(chunk):
                with output_lock:
                    room = MAX_OUTPUT_BYTES - 256 - len(output)
                    output.extend(chunk[:max(0, room)])
                if len(chunk) > room:
                    raise ValueError("Job log limit exceeded.")

            frames = ResultFrames(append_log) if "workload" in task else None

            def read_output():
                try:
                    while True:
                        chunk = process.stdout.read(4096)
                        if not chunk:
                            break
                        if frames:
                            frames.feed(chunk)
                        else:
                            append_log(chunk)
                    if frames:
                        frames.finish()
                except (ValueError, KeyError, TypeError):
                    output_exceeded.set()
                finally:
                    process.stdout.close()

            def monitor():
                decoder = codecs.getincrementaldecoder("utf-8")("replace")
                sent = 0
                while not stop_event.wait(0.5):
                    try:
                        response = http.get(
                            f"{API_URL}/worker_task_status/{task['task_id']}",
                            headers=worker_headers(), timeout=1.5, allow_redirects=False,
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
                                f"{API_URL}/stream_log", headers=worker_headers(), timeout=1.5, allow_redirects=False,
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

    duration = min(allowed_duration, round(time.perf_counter() - started, 4))
    with output_lock:
        full_output = bytes(output).decode("utf-8", errors="replace")
    full_output = full_output.encode("utf-8")[:MAX_OUTPUT_BYTES - 256].decode("utf-8", errors="ignore")
    if reason:
        full_output += f"\n{reason}\n"
    payload = result_payload(task, full_output, duration, forced_exit if forced_exit is not None else process.returncode, executor)
    if frames:
        payload["_artifact_blobs"] = frames.artifacts
    return payload


def recover_interrupted(journal, executor, identity=None):
    for task, started in journal.running():
        executor.recover(container_name(NODE_ID, task["task_id"]))
        allowed_duration = task_runtime(task, now=started)
        duration = min(allowed_duration, max(0, time.time() - started))
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
            if "_artifact_blobs" in payload:
                task = journal.task(payload["task_id"])
                try:
                    artifacts = publish_artifacts(task, payload, http=http, api_url=API_URL, headers=worker_headers())
                except requests.HTTPError as error:
                    if error.response is None or error.response.status_code != 409:
                        raise
                    status = http.get(f"{API_URL}/worker_task_status/{task['task_id']}",
                        headers=worker_headers(), timeout=5, allow_redirects=False)
                    status.raise_for_status()
                    if not (status.json().get("cancelled") or status.json().get("terminal")):
                        raise
                    # A concluded lease can acknowledge its outbox without publishing
                    # discarded files. The gateway keeps the original terminal result.
                    artifacts = []
                payload = {key: value for key, value in payload.items() if key != "_artifact_blobs"}
                payload["artifacts"] = artifacts
                payload = WORKER_IDENTITY.attest(task, payload, NODE_ID)
                journal.finish(payload["task_id"], payload)
            response = http.post(f"{API_URL}/submit_result", json=payload, headers=worker_headers(), timeout=10, allow_redirects=False)
            if response.status_code == 200:
                journal.acknowledge(payload["task_id"])
                print(f"[SETTLED] {payload['task_id']} ({payload['execution_time']}s)")
            else:
                report_auth_rejection("result submission", response.status_code)
                journal.retry(payload["task_id"], f"gateway HTTP {response.status_code}")
        except requests.RequestException as exc:
            journal.retry(payload["task_id"], type(exc).__name__)
    if not journal.blocked():
        current_status = "ONLINE (IDLE)"


def main():
    global WORKER_IDENTITY
    if not gateway_url_uses_secure_transport(API_URL):
        raise SystemExit("Remote GATEWAY_API_URL must use HTTPS. Plain HTTP is allowed only for loopback or the Docker Compose 'gateway' service.")
    deployment_environment = (os.getenv("APERTURE_ENV") or "development").strip().lower()
    if deployment_environment not in {"development", "test", "staging", "production"}:
        raise SystemExit("APERTURE_ENV must be development, test, staging, or production.")
    if ALLOW_UNSAFE_LOCAL_EXECUTION and deployment_environment in {"staging", "production"}:
        raise SystemExit("Unsafe host execution is disabled in staging and production; use the per-task Docker sandbox.")
    if not worker_id_is_valid(NODE_ID):
        raise SystemExit("APERTURE_NODE_ID must be 1 to 64 visible ASCII characters without surrounding spaces.")
    if not worker_token_is_configured(WORKER_TOKEN):
        raise SystemExit("Set APERTURE_WORKER_TOKEN in backend/.worker.env (or the worker environment) to a unique 16+ character secret; example values are rejected.")
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
        registration_ready.clear()
        threading.Thread(target=register_heartbeat, args=(stop_event, executor), daemon=True).start()
        while True:
            try:
                if not registration_ready.is_set():
                    stop_event.wait(1)
                    continue
                flush_results(journal)
                if journal.blocked():
                    stop_event.wait(1)
                    continue
                response = requests.get(f"{API_URL}/get_task", headers=worker_headers(), timeout=(5, 30), allow_redirects=False)
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
                else:
                    report_auth_rejection("task polling", response.status_code)
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
