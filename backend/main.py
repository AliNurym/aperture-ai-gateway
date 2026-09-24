import os
import sys
import uuid
import secrets
import time
import asyncio
import hmac
import math
import base58
import requests
from dotenv import load_dotenv

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from contextlib import asynccontextmanager
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

from ai_engine import analyze_code_complexity, get_sol_price_from_pyth
from solana_client import KEYPAIR_PATH, SolanaClient
from task_auth import execution_message

load_dotenv()

APP_ENV = os.getenv("APERTURE_ENV", "development").lower()
DEMO_MODE = os.getenv("APERTURE_DEMO_MODE", "false").lower() == "true"
WORKER_TOKEN = os.getenv("APERTURE_WORKER_TOKEN", "")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
HELIUS_URL = f"https://devnet.helius-rpc.com/?api-key={HELIUS_API_KEY}" if HELIUS_API_KEY else None
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if origin.strip()]
MAX_PENDING_TASKS = int(os.getenv("APERTURE_MAX_PENDING_TASKS", "100"))
MAX_STREAM_LINES_PER_TASK = int(os.getenv("APERTURE_MAX_STREAM_LINES_PER_TASK", "10_000"))
MAX_LOG_BYTES_PER_TASK = int(os.getenv("APERTURE_MAX_LOG_BYTES_PER_TASK", "1_000_000"))
TASK_LEASE_SECONDS = int(os.getenv("APERTURE_TASK_LEASE_SECONDS", "210"))
MAX_COMPLETED_TASKS = max(1, int(os.getenv("APERTURE_MAX_COMPLETED_TASKS", "1000")))
EXECUTE_RATE_LIMIT = max(1, int(os.getenv("APERTURE_EXECUTE_RATE_LIMIT", "10")))
FAUCET_RATE_LIMIT = max(1, int(os.getenv("APERTURE_FAUCET_RATE_LIMIT", "3")))
RATE_LIMIT_WINDOW_SECONDS = max(1, int(os.getenv("APERTURE_RATE_LIMIT_WINDOW_SECONDS", "60")))
AUTH_CHALLENGE_TTL_SECONDS = max(15, min(300, int(os.getenv("APERTURE_AUTH_CHALLENGE_TTL_SECONDS", "90"))))


def worker_token_is_configured(token: str) -> bool:
    """Reject empty/example credentials instead of treating documentation as a secret."""
    normalized = (token or "").strip().lower()
    return len(token or "") >= 16 and normalized not in {
        "replace-with-a-long-random-secret",
        "change-me",
        "example-token",
    }


