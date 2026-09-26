"""Aperture gateway: bounded execution, KYA delegation, durable receipts."""
import os
import time
from contextlib import asynccontextmanager
from typing import Optional
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from ai_engine import analyze_code_ast, get_sol_price_from_pyth
from solana_client import KEYPAIR_PATH, SolanaClient
from gateway import Gateway

load_dotenv()
APP_ENV = os.getenv("APERTURE_ENV", "development").lower()
DEMO_MODE = os.getenv("APERTURE_DEMO_MODE", "false").lower() == "true"
WORKER_TOKEN = os.getenv("APERTURE_WORKER_TOKEN", "")
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if origin.strip()]
solana_client = SolanaClient()
gateway = Gateway(solana_client, DEMO_MODE, WORKER_TOKEN)
require_worker = gateway.require_worker
nodes = {}
request_rate_buckets = {}
grid_stats = {"tasks_completed": 0, "total_compute_seconds": 0.0, "total_sol_burned": 0.0, "threats_blocked": 0, "start_time": time.time()}

def worker_token_is_configured(token):
    return len(token or "") >= 16 and (token or "").strip().lower() not in {"replace-with-a-long-random-secret", "change-me", "example-token"}

def enforce_rate_limit(scope, client_id, limit):
    now = time.time()
    key = f"{scope}:{client_id}"
    recent = [item for item in request_rate_buckets.get(key, []) if now - item < 60]
    if len(recent) >= limit:
        raise HTTPException(429, "Rate limit exceeded. Retry shortly.")
    request_rate_buckets[key] = recent + [now]

@asynccontextmanager
async def lifespan(app):
    await gateway.start()
    yield
    await gateway.close()
    await solana_client.close()

app = FastAPI(title="Aperture Compute Gateway", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def security_and_admission(request, call_next):
    if request.method == "POST" and request.url.path in {"/quotes", "/execute/challenge", "/execute", "/agents/challenge", "/agents", "/analyze"}:
        try:
            enforce_rate_limit(request.url.path, request.client.host if request.client else "unknown", 30)
        except HTTPException as error:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
    return response

app.include_router(gateway.router)

class AnalyzeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32_000)

class NodeInfo(BaseModel):
    node_id: str = Field(min_length=1, max_length=64)
    worker_pubkey: str = Field(min_length=32, max_length=44)
    gpu_name: str = Field(min_length=1, max_length=128)
    vram_total: float = Field(ge=0, le=1_000)
    vram_used: Optional[float] = Field(default=None, ge=0, le=1_000)
    gpu_temp: Optional[float] = Field(default=None, ge=-50, le=150)
    gpu_util: Optional[int] = Field(default=None, ge=0, le=100)
    power_watts: Optional[float] = Field(default=None, ge=0, le=10_000)
    tflops: Optional[float] = Field(default=None, ge=0, le=100_000)
    status: str = Field(default="ONLINE", max_length=32)
    execution_mode: str = Field(default="unknown", max_length=32)

class AirdropRequest(BaseModel):
    wallet: str = Field(min_length=32, max_length=44)
    amount_sol: float = Field(default=1.0, gt=0, le=2.0)

@app.get("/")
def root():
    return {"protocol": "Aperture Compute", "version": "2.0.0", "status": "online", "network": "Solana Devnet", "demo_mode": DEMO_MODE}

@app.get("/health")
async def health():
    signer_configured = bool(os.getenv("BACKEND_PRIVATE_KEY")) or KEYPAIR_PATH.exists()
    config = None
    if not DEMO_MODE and worker_token_is_configured(WORKER_TOKEN) and signer_configured:
        try:
            config = await solana_client.get_protocol_config()
        except Exception:
            pass
    ready = worker_token_is_configured(WORKER_TOKEN) and (DEMO_MODE or config is not None)
    return {"status": "ready" if ready else "configuration_required", "environment": APP_ENV,
            "demo_mode": DEMO_MODE, "worker_auth_configured": worker_token_is_configured(WORKER_TOKEN),
            "oracle_signer_configured": signer_configured, "protocol_config_initialized": bool(config) if not DEMO_MODE else None,
            "protocol_version": 2, "durable_state": True, "kya": "owner-issued delegation; not legal KYC", "execution_scope": "bounded Python CPU"}

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    return analyze_code_ast(req.code)

