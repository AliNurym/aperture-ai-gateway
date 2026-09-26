import os
import sys
import time
import uuid
import subprocess
import threading
import platform
import argparse
import warnings
import requests
import tempfile
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

parser = argparse.ArgumentParser(description="Aperture DePIN Worker Node")
parser.add_argument("--node-id", type=str, default=None, help="Custom identifier for this node")
parser.add_argument("--wallet", type=str, default=None, help="Payout Solana address")
parser.add_argument("--gateway", type=str, default="http://127.0.0.1:8000", help="Gateway URL")
parser.add_argument("--token", type=str, default=None, help="Shared gateway worker token")
parser.add_argument("--allow-unsafe-local-execution", action="store_true", help="Allow direct host execution for local development only")
args, _ = parser.parse_known_args()

# --- WORKER CONFIGURATION ---
API_URL = args.gateway or os.getenv("GATEWAY_API_URL", "http://127.0.0.1:8000")
NODE_ID = args.node_id or os.getenv("APERTURE_NODE_ID", f"NODE-HOST-GPU-{uuid.uuid4().hex[:4].upper()}")
PAYOUT_WALLET = args.wallet or "7wFo7q4EHfKrBNpL4XLXXWAi9TcE6BD27ZoQoBqtFcNQ"
WORKER_TOKEN = args.token or os.getenv("APERTURE_WORKER_TOKEN", "")
ALLOW_UNSAFE_LOCAL_EXECUTION = args.allow_unsafe_local_execution or os.getenv("APERTURE_ALLOW_UNSAFE_LOCAL_EXECUTION", "false").lower() == "true"


def worker_token_is_configured(token: str) -> bool:
    normalized = (token or "").strip().lower()
    return len(token or "") >= 16 and normalized not in {
        "replace-with-a-long-random-secret",
        "change-me",
        "example-token",
    }

current_status = "ONLINE (IDLE)"
MAX_OUTPUT_BYTES = 1_000_000
MAX_MEMORY_BYTES = 512 * 1024 * 1024


def worker_headers():
    return {
        "X-Aperture-Worker-Token": WORKER_TOKEN,
        "X-Aperture-Worker-Id": NODE_ID,
    }


def execution_limits():
    """Best-effort Unix resource limits; production should use a sandboxed container."""
    if os.name != "posix":
        return None
    import resource

    def apply():
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (180, 180))

    return apply


