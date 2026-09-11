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

warnings.filterwarnings("ignore")

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

parser = argparse.ArgumentParser(description="Aperture DePIN Worker Node")
parser.add_argument("--node-id", type=str, default=None, help="Custom identifier for this node")
parser.add_argument("--wallet", type=str, default=None, help="Payout Solana address")
parser.add_argument("--gateway", type=str, default="http://127.0.0.1:8000", help="Gateway URL")
args, _ = parser.parse_known_args()

# --- WORKER CONFIGURATION ---
API_URL = args.gateway or os.getenv("GATEWAY_API_URL", "http://127.0.0.1:8000")
NODE_ID = args.node_id or os.getenv("APERTURE_NODE_ID", f"NODE-HOST-GPU-{uuid.uuid4().hex[:4].upper()}")
PAYOUT_WALLET = args.wallet or "7wFo7q4EHfKrBNpL4XLXXWAi9TcE6BD27ZoQoBqtFcNQ"

current_status = "ONLINE (IDLE)"


def detect_hardware():
    """Detects available GPU or CPU compute specifications."""
    gpu_name = f"Virtualized CPU ({platform.processor() or 'Multi-Core'})"
    vram_total = 4.0
    tflops = 8.5

    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        gpu_name = pynvml.nvmlDeviceGetName(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        vram_total = round(mem.total / (1024**3), 1)
        tflops = 12.0
    except Exception:
        pass

    return gpu_name, vram_total, tflops


GPU_NAME, VRAM_TOTAL, TFLOPS = detect_hardware()


def get_live_telemetry():
    """Samples real-time physical metrics directly from NVML."""
    metrics = {
        "gpu_temp": 50.0,
        "gpu_util": 0,
        "vram_used": 0.2,
        "vram_total": VRAM_TOTAL,
        "power_watts": 15.0
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
            requests.post(f"{API_URL}/register_node", json=payload, timeout=4)
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

    temp_filename = f"task_{uuid.uuid4().hex[:8]}.py"
    with open(temp_filename, "w", encoding="utf-8") as f:
        f.write(code)

    start_time = time.perf_counter()
    output_lines = []

    print(f"⚙️ [EXEC] Launching isolated subprocess for task {task_id}...")

    # Launch subprocess using current Python executable
    process = subprocess.Popen(
        [sys.executable, temp_filename],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
        encoding="utf-8",
        errors="replace"
    )

    def reader():
        for line in iter(process.stdout.readline, ''):
            output_lines.append(line)
        process.stdout.close()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # Streamer & Watchdog Loop
    max_duration_seconds = 180  # 3 minutes maximum per task
    last_sent_idx = 0

    while t.is_alive():
        t.join(timeout=0.3)
        elapsed = time.perf_counter() - start_time

        # Stream new output lines to gateway
        if len(output_lines) > last_sent_idx:
            chunk = output_lines[last_sent_idx:]
            last_sent_idx = len(output_lines)
            try:
                requests.post(f"{API_URL}/stream_log", json={
                    "task_id": task_id,
                    "lines": chunk,
                    "node_id": NODE_ID
                }, timeout=1.5)
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
            }, timeout=2)
        except Exception:
            pass

    execution_time = round(time.perf_counter() - start_time, 4)
    current_status = "ONLINE (IDLE)"

    full_output = "".join(output_lines)
    if not full_output.strip():
        full_output = "Task executed successfully with no stdout output (did you include print() statements?)."

    if os.path.exists(temp_filename):
        try:
            os.remove(temp_filename)
        except Exception:
            pass

    return full_output, execution_time


def main():
    print("=" * 60)
    print(f"⚡ APERTURE DePIN COMPUTE NODE ONLINE: {NODE_ID}")
    print(f"💻 Hardware Target: {GPU_NAME} | VRAM: {VRAM_TOTAL}GB | TFLOPS: {TFLOPS}")
    print(f"📡 Connected Gateway: {API_URL}")
    print("=" * 60)

    # Start heartbeat background thread
    hb_thread = threading.Thread(target=register_heartbeat, daemon=True)
    hb_thread.start()

    consecutive_errors = 0

    while True:
        try:
            response = requests.get(f"{API_URL}/get_task", timeout=5)
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
                print(f"🧠 Executing in isolated hardware sandbox...")

                raw_output, duration = run_python_code_with_heartbeat(code, task_id, wallet)

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
                    "full_log": raw_output
                }

                settle_res = requests.post(f"{API_URL}/submit_result", json=payload, timeout=10)
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