@app.get("/price")
def price():
    return {"price": get_sol_price_from_pyth(), "source": "Pyth/Binance reference; not settlement authority"}

@app.get("/balance/{wallet_address}")
async def balance(wallet_address: str):
    try:
        state = await solana_client.get_channel_state(wallet_address)
        lamports = state.get("effective_balance_lamports", state["balance_lamports"]) if state else 0
        return {"wallet": wallet_address, "lamports": lamports, "balance": lamports / 1e9,
                "initialized": state is not None, "burn_rate_lamports": state["burn_rate_lamports"] if state else 0,
                "status": "on_chain" if state else "channel_not_opened", "task_deadline": state.get("task_deadline") if state else None}
    except Exception:
        raise HTTPException(503, "Compatible payment channel state is unavailable.")

@app.get("/channel-config")
async def channel_config():
    try:
        config = await solana_client.get_protocol_config()
        pda, _ = solana_client.get_config_pda()
        return {"initialized": config is not None, "program_id": str(solana_client.program_id), "config_pda": str(pda),
                "oracle": str(config["oracle"]) if config else None, "treasury": str(config["treasury"]) if config else None, "version": 2}
    except Exception:
        raise HTTPException(503, "Compatible v2 protocol configuration is unavailable.")

@app.post("/register_node")
async def register_node(info: NodeInfo, worker_id: str = Depends(require_worker)):
    from agent_identity import valid_public_key
    if info.node_id != worker_id or not valid_public_key(info.worker_pubkey):
        raise HTTPException(409, "Worker identity does not match node payload.")
    existing = gateway.store.get("workers", worker_id)
    if existing and existing["worker_pubkey"] != info.worker_pubkey:
        raise HTTPException(409, "Worker signing key changed; register a new worker ID.")
    record = {**info.model_dump(), "last_seen": time.time()}
    gateway.store.put("workers", worker_id, record)
    nodes[worker_id] = record
    return {"status": "registered", "node_id": worker_id}

@app.get("/active_nodes")
async def active_nodes():
    now = time.time()
    return [node for node in gateway.store.list("workers") if now - node["last_seen"] < 45]