def require_worker(
    x_aperture_worker_token: Optional[str] = Header(default=None),
    x_aperture_worker_id: Optional[str] = Header(default=None),
) -> str:
    """Authenticate a named worker before it can claim or mutate a task."""
    if not worker_token_is_configured(WORKER_TOKEN):
        raise HTTPException(status_code=503, detail="Worker authentication is not configured.")
    if not x_aperture_worker_token or not hmac.compare_digest(x_aperture_worker_token, WORKER_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid worker credentials.")
    if not x_aperture_worker_id or len(x_aperture_worker_id) > 64:
        raise HTTPException(status_code=401, detail="Worker identity is required.")
    return x_aperture_worker_id


def require_task_access(task_id: str, access_token: Optional[str]) -> None:
    """Task URLs are bearer-capability URLs, not public task-status feeds."""
    task = active_tasks_rates.get(task_id)
    expected = task.get("access_token") if task else None
    if not expected:
        # Completed tasks retain their capability separately for the result/log
        # endpoints; unknown IDs must not be distinguishable from forbidden ones.
        expected = completed_task_access.get(task_id)
    if not access_token or not expected or not hmac.compare_digest(access_token, expected):
        raise HTTPException(status_code=404, detail="Task not found.")


def verify_signature(public_key_str: str, signature_bytes: list, message_str: str) -> bool:
    """Verifies an Ed25519 wallet signature. Demo bypasses are opt-in only."""
    if not public_key_str:
        return False

    if DEMO_MODE and public_key_str.startswith("DEMO_") and signature_bytes == [0] * 64:
        print(f"[DEMO] Explicit demo authentication for {public_key_str[:12]}")
        return True

    try:
        public_key_bytes = base58.b58decode(public_key_str)
        if len(public_key_bytes) != 32:
            return False
        verify_key = VerifyKey(public_key_bytes)
        sig_bytes = bytes(signature_bytes)
        msg_bytes = message_str.encode("utf-8")
        verify_key.verify(msg_bytes, sig_bytes)
        return True
    except (BadSignatureError, ValueError, TypeError) as e:
        print(f"[!] Web3 authentication rejected ({public_key_str[:8]}...): {e}")
        return False


def mint_compute_receipt(wallet: str, task_id: str, duration: float, cost: float, ai_verdict: str) -> Optional[str]:
    """
    Generates an on-chain verifiable compute receipt.
    Attempts Helius compressed NFT mint on Devnet, with cryptographic fallback.
    """
    if not HELIUS_URL:
        return None
    print(f"[🛠️] Minting compute receipt for {wallet} (Task: {task_id})...")
    payload = {
        "jsonrpc": "2.0",
        "id": "aperture-mint",
        "method": "mintCompressedNft",
        "params": {
            "name": f"Aperture Task {task_id[-6:].upper()}",
            "symbol": "APRT",
            "owner": wallet if len(wallet) >= 32 and not wallet.startswith("DEMO_") else "C2q9yxux7b7bxFF64pkZUV6g2Vcs2bQ1FS4GUQy512wv",
            "description": f"Aperture AI Compute Receipt. Verdict: {ai_verdict}",
            "attributes": [
                {"trait_type": "Duration", "value": f"{duration:.2f}s"},
                {"trait_type": "Cost_SOL", "value": f"{cost:.8f} SOL"},
                {"trait_type": "Task_ID", "value": task_id},
                {"trait_type": "Network", "value": "Solana Devnet"},
                {"trait_type": "Validator", "value": "Aperture AI Sentinel"}
            ],
            "imageUrl": "https://raw.githubusercontent.com/solana-foundation/press-kit/main/Solana_Logo_Symbol_Gradient.png",
            "externalUrl": "https://github.com/AliNurym/aperture-ai-gateway"
        }
    }
    try:
        response = requests.post(HELIUS_URL, json=payload, timeout=5)
        res_data = response.json()
        if "result" in res_data and "signature" in res_data["result"]:
            tx_sig = res_data['result']['signature']
            print(f"[⛓️] COMPRESSED NFT RECEIPT MINTED: {tx_sig}")
            return tx_sig
    except Exception as e:
        print(f"[!] Helius compressed NFT notice: {e}")

    return None


# Global statistics tracker
grid_stats = {
    "tasks_completed": 0,
    "total_compute_seconds": 0.0,
    "total_sol_burned": 0.0,
    "threats_blocked": 0,
    "start_time": time.time()
}

# In-memory grid state
nodes: Dict[str, dict] = {}
pending_tasks: List[dict] = []
claimed_tasks: Dict[str, dict] = {}
completed_tasks: Dict[str, str] = {}
completed_task_access: Dict[str, str] = {}
completed_task_times: Dict[str, float] = {}
completed_receipts: Dict[str, dict] = {}
full_logs: Dict[str, str] = {}
active_tasks_rates: Dict[str, dict] = {}
streamed_logs: Dict[str, List[str]] = {}
streamed_log_bytes: Dict[str, int] = {}
request_rate_buckets: Dict[str, List[float]] = {}
execution_challenges: Dict[str, dict] = {}
# Cancellation is retained until the leased worker observes it (or its lease
# expires). Removing the lease immediately would prevent authenticated polling.
cancelled_tasks: Dict[str, float] = {}
execution_admission_lock = asyncio.Lock()
task_settlement_lock = asyncio.Lock()

solana_client = SolanaClient()


async def requeue_expired_tasks() -> None:
    """Fail closed on a dead worker lease: stop billing; never duplicate work."""
    now = time.time()
    expired = [task_id for task_id, claim in claimed_tasks.items() if now - claim["claimed_at"] > TASK_LEASE_SECONDS]
    for task_id in expired:
        async with task_settlement_lock:
            claim = claimed_tasks.get(task_id)
            info = active_tasks_rates.get(task_id)
            if not info:
                claimed_tasks.pop(task_id, None)
                cancelled_tasks.pop(task_id, None)
                continue
            stop_sig = await solana_client.update_burn_rate(user_pubkey_str=info["wallet"], new_rate_lamports=0)
            if not stop_sig and not DEMO_MODE:
                print(f"[QUEUE] Could not stop billing for expired task {task_id}; will retry on the next queue poll.")
                continue

            active_tasks_rates.pop(task_id, None)
            claimed_tasks.pop(task_id, None)
            cancelled_tasks.pop(task_id, None)
            proof_url = f"https://explorer.solana.com/tx/{stop_sig}?cluster=devnet" if stop_sig else None
            receipt = {
                "status": "saved",
                "task_id": task_id,
                "execution_status": "failed",
                "exit_code": None,
                "worker_id": claim.get("worker_id") if claim else None,
                "settlement_type": "DEVNET" if stop_sig else "OFF_CHAIN",
                "receipt_signature": None,
                "explorer_url": proof_url,
            }
            store_completed_task(task_id, "EXECUTION_LEASE_EXPIRED", "EXECUTION_LEASE_EXPIRED", info["access_token"], receipt)
            print(f"[QUEUE] Expired worker lease for {task_id}; billing stopped ({stop_sig}).")


def store_completed_task(task_id: str, output: str, full_log: str, access_token: str, receipt: Optional[dict] = None) -> None:
    """Keep completed task evidence bounded in memory until durable storage exists."""
    while len(completed_tasks) >= MAX_COMPLETED_TASKS:
        oldest_task_id = next(iter(completed_tasks))
        completed_tasks.pop(oldest_task_id, None)
        completed_task_access.pop(oldest_task_id, None)
        completed_task_times.pop(oldest_task_id, None)
        completed_receipts.pop(oldest_task_id, None)
        full_logs.pop(oldest_task_id, None)
        streamed_logs.pop(oldest_task_id, None)
        streamed_log_bytes.pop(oldest_task_id, None)
    completed_tasks[task_id] = output
    completed_task_access[task_id] = access_token
    completed_task_times[task_id] = time.time()
    full_logs[task_id] = full_log
    completed_receipts[task_id] = receipt or {
        "execution_status": "cancelled" if output == "EXECUTION_ABORTED_BY_USER" else "failed" if output == "EXECUTION_LEASE_EXPIRED" else "completed",
        "settlement_type": "UNKNOWN",
    }


def enforce_rate_limit(scope: str, client_id: str, limit: int) -> None:
    """Small in-process abuse guard; use a shared proxy/store for multi-instance production."""
    now = time.time()
    bucket_key = f"{scope}:{client_id}"
    recent = [seen_at for seen_at in request_rate_buckets.get(bucket_key, []) if now - seen_at < RATE_LIMIT_WINDOW_SECONDS]
    if len(recent) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Retry shortly.")
    recent.append(now)
    request_rate_buckets[bucket_key] = recent

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🟢 Aperture AI Oracle: Systems Online.")
    print("🛰️ AI Sentinel: AST Guard & Pyth Price Feeds Ready.")

    yield
    await solana_client.close()
    print("🛑 Aperture AI Oracle: Systems Offline.")


app = FastAPI(
    title="Aperture AI: Autonomous DePIN Gateway",
    description="The first logic-aware billing protocol on Solana built for the 400ms block economy.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


class RunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32_000)
    wallet: str = Field(min_length=1, max_length=44)
    signature: Optional[List[int]] = Field(default=None, min_length=64, max_length=64)
    message: Optional[str] = Field(default=None, max_length=512)
    authorization_nonce: str = Field(min_length=16, max_length=128)
    authorization_expires_at: int = Field(ge=1)
    guest_id: Optional[str] = "guest"


class ExecutionChallengeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32_000)
    wallet: str = Field(min_length=1, max_length=44)


