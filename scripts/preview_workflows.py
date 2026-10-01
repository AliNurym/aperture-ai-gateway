"""Launch a local off-chain preview restricted to reviewed compute templates.

Keeps the gateway and worker running for interactive use. This is trusted local
CPU execution, not Docker isolation or a Solana payment demonstration.
"""
import argparse
import importlib.util
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests
from solders.keypair import Keypair

ROOT = Path(__file__).resolve().parents[1]


def keep_children_in_launcher_job():
    """Windows closes this job with its launcher, including descendant processes."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                    ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                    ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("read_count", "write_count", "other_count", "read_bytes", "write_bytes", "other_bytes")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", IoCounters), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                    ("peak_job_memory", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(handle)
        raise error
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(handle)
        raise error
    # Do not close this handle while the launcher is alive: it also owns us.
    # The OS closes it on exit, stopping only this launcher's process tree.
    return handle


def wait_for_health(url, process, expected_key, *, ready=False):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("A preview service stopped. Inspect its log in the state directory.")
        try:
            response = requests.get(url + "/health", timeout=1)
            response.raise_for_status()
            health = response.json()
            if health.get("gateway_pubkey") != expected_key or health.get("demo_mode") is not True:
                raise RuntimeError("The listening gateway differs from this off-chain preview.")
            if not ready or health.get("status") == "ready":
                return health
        except (requests.RequestException, ValueError):
            pass
        time.sleep(0.2)
    raise TimeoutError("Preview " + ("worker did not register" if ready else "gateway did not start"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", type=Path, default=ROOT / ".aperture" / "preview" / "tasks.sqlite3")
    parser.add_argument("--state-directory", type=Path, default=ROOT / ".aperture" / "preview")
    parser.add_argument("--frontend", action="store_true", help="Start the console with this gateway's public identity pins")
    parser.add_argument("--frontend-port", type=int, default=3000)
    parser.add_argument("--temporary-key", action="store_true", help="Offer a memory-only development wallet in the console")
    parser.add_argument("--supervise", action="store_true", help="Keep the launcher open; Ctrl+C stops its services")
    args = parser.parse_args()
    if args.temporary_key and not args.frontend:
        parser.error("--temporary-key requires --frontend")
    ports = [args.port, *([args.frontend_port] if args.frontend else [])]
    if len(set(ports)) != len(ports) or any(not 1 <= port <= 65535 for port in ports):
        parser.error("Choose distinct gateway and frontend ports from 1 to 65535")
    for port in ports:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                raise RuntimeError(f"Port {port} is already in use. Continue in the existing workspace, stop its launcher, or choose a different port.") from error
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is unavailable. Use start_preview.bat or add Node.js to PATH.")
    if args.frontend and not (ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js").is_file():
        raise RuntimeError("Frontend dependencies are missing. Use start_preview.bat to prepare them.")
    state = args.state_directory.resolve()
    manifest_path = state / "processes.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("database") != str(args.database.resolve()):
            raise RuntimeError("This state directory belongs to another database. Preserve it and select a separate --state-directory.")
    approved = state / ("approved-" + secrets.token_hex(8))
    approved.mkdir(parents=True, exist_ok=True)
    args.database.resolve().parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    source = subprocess.check_output([node, "--input-type=module", "-e",
        "import {WORKLOADS} from './src/utils/workloads.js'; import {MERGE_SOURCE} from './src/utils/workflowSources.js'; console.log(JSON.stringify([...WORKLOADS.map(item=>({id:item.id,code:item.code})),{id:'workflow-report',code:MERGE_SOURCE}]));"],
        cwd=ROOT / "frontend", text=True, encoding="utf-8", creationflags=flags)
    for item in json.loads(source):
        (approved / (item["id"] + ".py")).write_text(item["code"], encoding="utf-8", newline="")
    spec = importlib.util.spec_from_file_location("batch_pipeline", ROOT / "examples" / "batch_data_workflow.py")
    pipeline = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "sdk" / "python"))
    spec.loader.exec_module(pipeline)
    for name, code in (("batch", pipeline.BATCH_SOURCE), ("merge", pipeline.MERGE_SOURCE)):
        (approved / (name + ".py")).write_text(code, encoding="utf-8", newline="")
    worker_secret = secrets.token_urlsafe(40)
    oracle_path = state / "oracle.json"
    if oracle_path.exists():
        oracle = Keypair.from_bytes(bytes(json.loads(oracle_path.read_text(encoding="utf-8"))))
    else:
        oracle = Keypair()
        oracle_path.write_text(json.dumps(list(bytes(oracle))), encoding="utf-8")
        oracle_path.chmod(0o600)
    environment = {**os.environ, "APERTURE_ENV": "development", "APERTURE_DEMO_MODE": "true",
        "APERTURE_STATE_DB": str(args.database.resolve()), "APERTURE_WORKER_CREDENTIALS": "",
        "APERTURE_OBJECT_STORE": str(args.database.resolve().with_name(args.database.stem + "-objects")),
        "BACKEND_PRIVATE_KEY": json.dumps(list(bytes(oracle))), "APERTURE_WORKER_TOKEN": worker_secret,
        "APERTURE_NODE_ID": "NODE-INTERACTIVE-PREVIEW", "GATEWAY_API_URL": f"http://127.0.0.1:{args.port}",
        "CORS_ORIGINS": f"http://127.0.0.1:{args.frontend_port},http://localhost:{args.frontend_port}",
        "APERTURE_TRUSTED_SOURCE_DIRECTORY": str(approved), "APERTURE_ALLOW_UNSAFE_LOCAL_EXECUTION": "true",
        "APERTURE_WORKER_STATE_DIR": str(state / "worker"), "PYTHONIOENCODING": "utf-8"}
    processes = []
    launcher_job = keep_children_in_launcher_job() if args.supervise else None
    try:
        with (state / "gateway.log").open("a", encoding="utf-8") as log:
            processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                "--port", str(args.port)], cwd=ROOT / "backend", env=environment, stdout=log,
                stderr=subprocess.STDOUT, creationflags=flags))
        health = wait_for_health(environment["GATEWAY_API_URL"], processes[0], str(oracle.pubkey()))
        with (state / "worker.log").open("a", encoding="utf-8") as log:
            processes.append(subprocess.Popen([sys.executable, "worker.py"], cwd=ROOT / "backend", env=environment,
                stdout=log, stderr=subprocess.STDOUT, creationflags=flags))
        health = wait_for_health(environment["GATEWAY_API_URL"], processes[1], str(oracle.pubkey()), ready=True)
        summary = {"gateway_pid": processes[0].pid, "worker_pid": processes[1].pid,
            "gateway_url": environment["GATEWAY_API_URL"], "execution": "reviewed_trusted_local",
            "gateway_pubkey": str(oracle.pubkey()), "program_id": health["program_id"],
            "settlement": "OFF_CHAIN", "database": str(args.database.resolve()), "logs": str(state)}
        if args.frontend:
            frontend_environment = {**environment, "VITE_API_URL": environment["GATEWAY_API_URL"],
                "VITE_APERTURE_GATEWAY_PUBKEY": str(oracle.pubkey()), "VITE_APERTURE_PROGRAM_ID": health["program_id"],
                "VITE_APERTURE_TREASURY_PUBKEY": "", "VITE_ENABLE_SESSION_KEY": "true" if args.temporary_key else "false"}
            with (state / "frontend.log").open("a", encoding="utf-8") as log:
                processes.append(subprocess.Popen([node, "scripts/vite.mjs", "--host", "127.0.0.1", "--port",
                    str(args.frontend_port), "--strictPort"], cwd=ROOT / "frontend", env=frontend_environment,
                    stdout=log, stderr=subprocess.STDOUT, creationflags=flags))
            frontend_url = f"http://127.0.0.1:{args.frontend_port}"
            for _ in range(100):
                if processes[2].poll() is not None:
                    raise RuntimeError("Preview frontend stopped. Inspect " + str(state / "frontend.log"))
                try:
                    if requests.get(frontend_url, timeout=1).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(0.2)
            else:
                raise TimeoutError("Preview frontend did not start")
            summary.update(frontend_pid=processes[2].pid, frontend_url=frontend_url, temporary_key=args.temporary_key)
        summary.update(launcher_pid=os.getpid() if args.supervise else None, supervised=args.supervise)
        manifest_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        if not args.supervise:
            return
        print("\nWorkspace ready. Keep this launcher open; Ctrl+C stops its services.\nReviewed local CPU execution · OFF_CHAIN · no Solana payment.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("A preview service stopped. See the logs; restart this launcher to recover saved tasks.")
    except KeyboardInterrupt:
        print("\nStopping preview services. Saved tasks, files and keys are retained.", flush=True)
    except BaseException:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
        raise
    finally:
        if args.supervise:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            # Keep the job handle alive until OS process cleanup.
            _ = launcher_job


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, TimeoutError, OSError) as error:
        print("Aperture preview: " + str(error), file=sys.stderr)
        raise SystemExit(1) from None