@app.get("/benchmarks")
def get_benchmarks():
    """Pre-configured curated benchmark workloads for demonstration and evaluation."""
    return [
        {
            "id": "matrix_mult",
            "name": "Matrix Multiplication (Python CPU)",
            "category": "Scientific Computing",
            "code": """# Aperture Benchmark: Dense Matrix Multiplication in Python
import time
import random

print(">>> [INIT] Allocating 150x150 Float Matrices...")
N = 150
A = [[random.random() for _ in range(N)] for _ in range(N)]
B = [[random.random() for _ in range(N)] for _ in range(N)]
C = [[0.0 for _ in range(N)] for _ in range(N)]

start = time.perf_counter()
print(f">>> [COMPUTE] Performing O(N^3) Matrix Multiplication for N={N}...")

for i in range(N):
    for j in range(N):
        total = 0.0
        for k in range(N):
            total += A[i][k] * B[k][j]
        C[i][j] = total

duration = time.perf_counter() - start
print(f"✅ [SUCCESS] Computed the {N}x{N} matrix product in {duration:.3f}s")
print("📊 [INFO] This script ran as a Python workload; billing is managed by the gateway.")
"""
        },
        {
            "id": "monte_carlo",
            "name": "Monte Carlo Pi Estimation (Stochastic Model)",
            "category": "Simulation",
            "code": """# Aperture Benchmark: Monte Carlo Pi Estimation
import random
import time

print(">>> [INIT] Initializing 500,000 Stochastic Iterations...")
total_points = 500000
inside_circle = 0

start = time.perf_counter()
for i in range(total_points):
    x = random.random()
    y = random.random()
    if (x*x + y*y) <= 1.0:
        inside_circle += 1

pi_estimate = 4.0 * inside_circle / total_points
elapsed = time.perf_counter() - start

print(f"✅ [RESULT] Estimated Pi: {pi_estimate:.6f} (Error: {abs(pi_estimate - 3.14159265):.6f})")
print(f"⏱️ [PERF] Executed 500,000 iterations in {elapsed:.3f}s on Aperture Node")
"""
        },
        {
            "id": "prime_sieve",
            "name": "Sieve of Eratosthenes (Memory & Branching)",
            "category": "Algorithm",
            "code": """# Aperture Benchmark: Prime Number Sieve
import time

LIMIT = 1000000
print(f">>> [INIT] Running Sieve of Eratosthenes up to {LIMIT:,}...")
start = time.perf_counter()

primes = [True] * LIMIT
primes[0] = primes[1] = False

for p in range(2, int(LIMIT**0.5) + 1):
    if primes[p]:
        for multiple in range(p * p, LIMIT, p):
            primes[multiple] = False

count = sum(primes)
elapsed = time.perf_counter() - start

print(f"✅ [RESULT] Found {count:,} prime numbers below {LIMIT:,}")
print(f"⏱️ [PERF] Computed in {elapsed:.3f}s. Memory footprint verified.")
"""
        },
        {
            "id": "sha256_mining",
            "name": "Cryptographic Proof-of-Work Simulation",
            "category": "Cryptography",
            "code": """# Aperture Benchmark: SHA-256 Mining Simulation
import hashlib
import time

target_prefix = "0000"
print(f">>> [INIT] Searching for SHA-256 hash starting with '{target_prefix}'...")

nonce = 0
start = time.perf_counter()

while True:
    data = f"Aperture-Solana-Block-{nonce}".encode('utf-8')
    h = hashlib.sha256(data).hexdigest()
    if h.startswith(target_prefix):
        elapsed = time.perf_counter() - start
        print(f"💎 [FOUND] Nonce: {nonce} | Hash: {h}")
        print(f"⏱️ [PERF] Rate: {int(nonce / max(elapsed, 0.001)):,} H/s in {elapsed:.3f}s")
        break
    nonce += 1
"""
        },
        {
            "id": "neural_forward",
            "name": "Neural Network Forward Pass (Python CPU)",
            "category": "Machine Learning Prototype",
            "code": """# Aperture Benchmark: Neural Network Forward Pass in Python
import time
import math
import random

print(">>> [INIT] Initializing 3-Layer Dense Perceptron (Inputs: 128, Hidden: 64, Outputs: 10)...")
num_samples = 500
input_dim = 128
hidden_dim = 64
output_dim = 10

# Initialize weights and inputs
W1 = [[random.uniform(-0.1, 0.1) for _ in range(hidden_dim)] for _ in range(input_dim)]
b1 = [0.01 for _ in range(hidden_dim)]
W2 = [[random.uniform(-0.1, 0.1) for _ in range(output_dim)] for _ in range(hidden_dim)]
b2 = [0.01 for _ in range(output_dim)]
X = [[random.random() for _ in range(input_dim)] for _ in range(num_samples)]

def relu(x):
    return max(0.0, x)

def softmax(vec):
    exps = [math.exp(min(v, 20.0)) for v in vec]
    s = sum(exps)
    return [e / s for e in exps]

start = time.perf_counter()
print(f">>> [INFERENCE] Performing Forward Propagation over {num_samples} tensors...")

predictions = []
for sample in X:
    # Layer 1: Dense + ReLU
    h = []
    for j in range(hidden_dim):
        val = sum(sample[i] * W1[i][j] for i in range(input_dim)) + b1[j]
        h.append(relu(val))

    # Layer 2: Output Dense + Softmax
    logits = []
    for k in range(output_dim):
        val = sum(h[j] * W2[j][k] for j in range(hidden_dim)) + b2[k]
        logits.append(val)

    probs = softmax(logits)
    pred_class = probs.index(max(probs))
    predictions.append(pred_class)

elapsed = time.perf_counter() - start
total_ops = num_samples * (input_dim * hidden_dim * 2 + hidden_dim * output_dim * 2)
print(f"✅ [RESULT] Completed {num_samples} inferences ({total_ops:,} FLOPs) in {elapsed:.3f}s")
print(f"🧠 [METRICS] Throughput: {num_samples / max(elapsed, 0.001):.1f} samples/sec in Python")
"""
        },
        {
            "id": "security_exploit",
            "name": "Restricted Source Example (Expected to Be Rejected)",
            "category": "Source-policy Preview",
            "code": """# Source-policy example; this code should not be executed
import os
import subprocess

print("Attempting to access host environment...")
os.system("ls -la /")
subprocess.run(["cat", "/etc/shadow"])
"""
        }
    ]