class NodeInfo(BaseModel):
    node_id: str = Field(min_length=1, max_length=64)
    gpu_name: str = Field(min_length=1, max_length=128)
    vram_total: float = Field(ge=0, le=1_000)
    vram_used: Optional[float] = Field(default=0.0, ge=0, le=1_000)
    gpu_temp: Optional[float] = Field(default=45.0, ge=-50, le=150)
    gpu_util: Optional[int] = Field(default=0, ge=0, le=100)
    power_watts: Optional[float] = Field(default=15.0, ge=0, le=10_000)
    tflops: Optional[float] = Field(default=0.0, ge=0, le=100_000)
    status: Optional[str] = Field(default="ONLINE", max_length=32)


class StreamChunk(BaseModel):
    task_id: str
    lines: List[str]
    node_id: Optional[str] = None


class AirdropRequest(BaseModel):
    wallet: str = Field(min_length=32, max_length=44)
    amount_sol: Optional[float] = Field(default=1.0, gt=0, le=2.0)


@app.get("/")
def root():
    return {
        "protocol": "Aperture AI",
        "description": "Autonomous DePIN Grid Governed by AI on Solana",
        "version": "1.0.0",
        "network": "Solana Devnet",
        "status": "OPERATIONAL"
    }


@app.get("/health")
def health():
    """Liveness/readiness signal safe for load balancers and public status checks."""
    signer_configured = bool(os.getenv("BACKEND_PRIVATE_KEY")) or KEYPAIR_PATH.exists()
    ready = worker_token_is_configured(WORKER_TOKEN) and (DEMO_MODE or signer_configured)
    return {
        "status": "ready" if ready else "configuration_required",
        "environment": APP_ENV,
        "demo_mode": DEMO_MODE,
        "worker_auth_configured": worker_token_is_configured(WORKER_TOKEN),
        "oracle_signer_configured": signer_configured,
    }


