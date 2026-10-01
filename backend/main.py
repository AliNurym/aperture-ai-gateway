"""Aperture gateway: bounded execution, KYA delegation, durable receipts."""
import os
import time
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlsplit
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field
from ai_engine import analyze_code_ast, get_sol_price_from_pyth
from solana_client import KEYPAIR_PATH, SolanaClient
from gateway import Gateway, SourceRequest, Utf8Request
from security_config import load_worker_credentials

load_dotenv()
APP_ENV = os.getenv("APERTURE_ENV", "development").strip().lower()
DEMO_MODE = os.getenv("APERTURE_DEMO_MODE", "false").strip().lower() == "true"
WORKER_TOKEN = (os.getenv("APERTURE_WORKER_TOKEN") or "").strip()
WORKER_CREDENTIALS = load_worker_credentials(os.getenv("APERTURE_WORKER_CREDENTIALS"))
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if origin.strip()]

def validate_runtime_configuration():
    if APP_ENV not in {"development", "test", "staging", "production"}:
        raise RuntimeError("APERTURE_ENV must be development, test, staging, or production.")
    if APP_ENV not in {"staging", "production"}:
        return
    issues = []
    if DEMO_MODE:
        issues.append("APERTURE_DEMO_MODE must be false in staging and production")
    if not WORKER_CREDENTIALS:
        issues.append("APERTURE_WORKER_CREDENTIALS must define a distinct 32+ character secret for every approved worker ID")
    state_db = (os.getenv("APERTURE_STATE_DB") or "").strip()
    if not state_db or state_db == ":memory:" or not os.path.isabs(state_db):
        issues.append("APERTURE_STATE_DB must be set to an absolute path on persistent storage in staging and production")
    invalid_origins = []
    for origin in CORS_ORIGINS:
        try:
            parsed = urlsplit(origin)
            parsed.port
            valid = (
                parsed.scheme.lower() == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.path == ""
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            invalid_origins.append(origin)
    if not CORS_ORIGINS or invalid_origins:
        issues.append("CORS_ORIGINS must contain only explicit HTTPS origins without paths, credentials, queries, or fragments")
    if issues:
        raise RuntimeError("Invalid production configuration: " + "; ".join(issues) + ".")

validate_runtime_configuration()
solana_client = SolanaClient()
legacy_worker_token = WORKER_TOKEN if APP_ENV in {"development", "test"} else ""
gateway = Gateway(solana_client, DEMO_MODE, legacy_worker_token, worker_credentials=WORKER_CREDENTIALS)
require_worker = gateway.require_worker
nodes = {}
request_rate_buckets = {}
request_rate_calls = 0
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_BUCKETS = 10_000

def enforce_rate_limit(scope, client_id, limit):
    global request_rate_calls
    now = time.monotonic()
    key = f"{scope}:{client_id}"
    request_rate_calls += 1
    if request_rate_calls % 256 == 0:
        expired = [bucket for bucket, timestamps in request_rate_buckets.items()
                   if not timestamps or now - timestamps[-1] >= RATE_LIMIT_WINDOW_SECONDS]
        for bucket in expired:
            request_rate_buckets.pop(bucket, None)
    recent = [item for item in request_rate_buckets.get(key, []) if now - item < RATE_LIMIT_WINDOW_SECONDS]
    if len(recent) >= limit:
        retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - recent[0])) + 1)
        raise HTTPException(429, "Rate limit exceeded. Retry shortly.", headers={"Retry-After": str(retry_after)})
    if key not in request_rate_buckets and len(request_rate_buckets) >= RATE_LIMIT_MAX_BUCKETS:
        oldest = min(request_rate_buckets, key=lambda bucket: request_rate_buckets[bucket][-1])
        request_rate_buckets.pop(oldest, None)
    request_rate_buckets[key] = recent + [now]


gateway.object_rate_limiter = enforce_rate_limit


class RequestBodyLimitMiddleware:
    """Reject oversized JSON bodies before FastAPI/Pydantic buffers and parses them."""
    def __init__(self, app, max_body_bytes):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        path = scope.get("path")
        # Immutable blob uploads authorize their exact size and hash before reading.
        # Preserve streaming instead of buffering up to 64 MiB in this JSON guard.
        if scope.get("method") == "PUT" and path.startswith("/objects/"):
            client = scope.get("client")
            try:
                enforce_rate_limit("object-upload", client[0] if client else "unknown", 3000)
            except HTTPException as error:
                await self._reject(send, status=error.status_code, detail=error.detail, extra_headers=error.headers)
                return
            await self.app(scope, receive, send)
            return
        limit = 3 if path == "/faucet/airdrop" else 30 if path in {"/quotes", "/execute/challenge", "/execute", "/agents/challenge", "/agents", "/agents/usage", "/agents/tasks/list", "/agents/tasks/resume", "/objects/authorize", "/objects/usage", "/objects/release", "/analyze"} else None
        if limit is not None:
            client = scope.get("client")
            try:
                enforce_rate_limit(path, client[0] if client else "unknown", limit)
            except HTTPException as error:
                await self._reject(send, status=error.status_code, detail=error.detail, extra_headers=error.headers)
                return

        content_length = next((value for name, value in scope.get("headers", []) if name.lower() == b"content-length"), None)
        if content_length is not None:
            try:
                declared_size = int(content_length)
                if declared_size < 0:
                    await self._reject(send, status=400, detail="Invalid Content-Length header.")
                    return
                if declared_size > self.max_body_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send, status=400, detail="Invalid Content-Length header.")
                return

        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_body_bytes:
                await self._reject(send)
                return
            if not message.get("more_body", False):
                break

        buffered_body = bytes(body)
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": buffered_body, "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)

    async def _reject(self, send, status=413, detail="Request body exceeds the configured size limit.", extra_headers=None):
        body = ("{\"detail\":\"" + detail + "\"}").encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"cache-control", b"no-store"),
        ]
        if extra_headers and "Retry-After" in extra_headers:
            headers.append((b"retry-after", extra_headers["Retry-After"].encode("ascii")))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})