def detect_hardware():
    """Report detected hardware; unavailable metrics remain unavailable."""
    gpu_name = f"CPU worker ({platform.processor() or 'processor details unavailable'})"
    vram_total = 0.0
    tflops = 0.0

    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        gpu_name = pynvml.nvmlDeviceGetName(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        vram_total = round(mem.total / (1024**3), 1)
    except Exception:
        pass

    return gpu_name, vram_total, tflops


GPU_NAME, VRAM_TOTAL, TFLOPS = detect_hardware()


def get_live_telemetry():
    """Samples real-time physical metrics directly from NVML."""
    metrics = {
        "gpu_temp": None,
        "gpu_util": None,
        "vram_used": None,
        "vram_total": VRAM_TOTAL,
        "power_watts": None
    }
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        metrics["gpu_temp"] = float(temp)
        metrics["gpu_util"] = int(util.gpu)
        metrics["vram_used"] = round(mem.used / (1024**3), 2)
        metrics["vram_total"] = round(mem.total / (1024**3), 2)
        try:
            power = pynvml.nvmlDeviceGetPowerUsage(handle)
            metrics["power_watts"] = round(power / 1000.0, 1)
        except Exception:
            pass
    except Exception:
        pass
    return metrics


def register_heartbeat():
    """Background thread to announce node availability and live telemetry to the Gateway."""
    while True:
        try:
            telemetry = get_live_telemetry()
            payload = {
                "node_id": NODE_ID,
                "gpu_name": GPU_NAME,
                "vram_total": telemetry["vram_total"],
                "vram_used": telemetry["vram_used"],
                "gpu_temp": telemetry["gpu_temp"],
                "gpu_util": telemetry["gpu_util"],
                "power_watts": telemetry["power_watts"],
                "tflops": TFLOPS,
                "status": current_status
            }
            requests.post(f"{API_URL}/register_node", json=payload, headers=worker_headers(), timeout=4)
        except Exception:
            pass
        time.sleep(5)


def run_python_code_with_heartbeat(code: str, task_id: str, wallet: str = None):
    """
    Executes Python payload in an isolated subprocess, streaming real-time stdout
    chunks to the gateway and enforcing runtime gas checks and execution timeouts.
    """
    global current_status
    current_status = "ACTIVE (COMPUTING)"

    task_dir = tempfile.TemporaryDirectory(prefix="aperture-task-")
    temp_filename = os.path.join(task_dir.name, "payload.py")
    with open(temp_filename, "w", encoding="utf-8") as f:
        f.write(code)

    start_time = time.perf_counter()
    output_lines = []

    print(f"⚙️ [EXEC] Launching isolated subprocess for task {task_id}...")

    # Isolated interpreter, ephemeral task directory, stripped secret-bearing environment.
    safe_env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC") if key in os.environ}
    safe_env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        [sys.executable, "-I", temp_filename],
        cwd=task_dir.name,
        env=safe_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
        encoding="utf-8",
        errors="replace",
        preexec_fn=execution_limits(),
    )

    def reader():
        output_bytes = 0
        for line in iter(process.stdout.readline, ''):
            output_bytes += len(line.encode("utf-8", errors="replace"))
            output_lines.append(line)
            if output_bytes > MAX_OUTPUT_BYTES:
                output_lines.append("\n[OUTPUT LIMIT EXCEEDED: process terminated]\n")
                process.kill()
                break
        process.stdout.close()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # Streamer & Watchdog Loop
    max_duration_seconds = 180  # 3 minutes maximum per task
    last_sent_idx = 0
    last_cancellation_check = 0.0

    while t.is_alive() or process.poll() is None:
        t.join(timeout=0.3)
        elapsed = time.perf_counter() - start_time

        # Resetting the billing rate must also stop the local process; poll
        # the gateway under the worker's lease before charging more compute.
        if elapsed - last_cancellation_check >= 1.0:
            last_cancellation_check = elapsed
            try:
                status = requests.get(f"{API_URL}/worker_task_status/{task_id}", headers=worker_headers(), timeout=1.5)
                if status.status_code == 200 and status.json().get("cancelled"):
                    process.kill()
                    output_lines.append("\n[EXECUTION_CANCELLED_BY_SUBMITTER]\n")
                    break
            except Exception:
                # A transient gateway failure is not authorization to change
                # task state; the existing hard timeout still bounds runtime.
                pass

        # Stream new output lines to gateway
        if len(output_lines) > last_sent_idx:
            chunk = output_lines[last_sent_idx:]
            last_sent_idx = len(output_lines)
            try:
                streamed = requests.post(f"{API_URL}/stream_log", json={
                    "task_id": task_id,
                    "lines": chunk,
                    "node_id": NODE_ID
                }, headers=worker_headers(), timeout=1.5)
                if streamed.status_code == 409:
                    process.kill()
                    output_lines.append("\n[EXECUTION_CANCELLED_BY_SUBMITTER]\n")
                    break
            except Exception:
                pass

        # Check gas tank if wallet is known
        if wallet and elapsed > 5.0 and int(elapsed) % 6 == 0:
            try:
                res = requests.get(f"{API_URL}/balance/{wallet}", timeout=3)
                if res.status_code == 200:
                    balance = res.json().get("balance", 0.0)
                    if balance < 0.0001:
                        print(f"🚨 [GAS WATCHDOG] Task {task_id} terminated: Payment channel depleted.")
                        process.kill()
                        output_lines.append("\n\n🚨 [APERTURE SENTINEL ALERT]: Task halted - Payment channel gas depleted (< 0.0001 SOL).")
                        break
            except Exception:
                pass

        # Timeout limit
        if elapsed > max_duration_seconds:
            print(f"🚨 [WATCHDOG] Task {task_id} exceeded maximum runtime limit ({max_duration_seconds}s). Terminating.")
            process.kill()
            output_lines.append(f"\n\n🚨 [TIMEOUT EXCEEDED]: Execution surpassed max limit of {max_duration_seconds} seconds.")
            break

    # Send any remaining lines
    if len(output_lines) > last_sent_idx:
        chunk = output_lines[last_sent_idx:]
        try:
            requests.post(f"{API_URL}/stream_log", json={
                "task_id": task_id,
                "lines": chunk,
                "node_id": NODE_ID
            }, headers=worker_headers(), timeout=2)
        except Exception:
            pass

    # Reap before cleaning its working directory, particularly on Windows.
    process.wait(timeout=5)
    t.join(timeout=2)
    execution_time = min(180.0, round(time.perf_counter() - start_time, 4))
    current_status = "ONLINE (IDLE)"

    full_output = "".join(output_lines)
    if not full_output.strip() and process.returncode == 0:
        full_output = "Task executed successfully with no stdout output (did you include print() statements?)."

    task_dir.cleanup()

    return full_output, execution_time, process.returncode