@app.get("/price")
def get_sol_price():
    """Returns the live SOL price from Pyth Network oracle."""
    price = get_sol_price_from_pyth()
    return {"price": price, "source": "Pyth Network Hermes / Binance Oracle"}


@app.get("/balance/{wallet_address}")
async def get_balance(wallet_address: str):
    """Reads on-chain locked fuel balance directly from user's PDA channel."""
    try:
        channel_state = await solana_client.get_channel_state(wallet_address)
        balance_lamports = channel_state["balance_lamports"] if channel_state else 0
        balance_sol = balance_lamports / 1_000_000_000
        return {
            "wallet": wallet_address,
            "lamports": balance_lamports,
            "balance": round(balance_sol, 8),
            "initialized": channel_state is not None,
            "burn_rate_lamports": channel_state["burn_rate_lamports"] if channel_state else 0,
            "status": "on_chain" if channel_state else "channel_not_opened"
        }
    except Exception as e:
        print(f"🔴 Error reading on-chain balance: {e}")
        return {"balance": 0.0, "lamports": 0, "initialized": False, "status": "error"}


@app.get("/channel-config")
async def get_channel_config():
    """Returns public protocol account addresses needed by the wallet client."""
    try:
        config = await solana_client.get_protocol_config()
        config_pda, _bump = solana_client.get_config_pda()
        return {
            "initialized": config is not None,
            "program_id": str(solana_client.program_id),
            "config_pda": str(config_pda),
            "oracle": str(config["oracle"]) if config else None,
            "treasury": str(config["treasury"]) if config else None,
        }
    except Exception as e:
        print(f"🔴 Error reading protocol config: {e}")
        raise HTTPException(status_code=503, detail="Protocol configuration is unavailable or incompatible.")


@app.post("/execute/challenge")
def issue_execution_challenge(req: ExecutionChallengeRequest, request: Request):
    """Issue a one-time, short-lived wallet-signature challenge for this code."""
    client_id = request.client.host if request.client else "unknown"
    enforce_rate_limit("challenge", client_id, EXECUTE_RATE_LIMIT)
    now = int(time.time())
    expired = [nonce for nonce, item in execution_challenges.items() if item["expires_at"] < now]
    for nonce in expired:
        execution_challenges.pop(nonce, None)
    nonce = secrets.token_urlsafe(32)
    expires_at = now + AUTH_CHALLENGE_TTL_SECONDS
    execution_challenges[nonce] = {"wallet": req.wallet, "code": req.code, "expires_at": expires_at}
    return {
        "nonce": nonce,
        "expires_at": expires_at,
        "message": execution_message(req.wallet, req.code, nonce, expires_at),
    }