@asynccontextmanager
async def lifespan(app):
    await gateway.start()
    yield
    await gateway.close()
    await solana_client.close()

app = FastAPI(title="Aperture Compute Gateway", version="2.0.0", lifespan=lifespan)
app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=max(1024, int(os.getenv("APERTURE_MAX_REQUEST_BYTES", "2500000"))))
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def security_and_admission(request, call_next):
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
    return response

app.include_router(gateway.router)

class AnalyzeRequest(SourceRequest):
    pass

class NodeInfo(Utf8Request):
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
    source_policy: str = Field(default="unknown", max_length=32)
    approved_source_count: Optional[int] = Field(default=None, ge=1, le=10_000)

class AirdropRequest(Utf8Request):
    wallet: str = Field(min_length=32, max_length=44)
    amount_sol: float = Field(default=1.0, gt=0, le=2.0)

@app.get("/")
def root():
    return {"protocol": "Aperture Compute", "version": "2.0.0", "status": "online", "network": "off_chain" if DEMO_MODE else "devnet", "demo_mode": DEMO_MODE}

@app.get("/health")
async def health():
    signer_configured = bool(os.getenv("BACKEND_PRIVATE_KEY")) or KEYPAIR_PATH.exists()
    config = None
    if not DEMO_MODE and gateway.worker_auth_configured and signer_configured:
        try:
            config = await solana_client.get_protocol_config()
        except Exception:
            pass
    configured = gateway.worker_auth_configured and gateway.store.durable_state and (DEMO_MODE or config is not None)
    active_workers = [node for node in gateway.store.list("workers") if time.time() - node.get("last_seen", 0) < 45]
    issues = []
    if not gateway.worker_auth_configured:
        issues.append("worker_authentication")
    if not gateway.store.durable_state:
        issues.append("non_durable_state")
    if not DEMO_MODE and not signer_configured:
        issues.append("oracle_signer")
    if not DEMO_MODE and config is None:
        issues.append("protocol_configuration")
    if not active_workers:
        issues.append("worker_connection")
    return {"status": "ready" if configured and active_workers else "workers_unavailable" if configured else "configuration_required", "environment": APP_ENV,
            "demo_mode": DEMO_MODE, "worker_auth_configured": gateway.worker_auth_configured,
            "oracle_signer_configured": signer_configured, "protocol_config_initialized": bool(config) if not DEMO_MODE else None,
            "network": "off_chain" if DEMO_MODE else "devnet", "gateway_pubkey": str(solana_client.ai_signer.pubkey()),
            "program_id": str(solana_client.program_id), "data_job_version": 1,
            "active_worker_count": len(active_workers), "configuration_issues": issues,
            "protocol_version": 2, "durable_state": gateway.store.durable_state,
            "kya": "owner-issued delegation; not legal KYC", "execution_scope": "bounded Python CPU"}

@app.get("/health/worker-auth")
def worker_auth_health():
    """Bootstrap probe used to start workers before Devnet config is initialized."""
    if not gateway.worker_auth_configured:
        raise HTTPException(503, "Worker authentication is not configured.")
    return {"status": "configured", "worker_auth_configured": True}

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
    active = [n for n in gateway.store.list("workers") if now - n["last_seen"] < 45]
    known_temps = [n["gpu_temp"] for n in active if n.get("gpu_temp") is not None]
    known_utils = [n["gpu_util"] for n in active if n.get("gpu_util") is not None]
    avg_temp = round(sum(known_temps) / len(known_temps), 1) if known_temps else None
    avg_util = round(sum(known_utils) / len(known_utils), 0) if known_utils else None
    total_vram = round(sum(n.get("vram_total") or 0.0 for n in active), 1)
    used_vram = round(sum(n.get("vram_used") or 0.0 for n in active), 1)
    total_tflops = round(sum(float(n.get("tflops") or 0.0) for n in active), 1)
    totals = gateway.store.telemetry_totals()
    retained_finished = gateway.store.count_completed_jobs()
    charged_lamports = totals['total_charged_lamports']

    return {
        "tasks_completed": totals["tasks_completed"],
        "total_compute_seconds": round(totals["total_compute_seconds"], 2),
        "total_sol_burned": charged_lamports / 1_000_000_000,
        "total_charged_lamports": charged_lamports,
        "tasks_finished": totals["tasks_finished"],
        "retained_tasks_finished": retained_finished,
        "history_scope": "durable_gateway_totals",
        "totals_tracked_since": totals["tracked_since"],
        "active_nodes": len(active),
        "active_workers_count": len(active),
        "sol_price": get_sol_price_from_pyth() if not DEMO_MODE else None,
        "network": "Off-chain execution" if DEMO_MODE else "Solana Devnet",
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
    if APP_ENV in {"staging", "production"}:
        raise HTTPException(status_code=404, detail="Devnet faucet is disabled in staging and production.")
    success = await solana_client.request_airdrop(req.wallet, int(req.amount_sol * 1_000_000_000))
    if success:
        return {"status": "success", "amount_sol": req.amount_sol, "wallet": req.wallet}
    raise HTTPException(status_code=500, detail="Devnet faucet request failed or rate-limited. Try official solana airdrop.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("APERTURE_BIND_HOST", "127.0.0.1"), port=8000)