@app.get("/stats")
def get_stats():
    """Aggregated protocol telemetry for the DePIN network."""
    now = time.time()
    active = [n for n in nodes.values() if now - n["last_seen"] < 45]
    known_temps = [n["gpu_temp"] for n in active if n.get("gpu_temp") is not None]
    known_utils = [n["gpu_util"] for n in active if n.get("gpu_util") is not None]
    avg_temp = round(sum(known_temps) / len(known_temps), 1) if known_temps else None
    avg_util = round(sum(known_utils) / len(known_utils), 0) if known_utils else None
    total_vram = round(sum(n.get("vram_total") or 0.0 for n in active), 1)
    used_vram = round(sum(n.get("vram_used") or 0.0 for n in active), 1)
    total_tflops = round(sum(float(n.get("tflops") or 0.0) for n in active), 1)
    done = [job for job in gateway.store.list('jobs') if job['state'] == 'completed']
    grid_stats['tasks_completed'] = len(done)
    grid_stats['total_compute_seconds'] = sum(job['receipt']['execution_time'] for job in done)
    grid_stats['total_sol_burned'] = sum(job['receipt'].get('cost_sol') or 0 for job in done)

    return {
        "tasks_completed": grid_stats["tasks_completed"],
        "total_compute_seconds": round(grid_stats["total_compute_seconds"], 2),
        "total_sol_burned": round(grid_stats["total_sol_burned"], 6),
        "threats_blocked": grid_stats["threats_blocked"],
        "active_nodes": len(active),
        "active_workers_count": len(active),
        "sol_price": get_sol_price_from_pyth(),
        "network": "Solana Devnet",
        "program_id": str(solana_client.program_id),
        "hardware": {
            "avg_temp": avg_temp,
            "avg_util": avg_util,
            "total_vram": total_vram,
            "used_vram": used_vram,
            "total_tflops": total_tflops
        }
    }


@app.post("/faucet/airdrop")
async def faucet_airdrop(req: AirdropRequest, request: Request):
    """Requests Devnet SOL airdrop to help evaluators test without a funded wallet."""
    if APP_ENV == "production":
        raise HTTPException(status_code=404, detail="Devnet faucet is disabled in production.")
    client_id = request.client.host if request.client else "unknown"
    enforce_rate_limit("faucet", f"{client_id}:{req.wallet}", 3)
    success = await solana_client.request_airdrop(req.wallet, int(req.amount_sol * 1_000_000_000))
    if success:
        return {"status": "success", "amount_sol": req.amount_sol, "wallet": req.wallet}
    raise HTTPException(status_code=500, detail="Devnet faucet request failed or rate-limited. Try official solana airdrop.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