@app.post("/execute")
async def execute_code(req: RunRequest, request: Request):
    """
    Primary Gateway Endpoint:
    1. Authenticates wallet
    2. Runs AI-Sentinel Pre-Execution Audit (AST security & complexity)
    3. Blocks malicious code immediately
    4. Calculates dynamic burn rate (Lamports/sec)
    5. Modulates on-chain smart contract state
    6. Dispatches to decentralized execution worker
    """
    client_id = request.client.host if request.client else "unknown"
    enforce_rate_limit("execute", client_id, EXECUTE_RATE_LIMIT)
    sig = req.signature or [0] * 64
    msg = req.message or ""
    challenge = execution_challenges.get(req.authorization_nonce)
    expected_message = execution_message(req.wallet, req.code, req.authorization_nonce, req.authorization_expires_at)
    now = int(time.time())
    if (
        not challenge
        or challenge["expires_at"] != req.authorization_expires_at
        or challenge["expires_at"] < now
        or challenge["wallet"] != req.wallet
        or challenge["code"] != req.code
    ):
        raise HTTPException(status_code=401, detail="Execution authorization is expired or already used.")
    if not hmac.compare_digest(msg, expected_message):
        raise HTTPException(status_code=401, detail="Signature message does not match this workload.")

    if not verify_signature(req.wallet, sig, msg):
        raise HTTPException(status_code=401, detail="Invalid Web3 Wallet Signature.")

    # 🧠 AI-SENTINEL PRE-EXECUTION AUDIT
    ai_result = analyze_code_complexity(req.code)

    if ai_result.get("security") == "DANGEROUS":
        grid_stats["threats_blocked"] += 1
        reason = ai_result.get("reason", "Malicious code detected.")
        print(f"\n[🚨 AI SENTINEL BLOCKED MALICIOUS CODE from {req.wallet[:8]}]")
        print(f"Reason: {reason}\n")
        return JSONResponse(
            status_code=403,
            content={
                "status": "blocked",
                "security": "DANGEROUS",
                "detail": f"AI Sentinel Security Alert: {reason}",
                "scores": ai_result.get("scores", {}),
                "reason": reason
            }
        )

    complexity = ai_result.get("complexity_score", 30)
    burn_rate_sol = ai_result.get("calculated_rate_sol_sec", 0.00000150)
    burn_rate_lamports = int(burn_rate_sol * 1_000_000_000)
    reason = ai_result.get("scores", {}).get("reason", "Algorithmic compute payload verified.")

    print("\n" + "="*55)
    print(f"🧠 [AI SENTINEL AUDIT PASSED]: {req.wallet[:12]}...")
    print(f"📊 [COMPLEXITY]: {complexity}/100 | Predicted Time: {ai_result.get('predicted_sec', 3)}s")
    print(f"🔥 [DYNAMIC BURN RATE]: {burn_rate_sol:.8f} SOL/sec ({burn_rate_lamports} lamports/sec)")
    print(f"📝 [VERDICT]: {reason}")
    print("="*55 + "\n")

    async with execution_admission_lock:
        # Recheck and consume under one lock: parallel replays cannot both pass
        # the one-time challenge check while waiting for the chain RPC.
        challenge = execution_challenges.get(req.authorization_nonce)
        if (
            not challenge
            or challenge["expires_at"] != req.authorization_expires_at
            or challenge["expires_at"] < int(time.time())
            or challenge["wallet"] != req.wallet
            or challenge["code"] != req.code
        ):
            raise HTTPException(status_code=401, detail="Execution authorization is expired or already used.")
        if len(pending_tasks) >= MAX_PENDING_TASKS:
            raise HTTPException(status_code=429, detail="Compute queue is full. Retry shortly.")
        if any(task.get("wallet") == req.wallet for task in active_tasks_rates.values()):
            raise HTTPException(status_code=409, detail="This payment channel already has an active task.")

        starting_balance = None
        if not DEMO_MODE:
            try:
                channel_state = await solana_client.get_channel_state(req.wallet)
            except Exception as e:
                print(f"🔴 Could not read payment channel before dispatch: {e}")
                raise HTTPException(status_code=503, detail="Payment channel could not be verified.")
            if not channel_state or channel_state["balance_lamports"] <= 0:
                raise HTTPException(status_code=409, detail="Open and fund a payment channel before execution.")
            starting_balance = channel_state["balance_lamports"]

        # 128-bit opaque IDs make task log/result URLs non-guessable.
        task_id = f"task-{uuid.uuid4().hex}"
        task_access_token = secrets.token_urlsafe(32)
        execution_challenges.pop(req.authorization_nonce, None)

        tx_sig = await solana_client.update_burn_rate(
            user_pubkey_str=req.wallet,
            new_rate_lamports=burn_rate_lamports
        )
        if not tx_sig and not DEMO_MODE:
            raise HTTPException(status_code=503, detail="On-chain payment channel update failed; task was not queued.")

        on_chain_proof = f"https://explorer.solana.com/tx/{tx_sig}?cluster=devnet" if tx_sig else None
        active_tasks_rates[task_id] = {
            "wallet": req.wallet,
            "rate_sol": burn_rate_sol,
            "start_time": time.time(),
            "starting_balance_lamports": starting_balance,
            "proof": on_chain_proof,
            "ai_verdict": reason,
            "complexity": complexity,
            "access_token": task_access_token,
        }
        pending_tasks.append({"task_id": task_id, "code": req.code, "wallet": req.wallet})

    return {
        "status": "success",
        "task_id": task_id,
        "burn_rate": burn_rate_sol,
        "burn_rate_lamports": burn_rate_lamports,
        "complexity_score": complexity,
        "ai_analysis": ai_result,
        "on_chain_proof": on_chain_proof,
        "tx_sig": tx_sig,
        "task_access_token": task_access_token,
        "sol_market_price": ai_result.get("sol_market_price", 185.0)
    }