def main():
    print("=" * 60)
    print(f"⚡ APERTURE DePIN COMPUTE NODE ONLINE: {NODE_ID}")
    vram_display = f"{VRAM_TOTAL} GB VRAM" if VRAM_TOTAL > 0 else "VRAM unavailable"
    print(f"💻 Detected hardware: {GPU_NAME} | {vram_display}")
    print(f"📡 Connected Gateway: {API_URL}")
    if not worker_token_is_configured(WORKER_TOKEN):
        raise SystemExit("Set APERTURE_WORKER_TOKEN to a unique 16+ character secret; example values are rejected.")
    if not ALLOW_UNSAFE_LOCAL_EXECUTION:
        raise SystemExit("Direct host execution is disabled. Use a containerized worker, or pass --allow-unsafe-local-execution for local development only.")
    print("=" * 60)

    # Start heartbeat background thread
    hb_thread = threading.Thread(target=register_heartbeat, daemon=True)
    hb_thread.start()

    consecutive_errors = 0

    while True:
        try:
            response = requests.get(f"{API_URL}/get_task", headers=worker_headers(), timeout=5)
            if response.status_code != 200:
                consecutive_errors += 1
                if consecutive_errors % 10 == 1:
                    print(f"⚠️ Gateway unreachable (HTTP {response.status_code}). Retrying...")
                time.sleep(3)
                continue

            consecutive_errors = 0
            task = response.json()

            if task and task.get("task_id"):
                task_id = task["task_id"]
                code = task["code"]
                wallet = task.get("wallet")

                print("\n" + "-" * 50)
                print(f"📦 [PAYLOAD RECEIVED] Task ID: {task_id}")
                print(f"👤 Submitter: {wallet[:12] if wallet else 'Anonymous'}...")
                print("Executing on the local development host...")

                raw_output, duration, exit_code = run_python_code_with_heartbeat(code, task_id, wallet)

                # Format output for frontend terminal display
                lines = raw_output.splitlines()
                display_output = raw_output
                if len(lines) > 25:
                    display_output = "\n".join(lines[:20])
                    display_output += f"\n\n[📊] OUTPUT TRUNCATED ({len(lines)} total lines). Full log archived."

                # Send result back to Gateway
                payload = {
                    "task_id": task_id,
                    "output": display_output,
                    "execution_time": duration,
                    "full_log": raw_output,
                    "exit_code": exit_code,
                }

                settle_res = requests.post(f"{API_URL}/submit_result", json=payload, headers=worker_headers(), timeout=10)
                if settle_res.status_code == 200:
                    data = settle_res.json()
                    print(f"✅ [TASK SETTLED] Task: {task_id} | Time: {duration}s | Cost: {data.get('cost_sol', 0)} SOL")
                    if data.get("receipt_signature"):
                        print(f"📜 [RECEIPT] Proof Signature: {data.get('receipt_signature')[:24]}...")
                else:
                    print(f"❌ [SETTLEMENT FAILED]: {settle_res.text}")

        except requests.exceptions.ConnectionError:
            time.sleep(3)
        except Exception as e:
            print(f"🚨 Worker Loop Note: {e}")
            time.sleep(2)

        time.sleep(1)


if __name__ == "__main__":
    main()