@app.post("/submit_result")
async def submit_result(payload: dict, worker_id: str = Depends(require_worker)):
    """Execution Worker submits telemetry and stdout output upon task completion."""
    task_id = payload.get("task_id")
    output = payload.get("output", "")
    full_log_data = payload.get("full_log", output)
    exit_code = payload.get("exit_code", 0)
    if type(exit_code) is not int:
        raise HTTPException(status_code=422, detail="Exit code must be an integer.")
    try:
        execution_time = float(payload.get("execution_time", 0.0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Execution time must be numeric.")

    if not task_id or task_id not in active_tasks_rates:
        raise HTTPException(status_code=404, detail="Unknown or already-settled task.")
    claim = claimed_tasks.get(task_id)
    if not claim or claim["worker_id"] != worker_id:
        raise HTTPException(status_code=409, detail="Task is not leased to this worker.")
    if task_id in cancelled_tasks:
        claimed_tasks.pop(task_id, None)
        cancelled_tasks.pop(task_id, None)
        raise HTTPException(status_code=409, detail="Task was cancelled by its submitter.")
    if not math.isfinite(execution_time) or execution_time < 0 or execution_time > 180:
        raise HTTPException(status_code=422, detail="Execution time is outside the permitted range.")
    if not isinstance(output, str) or not isinstance(full_log_data, str):
        raise HTTPException(status_code=422, detail="Task output must be text.")
    if max(len(output.encode("utf-8", errors="replace")), len(full_log_data.encode("utf-8", errors="replace"))) > MAX_LOG_BYTES_PER_TASK:
        raise HTTPException(status_code=413, detail="Task output exceeds the configured limit.")

    async with task_settlement_lock:
        info = active_tasks_rates.get(task_id)
        claim = claimed_tasks.get(task_id)
        if not info:
            raise HTTPException(status_code=404, detail="Unknown or already-settled task.")
        if not claim or claim["worker_id"] != worker_id:
            raise HTTPException(status_code=409, detail="Task is not leased to this worker.")
        if task_id in cancelled_tasks:
            raise HTTPException(status_code=409, detail="Task was cancelled by its submitter.")

        # Keep the active record and worker lease until the reset is confirmed.
        # A transient RPC failure can then be retried without losing billing state.
        stop_sig = await solana_client.update_burn_rate(user_pubkey_str=info["wallet"], new_rate_lamports=0)
        if not stop_sig and not DEMO_MODE:
            raise HTTPException(status_code=503, detail="Could not confirm payment-channel settlement; worker may retry.")

        final_cost = None
        exact_cost = False
        if info.get("starting_balance_lamports") is not None:
            try:
                final_state = await solana_client.get_channel_state(info["wallet"])
                if final_state:
                    spent_lamports = max(0, info["starting_balance_lamports"] - final_state["balance_lamports"])
                    final_cost = round(spent_lamports / 1_000_000_000, 9)
                    exact_cost = True
            except Exception as e:
                print(f"[SETTLEMENT] Balance read failed after confirmed reset for {task_id}: {e}")

        receipt_sig = None
        if stop_sig:
            receipt_sig = mint_compute_receipt(
                wallet=info["wallet"],
                task_id=task_id,
                duration=execution_time,
                cost=final_cost if final_cost is not None else 0.0,
                ai_verdict=info["ai_verdict"]
            )

        proof_signature = receipt_sig or stop_sig
        explorer_url = f"https://explorer.solana.com/tx/{proof_signature}?cluster=devnet" if proof_signature else None
        receipt = {
            "status": "saved",
            "task_id": task_id,
            "execution_status": "completed" if exit_code == 0 else "failed",
            "exit_code": exit_code,
            "worker_id": worker_id,
            "execution_time": execution_time,
            "cost_sol": final_cost,
            "cost_is_exact": exact_cost,
            "settlement_type": "DEVNET" if stop_sig else "OFF_CHAIN",
            "receipt_signature": receipt_sig,
            "explorer_url": explorer_url
        }
        active_tasks_rates.pop(task_id, None)
        claimed_tasks.pop(task_id, None)
        store_completed_task(task_id, output, full_log_data, info["access_token"], receipt)

        grid_stats["tasks_completed"] += 1
        grid_stats["total_compute_seconds"] += execution_time
        if final_cost is not None:
            grid_stats["total_sol_burned"] += final_cost
        print(f"🛑 [SETTLEMENT] Task {task_id} billing reset confirmed ({stop_sig}).")
        return receipt


@app.post("/stop/{task_id}")
async def stop_task(task_id: str, access_token: Optional[str] = Query(default=None)):
    """Stops a running task immediately and resets on-chain burn rate to 0."""
    require_task_access(task_id, access_token)
    async with task_settlement_lock:
        info = active_tasks_rates.get(task_id)
        if not info:
            raise HTTPException(status_code=409, detail="Task is already concluded.")

        stop_sig = await solana_client.update_burn_rate(user_pubkey_str=info["wallet"], new_rate_lamports=0)
        if not stop_sig and not DEMO_MODE:
            raise HTTPException(status_code=503, detail="Could not confirm the payment-channel reset; the task remains active.")

        global pending_tasks
        pending_tasks = [task for task in pending_tasks if task.get("task_id") != task_id]
        if task_id in claimed_tasks:
            cancelled_tasks[task_id] = time.time()
        active_tasks_rates.pop(task_id, None)

        proof_url = f"https://explorer.solana.com/tx/{stop_sig}?cluster=devnet" if stop_sig else None
        receipt = {
            "status": "saved",
            "task_id": task_id,
            "execution_status": "cancelled",
            "exit_code": None,
            "settlement_type": "DEVNET" if stop_sig else "OFF_CHAIN",
            "receipt_signature": None,
            "explorer_url": proof_url,
        }
        store_completed_task(task_id, "EXECUTION_ABORTED_BY_USER", "EXECUTION_ABORTED_BY_USER", info["access_token"], receipt)
        print(f"🛑 [ABORT] User cancelled task {task_id}; billing reset confirmed ({stop_sig}).")
        return {"status": "stopped", "tx_sig": stop_sig}


@app.get("/result/{task_id}")
def get_result(task_id: str, access_token: Optional[str] = Query(default=None)):
    """Polled by frontend to receive real-time stdout and completion state."""
    require_task_access(task_id, access_token)
    if task_id in completed_tasks:
        return {
            "status": "completed",
            "output": completed_tasks[task_id],
            "receipt": completed_receipts.get(task_id),
            "task_id": task_id
        }
    return {"status": "processing", "task_id": task_id}


@app.get("/download/{task_id}")
def download_result(task_id: str, access_token: Optional[str] = Query(default=None)):
    """Downloads complete raw execution logs."""
    require_task_access(task_id, access_token)
    if task_id in full_logs:
        return PlainTextResponse(
            full_logs[task_id],
            headers={"Content-Disposition": f"attachment; filename=aperture_log_{task_id}.txt"}
        )
    raise HTTPException(status_code=404, detail="Log file not found.")


@app.post("/stream_log")
def stream_log_chunk(chunk: StreamChunk, worker_id: str = Depends(require_worker)):
    """Worker streams intermediate stdout chunks during execution."""
    if chunk.task_id not in active_tasks_rates:
        raise HTTPException(status_code=404, detail="Unknown or already-settled task.")
    claim = claimed_tasks.get(chunk.task_id)
    if not claim or claim["worker_id"] != worker_id or chunk.node_id != worker_id:
        raise HTTPException(status_code=409, detail="Task is not leased to this worker.")
    if chunk.task_id in cancelled_tasks:
        raise HTTPException(status_code=409, detail="Task was cancelled by its submitter.")
    if chunk.task_id not in streamed_logs:
        streamed_logs[chunk.task_id] = []
        streamed_log_bytes[chunk.task_id] = 0
    if len(streamed_logs[chunk.task_id]) + len(chunk.lines) > MAX_STREAM_LINES_PER_TASK:
        raise HTTPException(status_code=413, detail="Task stream exceeds the configured line limit.")
    chunk_bytes = sum(len(line.encode("utf-8", errors="replace")) for line in chunk.lines)
    if streamed_log_bytes[chunk.task_id] + chunk_bytes > MAX_LOG_BYTES_PER_TASK:
        raise HTTPException(status_code=413, detail="Stream chunk exceeds the configured byte limit.")
    streamed_logs[chunk.task_id].extend(chunk.lines)
    streamed_log_bytes[chunk.task_id] += chunk_bytes
    return {"status": "ok", "total_lines": len(streamed_logs[chunk.task_id])}


@app.get("/worker_task_status/{task_id}")
def worker_task_status(task_id: str, worker_id: str = Depends(require_worker)):
    """Expose cancellation only to the named worker that holds this lease."""
    claim = claimed_tasks.get(task_id)
    if not claim or claim["worker_id"] != worker_id:
        raise HTTPException(status_code=404, detail="Task lease not found.")
    return {"task_id": task_id, "cancelled": task_id in cancelled_tasks}


@app.get("/stream_log/{task_id}")
def get_stream_log(task_id: str, offset: int = 0, access_token: Optional[str] = Query(default=None)):
    """Frontend polls to get real-time incremental execution output."""
    require_task_access(task_id, access_token)
    all_lines = streamed_logs.get(task_id, [])
    new_lines = all_lines[offset:] if offset < len(all_lines) else []
    is_completed = task_id in completed_tasks
    output = completed_tasks.get(task_id)
    return {
        "task_id": task_id,
        "lines": new_lines,
        "next_offset": len(all_lines),
        "is_completed": is_completed,
        "output": output,
        "receipt": completed_receipts.get(task_id) if is_completed else None,
    }


@app.post("/register_node")
async def register_node(info: NodeInfo, worker_id: str = Depends(require_worker)):
    """Worker nodes call this periodically to heartbeat and announce hardware specs & live telemetry."""
    if info.node_id != worker_id:
        raise HTTPException(status_code=409, detail="Worker identity does not match node payload.")
    nodes[info.node_id] = {
        "node_id": info.node_id,
        "gpu_name": info.gpu_name,
        "vram_total": info.vram_total,
        "vram_used": info.vram_used if info.vram_used is not None else 0.0,
        "gpu_temp": info.gpu_temp if info.gpu_temp is not None else 45.0,
        "gpu_util": info.gpu_util if info.gpu_util is not None else 0,
        "power_watts": info.power_watts if info.power_watts is not None else 15.0,
        "tflops": info.tflops or 0.0,
        "status": info.status or "ONLINE",
        "last_seen": time.time()
    }
    return {"status": "registered", "node_id": info.node_id}


@app.get("/active_nodes")
async def get_nodes():
    """Returns list of currently active GPU and CPU execution workers in the DePIN grid."""
    now = time.time()
    # Keep nodes alive if seen in last 45 seconds
    active = [n for n in nodes.values() if now - n["last_seen"] < 45]
    return active


@app.get("/get_task")
async def get_task(worker_id: str = Depends(require_worker)):
    """Polled by worker daemon to receive next audited task in FIFO order."""
    await requeue_expired_tasks()
    if pending_tasks:
        task = pending_tasks.pop(0)
        claimed_tasks[task["task_id"]] = {"task": task, "worker_id": worker_id, "claimed_at": time.time()}
        return task
    return {"task_id": None}


@app.get("/benchmarks")
def get_benchmarks():
    """Pre-configured curated benchmark workloads for demonstration and evaluation."""
    return [
        {
            "id": "matrix_mult",
            "name": "Matrix Multiplication (High TFLOPS)",
            "category": "Scientific AI",
            "code": """# Aperture Benchmark: Dense Matrix Multiplication (TFLOPS Stress)
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
print(f"✅ [SUCCESS] Computed {N*N*N} floating point operations in {duration:.3f}s")
print(f"📊 [TELEMETRY] Aperture Logic-Aware Rate Applied: Robin Hood dynamic billing.")
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
            "name": "Deep Neural Network Forward Pass (Tensor AI Inference)",
            "category": "Machine Learning",
            "code": """# Aperture Benchmark: Deep Neural Network Layer Inference
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
print(f"🧠 [METRICS] Throughput: {num_samples / max(elapsed, 0.001):.1f} samples/sec on physical silicon")
"""
        },
        {
            "id": "security_exploit",
            "name": "Security Exploit Test (Blocked by Sentinel)",
            "category": "Security Sandbox",
            "code": """# Aperture Security Test: Unauthorized System Probe
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
    avg_temp = round(sum(n.get("gpu_temp", 0.0) for n in active) / len(active), 1) if active else None
    avg_util = round(sum(n.get("gpu_util", 0.0) for n in active) / len(active), 0) if active else None
    total_vram = round(sum(n.get("vram_total", 0.0) for n in active), 1)
    used_vram = round(sum(n.get("vram_used", 0.0) for n in active), 1)
    total_tflops = round(sum(float(n.get("tflops", 0.0)) for n in active), 1)

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
    enforce_rate_limit("faucet", f"{client_id}:{req.wallet}", FAUCET_RATE_LIMIT)
    success = await solana_client.request_airdrop(req.wallet, int(req.amount_sol * 1_000_000_000))
    if success:
        return {"status": "success", "amount_sol": req.amount_sol, "wallet": req.wallet}
    raise HTTPException(status_code=500, detail="Devnet faucet request failed or rate-limited. Try official solana airdrop.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
