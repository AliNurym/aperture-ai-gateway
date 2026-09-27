"""Spend-bounded admission, owner delegation, and crash-safe settlement."""
import asyncio
import hmac
import math
import os
import secrets
import sqlite3
import time
import uuid
import base58
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from agent_identity import (CAPABILITIES, canonical_json, passport_message,
                            quote_message, receipt_message, sha256_text,
                            valid_public_key, verify_ed25519)
from ai_engine import analyze_code_ast, calculate_quantum_price
from state_store import ACTIVE_STATES, StateStore
from worker_identity import receipt_bytes


class QuoteRequest(BaseModel):
    wallet: str = Field(min_length=32, max_length=44)
    agent_pubkey: Optional[str] = Field(default=None, min_length=32, max_length=44)
    code: str = Field(min_length=1, max_length=32_000)
    max_cost_lamports: int = Field(default=1_000_000, gt=0, le=1_000_000_000)
    max_runtime_seconds: int = Field(default=30, ge=1, le=180)


class ExecuteRequest(BaseModel):
    quote_id: str = Field(min_length=16, max_length=128)
    wallet: str = Field(min_length=32, max_length=44)
    agent_pubkey: Optional[str] = Field(default=None, min_length=32, max_length=44)
    code: str = Field(min_length=1, max_length=32_000)
    signature: list[int] = Field(min_length=64, max_length=64)
    message: str = Field(min_length=1, max_length=2048)


class PassportChallenge(BaseModel):
    action: Literal["register", "update", "revoke"]
    owner: str = Field(min_length=32, max_length=44)
    agent_pubkey: str = Field(min_length=32, max_length=44)
    name: str = Field(default="Compute agent", min_length=1, max_length=80)
    max_cost_lamports: int = Field(default=1_000_000, gt=0, le=1_000_000_000)
    max_runtime_seconds: int = Field(default=30, ge=1, le=180)
    total_budget_lamports: int = Field(default=10_000_000, gt=0, le=100_000_000_000)
    expires_at: int = Field(gt=0)
    capabilities: list[str] = Field(default_factory=lambda: list(CAPABILITIES), min_length=1, max_length=1)


class PassportAuthorization(BaseModel):
    nonce: str = Field(min_length=16, max_length=128)
    signature: list[int] = Field(min_length=64, max_length=64)
    message: str = Field(min_length=1, max_length=4096)


class StreamChunk(BaseModel):
    task_id: str
    lines: list[str] = Field(max_length=10_000)
    node_id: Optional[str] = None
    lease_id: Optional[str] = None


class Gateway:
    def __init__(self, solana, demo_mode, worker_token, store=None):
        self.solana = solana
        self.demo_mode = demo_mode
        self.worker_token = worker_token
        self.store = store or StateStore(os.getenv("APERTURE_STATE_DB", str(Path(__file__).parent / "data" / "gateway.sqlite3")))
        self.lock = asyncio.Lock()
        self.router = APIRouter()
        self.recovery_task = None
        self._mount()

    def require_worker(self, x_aperture_worker_token: Optional[str] = Header(default=None), x_aperture_worker_id: Optional[str] = Header(default=None)):
        if len(self.worker_token) < 16 or self.worker_token == "replace-with-a-long-random-secret":
            raise HTTPException(503, "Worker authentication is not configured.")
        if not x_aperture_worker_token or not hmac.compare_digest(x_aperture_worker_token, self.worker_token):
            raise HTTPException(401, "Invalid worker credentials.")
        if not x_aperture_worker_id or len(x_aperture_worker_id) > 64:
            raise HTTPException(401, "Worker identity is required.")
        return x_aperture_worker_id

    def task(self, task_id, token=None, worker_id=None):
        job = self.store.get("jobs", task_id)
        if not job or (token is not None and not hmac.compare_digest(job["access_token"], token)) or (worker_id is not None and job.get("worker_id") != worker_id):
            raise HTTPException(404, "Task not found.")
        if token is None and worker_id is None:
            raise HTTPException(404, "Task access token is required.")
        return job

    def _valid_keys(self, *keys):
        if not all(valid_public_key(key) for key in keys):
            raise HTTPException(422, "A valid Ed25519 Solana public key is required.")

    async def passport(self, owner, agent, max_cost, runtime):
        if owner == agent:
            return None
        item = self.store.get("agents", agent)
        if not item or item["owner"] != owner or item["revoked"] or item["expires_at"] <= int(time.time()):
            raise HTTPException(403, "Agent delegation is absent, revoked, expired, or belongs to another owner.")
        if "python.execute" not in item["capabilities"] or max_cost > item["max_cost_lamports"] or runtime > item["max_runtime_seconds"]:
            raise HTTPException(403, "The quote exceeds the agent's delegated capabilities or limits.")
        # Reserve full task bounds until final settlement; never spend a not-yet
        # reconciled allowance again after an RPC failure or process restart.
        jobs = [job for job in self.store.list("jobs") if job.get("agent_pubkey") == agent and job["state"] in ACTIVE_STATES]
        reserved = sum(job["max_cost_lamports"] for job in jobs)
        spent = self.store.spent_for_agent(agent)
        if reserved + spent + max_cost > item["total_budget_lamports"]:
            raise HTTPException(403, "Agent lifetime budget has no available allowance.")
        if not self.demo_mode:
            chain = await self.solana.get_agent_passport(agent)
            if not chain or chain.get("owner") != owner or chain.get("revoked") or chain.get("valid_until", 0) <= int(time.time()):
                raise HTTPException(403, "A matching active on-chain agent passport is required.")
            if chain.get("metadata_hash") != item["metadata_hash"] or max_cost > chain["max_cost_lamports"] or runtime > chain["max_runtime_seconds"]:
                raise HTTPException(403, "On-chain agent policy does not match this delegation.")
            if chain["spent_lamports"] + chain["reserved_lamports"] + max_cost > chain["total_budget_lamports"]:
                raise HTTPException(403, "On-chain agent lifetime budget is exhausted.")
        return item

    async def issue_quote(self, req):
        agent = req.agent_pubkey or req.wallet
        self._valid_keys(req.wallet, agent)
        passport = await self.passport(req.wallet, agent, req.max_cost_lamports, req.max_runtime_seconds)
        audit = analyze_code_ast(req.code)
        if audit.get("security") == "DANGEROUS":
            raise HTTPException(403, audit.get("reason", "Source policy rejected workload."))
        complexity = audit.get('cpu', 20) + audit.get('ram', 15)
        rate = max(1, int(round(calculate_quantum_price(complexity) * 1_000_000_000)))
        analysis = {'security': 'SAFE', 'status': 'success', 'complexity_score': complexity,
                    'predicted_sec': audit.get('predicted_sec', 3), 'scores': audit,
                    'calculated_rate_sol_sec': rate / 1e9, 'calculated_rate_lamports_sec': rate,
                    'sol_market_price': None, 'reason': audit.get('reason'), 'pricing': 'deterministic_ast_lamports_v1'}
        if req.max_cost_lamports < rate:
            raise HTTPException(422, "Budget must cover at least one second at the quoted rate.")
        config = None
        if not self.demo_mode:
            try:
                config = await self.solana.get_protocol_config()
            except Exception:
                raise HTTPException(503, "Compatible protocol configuration cannot be verified.")
            if not config:
                raise HTTPException(503, "Compatible v2 protocol configuration is required before quoting live work.")
        quote = {
            "quote_id": secrets.token_urlsafe(24), "wallet": req.wallet, "agent_pubkey": agent,
            "code_sha256": sha256_text(req.code), "rate_lamports": rate,
            "max_cost_lamports": req.max_cost_lamports, "max_runtime_seconds": req.max_runtime_seconds,
            "effective_runtime_seconds": min(req.max_runtime_seconds, req.max_cost_lamports // rate),
            "expires_at": int(time.time()) + 90, "passport_version": passport["version"] if passport else 0,
            "analysis": analysis,
            "program_id": str(self.solana.program_id), "network": "off_chain" if self.demo_mode else "devnet",
            "gateway_pubkey": str(self.solana.ai_signer.pubkey()), "treasury": str(config["treasury"]) if config else None,
        }
        quote["message"] = quote_message(quote)
        self.store.put("quotes", quote["quote_id"], quote)
        return quote

    async def execute(self, req):
        async with self.lock:
            quote = self.store.get("quotes", req.quote_id)
            if not quote:
                raise HTTPException(401, "Quote is absent or expired. Request a fresh quote.")
            agent = req.agent_pubkey or req.wallet
            if quote["wallet"] != req.wallet or quote["agent_pubkey"] != agent or quote["code_sha256"] != sha256_text(req.code) or not hmac.compare_digest(quote["message"], req.message):
                raise HTTPException(401, "Signature authorization does not match the exact quote and source.")
            if not verify_ed25519(agent, req.signature, req.message):
                raise HTTPException(401, "Invalid agent signature.")
            existing = next((job for job in self.store.list('jobs') if job['quote_id'] == req.quote_id), None)
            if existing:
                return self.execution_response(existing)
            if quote['expires_at'] < int(time.time()):
                raise HTTPException(401, "Quote expired. Request a fresh quote.")
            passport = await self.passport(req.wallet, agent, quote["max_cost_lamports"], quote["max_runtime_seconds"])
            if (passport["version"] if passport else 0) != quote["passport_version"]:
                raise HTTPException(403, "Agent policy changed after this quote was issued.")
            if not self.demo_mode:
                channel = await self.solana.get_channel_state(req.wallet)
                if not channel or channel.get("effective_balance_lamports", channel["balance_lamports"]) < quote["max_cost_lamports"] or channel["burn_rate_lamports"]:
                    raise HTTPException(409, "Fund an idle compatible payment channel to cover the maximum authorized cost.")
            task_id = "task-" + uuid.uuid4().hex
            job = {**quote, "task_id": task_id, "task_hash": sha256_text(task_id), "code": req.code,
                   "access_token": secrets.token_urlsafe(32), "state": "queued", "created_at": time.time(),
                   "cancelled": False, "worker_id": None, "lease_id": None, "streams": [], "stream_bytes": 0}
            try:
                self.store.admit(req.quote_id, job, int(os.getenv("APERTURE_MAX_PENDING_TASKS", "100")))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "This payment channel already has an active task.")
            except ValueError as error:
                raise HTTPException(401 if str(error) == "quote_consumed" else 429, "Quote already consumed." if str(error) == "quote_consumed" else "Compute queue is full.")
            return self.execution_response(job)

    def execution_response(self, job):
        return {"status": job['state'], "task_id": job['task_id'], "task_access_token": job["access_token"],
                "quote_id": job["quote_id"], "code_sha256": job["code_sha256"],
                "burn_rate": job["rate_lamports"] / 1e9, "burn_rate_lamports": job["rate_lamports"],
                "max_cost_lamports": job["max_cost_lamports"], "max_runtime_seconds": job["max_runtime_seconds"],
                "complexity_score": job["analysis"].get("complexity_score"), "ai_analysis": job["analysis"]}

    def result_fingerprint(self, payload):
        return sha256_text(canonical_json({key: payload.get(key) for key in ("output", "full_log", "exit_code", "execution_time", "execution_backend", "isolation")}))

    async def settle(self, job):
        """The durable result remains retryable until the chain agrees."""
        if job["state"] == "completed":
            return job["receipt"]
        settlement = None
        if not self.demo_mode and job.get("start_intent"):
            try:
                settlement = await self.solana.stop_task(job["wallet"], job["task_hash"], job["agent_pubkey"], start_intent=job.get("prepared_start"))
            except Exception as error:
                job["last_settlement_error"] = type(error).__name__
            if not settlement:
                job["state"] = "settlement_pending"
                job["settlement_attempts"] = job.get("settlement_attempts", 0) + 1
                job["next_settlement_attempt"] = time.time() + min(30, 2 ** min(job["settlement_attempts"], 5))
                self.store.save_job(job)
                return None
        result = job.get("result", {})
        elapsed = min(float(result.get("execution_time", 0)), job["max_runtime_seconds"])
        charged = settlement.get("charged_lamports") if settlement else (0 if not job.get("start_intent") else None)
        evidence = {
            "receipt_version": 1, "task_id": job["task_id"], "task_hash": job["task_hash"],
            "quote_id": job["quote_id"], "owner_wallet": job["wallet"], "agent_pubkey": job["agent_pubkey"],
            "passport_version": job["passport_version"], "code_sha256": job["code_sha256"],
            "output_sha256": sha256_text(result.get("full_log", result.get("output", ""))),
            "source_hash": job["code_sha256"], "output_hash": sha256_text(result.get("full_log", result.get("output", ""))),
            "worker_id": job.get("worker_id"), "lease_id": job.get("lease_id"),
            "execution_status": result.get("execution_status", "failed"), "exit_code": result.get("exit_code"),
            "execution_time": elapsed, "execution_backend": result.get("execution_backend", "unknown"),
            "execution_mode": result.get("execution_backend", "unknown"),
            "isolation": result.get("isolation"), "rate_lamports": job["rate_lamports"],
            "max_cost_lamports": job["max_cost_lamports"], "max_runtime_seconds": job["max_runtime_seconds"],
            "charged_lamports": charged, "cost_sol": charged / 1e9 if charged is not None else None,
            "cost_is_exact": charged is not None, "settlement_type": "DEVNET" if settlement else "OFF_CHAIN" if job.get("start_intent") else "NOT_STARTED",
            "settlement_signature": settlement.get("signature") if settlement else None,
            "settlement_evidence": settlement.get("evidence") if settlement else None,
            "worker_receipt": result.get("worker_receipt"), "worker_signature": result.get("worker_signature"),
            "settled_at": int(time.time()), "attestation": "gateway-reported execution and canonical hashes; not a proof of faithful remote execution",
        }
        message = receipt_message(evidence)
        evidence["gateway_pubkey"] = str(self.solana.ai_signer.pubkey())
        evidence["gateway_signature"] = list(bytes(self.solana.ai_signer.sign_message(message.encode("utf-8"))))
        evidence["signed_message"] = message
        evidence["receipt_sha256"] = sha256_text(message)
        evidence["explorer_url"] = f"https://explorer.solana.com/tx/{evidence['settlement_signature']}?cluster=devnet" if evidence["settlement_signature"] else None
        evidence["status"] = "saved"
        job.update(state="completed", receipt=evidence, completed_at=time.time())
        self.store.save_job(job)
        return evidence

    async def recover_once(self, restart=False):
        async with self.lock:
            now = time.time()
            for job in self.store.list("jobs"):
                if job["state"] not in ACTIVE_STATES:
                    continue
                if job["state"] == "queued":
                    # A delegated policy can be revoked while the job waits.
                    agent = self.store.get("agents", job["agent_pubkey"]) if job["agent_pubkey"] != job["wallet"] else None
                    if now - job["created_at"] > int(os.getenv("APERTURE_QUEUE_TTL_SECONDS", "300")) or (agent and (agent["revoked"] or agent["expires_at"] <= now)):
                        job.update(cancelled=True, state="settlement_pending", result={"output": "QUEUE_EXPIRED_OR_AGENT_REVOKED", "full_log": "QUEUE_EXPIRED_OR_AGENT_REVOKED", "execution_status": "cancelled", "execution_time": 0})
                        self.store.save_job(job)
                        await self.settle(job)
                    continue
                if job["state"] == "settlement_pending":
                    if now >= job.get("next_settlement_attempt", 0):
                        await self.settle(job)
                    continue
                if restart or job["state"] == "starting" or now >= job.get("deadline_unix", 0):
                    job.update(cancelled=True, state="settlement_pending", result={"output": "EXECUTION_LEASE_EXPIRED", "full_log": "EXECUTION_LEASE_EXPIRED", "execution_status": "failed", "execution_time": max(0, min(now - job.get("started_at", now), job["max_runtime_seconds"]))})
                    self.store.save_job(job)
                    await self.settle(job)

    async def recovery_loop(self):
        while True:
            try:
                await self.recover_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                print(f"[RECOVERY] Retry after {type(error).__name__}")
            await asyncio.sleep(1)

    async def start(self):
        await self.recover_once(restart=True)
        self.recovery_task = asyncio.create_task(self.recovery_loop())

    async def close(self):
        if self.recovery_task:
            self.recovery_task.cancel()
            try:
                await self.recovery_task
            except asyncio.CancelledError:
                pass

    def _mount(self):
        router = self.router

        @router.post("/quotes")
        @router.post("/execute/challenge")
        async def quotes(req: QuoteRequest):
            return await self.issue_quote(req)

        @router.post("/execute")
        async def execute(req: ExecuteRequest):
            return await self.execute(req)

        @router.post("/agents/challenge")
        async def agent_challenge(req: PassportChallenge):
            self._valid_keys(req.owner, req.agent_pubkey)
            if req.capabilities != CAPABILITIES or req.max_cost_lamports > req.total_budget_lamports or req.expires_at <= int(time.time()) or req.expires_at > int(time.time()) + 366 * 86400:
                raise HTTPException(422, "Invalid agent capability, budget, or expiry policy.")
            existing = self.store.get("agents", req.agent_pubkey)
            if existing and existing["owner"] != req.owner:
                raise HTTPException(403, "Only the agent's registered owner may change its passport.")
            if req.action != "register" and not existing:
                raise HTTPException(404, "Agent passport not found.")
            policy = req.model_dump(exclude={"action"})
            policy["program_id"] = str(self.solana.program_id)
            policy["network"] = "off_chain" if self.demo_mode else "devnet"
            policy["version"] = (existing["version"] + 1) if existing else 1
            policy["metadata_hash"] = sha256_text(canonical_json(policy))
            nonce = secrets.token_urlsafe(32)
            expires = int(time.time()) + 90
            message = passport_message(req.action, policy, nonce, expires)
            challenge = {"nonce": nonce, "expires_at": expires, "action": req.action, "passport": policy, "message": message}
            if not self.demo_mode:
                chain = await self.solana.get_agent_passport(req.agent_pubkey)
                if chain and chain['owner'] != req.owner:
                    raise HTTPException(403, "The on-chain agent passport belongs to another owner.")
                # Recover an owner transaction that landed while a previous
                # API authorization expired or was lost. Never initialize an
                # already-created passport again.
                instruction_action = 'update' if req.action == 'register' and chain else req.action
                already_matches = chain and chain['revoked'] == (req.action == 'revoke') and (req.action == 'revoke' or all(chain[key] == policy[local] for key, local in (("metadata_hash", "metadata_hash"), ("max_cost_lamports", "max_cost_lamports"), ("max_runtime_seconds", "max_runtime_seconds"), ("valid_until", "expires_at"), ("total_budget_lamports", "total_budget_lamports"))))
                if not already_matches:
                    challenge["chain_instruction"] = self.solana.agent_instruction(instruction_action, policy)
                challenge['chain_already_matches'] = bool(already_matches)
            self.store.put("challenges", nonce, challenge)
            return challenge

        @router.post("/agents")
        async def authorize_agent(req: PassportAuthorization):
            async with self.lock:
                challenge = self.store.get("challenges", req.nonce)
                if not challenge or challenge["expires_at"] < int(time.time()) or not hmac.compare_digest(challenge["message"], req.message) or not verify_ed25519(challenge["passport"]["owner"], req.signature, req.message):
                    raise HTTPException(401, "Owner authorization is invalid or expired.")
                policy = dict(challenge["passport"])
                existing = self.store.get("agents", policy["agent_pubkey"])
                if existing and (existing["owner"] != policy["owner"] or policy["version"] != existing["version"] + 1):
                    raise HTTPException(409, "Passport changed after this authorization was issued.")
                policy["revoked"] = challenge["action"] == "revoke"
                if not self.demo_mode:
                    chain = await self.solana.get_agent_passport(policy["agent_pubkey"])
                    if not chain or chain["owner"] != policy["owner"] or chain["revoked"] != policy["revoked"] or (not policy["revoked"] and any(chain[key] != policy[local] for key, local in (("metadata_hash", "metadata_hash"), ("max_cost_lamports", "max_cost_lamports"), ("max_runtime_seconds", "max_runtime_seconds"), ("valid_until", "expires_at"), ("total_budget_lamports", "total_budget_lamports")))):
                        raise HTTPException(409, "Submit the matching owner-signed on-chain passport transaction first.")
                policy["attestation"] = "SOLANA_DEVNET" if not self.demo_mode else "OWNER_SIGNED_OFF_CHAIN"
                policy["owner_signature"] = req.signature
                policy["owner_signed_message"] = req.message
                try:
                    self.store.consume_challenge(req.nonce, policy)
                except ValueError:
                    raise HTTPException(401, "Owner authorization already consumed.")
                # Revocation also cancels existing tasks; the chain independently
                # stops additional accrual at revoked_at even if this gateway dies.
                if policy["revoked"]:
                    for job in self.store.list("jobs"):
                        if job["agent_pubkey"] == policy["agent_pubkey"] and job["state"] in ACTIVE_STATES:
                            job.update(cancelled=True, state="settlement_pending")
                            job.setdefault("result", {"output": "AGENT_REVOKED", "full_log": "AGENT_REVOKED", "execution_status": "cancelled", "execution_time": 0})
                            self.store.save_job(job)
                            await self.settle(job)
                return policy

        @router.get("/agents")
        async def agents(owner: str):
            return [item for item in self.store.list("agents") if item["owner"] == owner]

        @router.get("/agents/{agent_pubkey}")
        async def agent(agent_pubkey: str):
            item = self.store.get("agents", agent_pubkey)
            if not item:
                raise HTTPException(404, "Agent passport not found.")
            return {**item, "active": not item["revoked"] and item["expires_at"] > time.time()}

        @router.get("/get_task")
        async def get_task(worker_id: str = Depends(self.require_worker)):
            if not self.store.get('workers', worker_id):
                raise HTTPException(409, "Register this worker's stable signing key before claiming tasks.")
            await self.recover_once()
            async with self.lock:
                for job in self.store.list("jobs"):
                    if job["state"] != "queued":
                        continue
                    try:
                        policy = await self.passport(job["wallet"], job["agent_pubkey"], 0, job["max_runtime_seconds"])
                        if (policy["version"] if policy else 0) != job["passport_version"]:
                            raise HTTPException(403, "Delegation changed.")
                    except HTTPException:
                        job.update(cancelled=True, state="settlement_pending", result={"output": "AGENT_POLICY_CHANGED", "full_log": "AGENT_POLICY_CHANGED", "execution_status": "cancelled", "execution_time": 0})
                        self.store.save_job(job)
                        await self.settle(job)
                        continue
                    if not self.demo_mode:
                        channel = await self.solana.get_channel_state(job["wallet"])
                        if not channel or channel.get("effective_balance_lamports", channel["balance_lamports"]) < job["max_cost_lamports"] or channel["burn_rate_lamports"]:
                            job.update(cancelled=True, state="settlement_pending", result={"output": "PAYMENT_CHANNEL_UNAVAILABLE", "full_log": "PAYMENT_CHANNEL_UNAVAILABLE", "execution_status": "failed", "execution_time": 0})
                            self.store.save_job(job)
                            await self.settle(job)
                            continue
                    prepared = None
                    if not self.demo_mode:
                        try:
                            prepared = await self.solana.prepare_start_task(job["wallet"], job["task_hash"], job["code_sha256"], job["agent_pubkey"], job["rate_lamports"], job["max_cost_lamports"], job["effective_runtime_seconds"])
                        except Exception:
                            return {"task_id": None}
                    job.update(state="starting", worker_id=worker_id, lease_id=secrets.token_urlsafe(24), start_intent=True, prepared_start=prepared,
                               started_at=None, deadline_unix=None)
                    self.store.save_job(job)
                    start = None
                    if not self.demo_mode:
                        try:
                            start = await self.solana.send_prepared_start(prepared)
                        except Exception:
                            start = None
                        if not start:
                            # Uncertain submission is never replayed as new work.
                            job.update(state="settlement_pending", cancelled=True, result={"output": "START_CONFIRMATION_FAILED", "full_log": "START_CONFIRMATION_FAILED", "execution_status": "failed", "execution_time": 0})
                            self.store.save_job(job)
                            await self.settle(job)
                            return {"task_id": None}
                    if self.demo_mode:
                        started_at = time.time()
                        deadline_unix = int(started_at) + job["effective_runtime_seconds"]
                    else:
                        try:
                            receipt = await self.solana.get_task_receipt(job["task_hash"])
                            if (not receipt or receipt["settled"] or receipt["owner"] != job["wallet"]
                                    or receipt["agent_pubkey"] != job["agent_pubkey"]
                                    or receipt["source_hash"] != job["code_sha256"]
                                    or receipt["rate_lamports"] != job["rate_lamports"]
                                    or receipt["max_cost_lamports"] != job["max_cost_lamports"]):
                                raise ValueError("Confirmed task receipt does not match the admitted workload.")
                            started_at = receipt["started_at"]
                            deadline_unix = receipt["deadline"]
                            if (type(started_at) is not int or type(deadline_unix) is not int
                                    or deadline_unix <= started_at
                                    or deadline_unix > started_at + job["effective_runtime_seconds"]):
                                raise ValueError("Confirmed task receipt has invalid execution bounds.")
                        except Exception:
                            job.update(state="settlement_pending", cancelled=True, result={"output": "START_RECEIPT_UNAVAILABLE", "full_log": "START_RECEIPT_UNAVAILABLE", "execution_status": "failed", "execution_time": 0})
                            self.store.save_job(job)
                            await self.settle(job)
                            return {"task_id": None}
                    if time.time() >= deadline_unix:
                        elapsed = max(0, min(time.time() - started_at, job["effective_runtime_seconds"]))
                        job.update(state="settlement_pending", cancelled=True, started_at=started_at, deadline_unix=deadline_unix,
                                   result={"output": "EXECUTION_WINDOW_ELAPSED_BEFORE_DISPATCH", "full_log": "EXECUTION_WINDOW_ELAPSED_BEFORE_DISPATCH", "execution_status": "failed", "execution_time": elapsed})
                        self.store.save_job(job)
                        await self.settle(job)
                        return {"task_id": None}
                    job.update(state="running", start_signature=start, started_at=started_at, deadline_unix=deadline_unix)
                    self.store.save_job(job)
                    return {key: job[key] for key in ("task_id", "code", "wallet", "agent_pubkey", "quote_id", "lease_id", "code_sha256", "max_cost_lamports", "max_runtime_seconds", "deadline_unix")} | {"source_hash": job["code_sha256"], "execution_deadline": job["deadline_unix"]}
            return {"task_id": None}

        @router.post("/submit_result")
        async def submit_result(payload: dict, worker_id: str = Depends(self.require_worker)):
            async with self.lock:
                job = self.task(payload.get("task_id"), worker_id=worker_id)
                if payload.get("lease_id") != job.get("lease_id"):
                    raise HTTPException(409, "Result lease identity does not match.")
                output = payload.get("output", "")
                log = payload.get("full_log", output)
                exit_code = payload.get("exit_code", 0)
                duration = payload.get("execution_time", 0)
                if not isinstance(output, str) or not isinstance(log, str) or type(exit_code) is not int or type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0 or duration > job["max_runtime_seconds"] + 5:
                    raise HTTPException(422, "Invalid bounded execution result.")
                if max(len(output.encode("utf-8")), len(log.encode("utf-8"))) > int(os.getenv("APERTURE_MAX_LOG_BYTES_PER_TASK", "1000000")):
                    raise HTTPException(413, "Task output exceeds the configured limit.")
                if payload.get("code_sha256", payload.get("source_hash")) != job["code_sha256"] or payload.get("output_sha256", payload.get("output_hash")) != sha256_text(log):
                    raise HTTPException(422, "Canonical source/output hashes do not match.")
                worker = self.store.get("workers", worker_id)
                mode = payload.get("execution_mode", payload.get("execution_backend", "unknown"))
                expected_attestation = {
                    "domain": "aperture.worker.result.v1", "task_id": job["task_id"], "lease_id": job["lease_id"],
                    "source_hash": job["code_sha256"], "output_hash": sha256_text(log), "execution_mode": mode,
                    "execution_time_ms": round(duration * 1000), "exit_code": exit_code, "worker_id": worker_id,
                    "worker_pubkey": payload.get("worker_pubkey"), "agent_pubkey": job["agent_pubkey"], "quote_id": job["quote_id"],
                }
                try:
                    worker_signature = list(base58.b58decode(payload.get("worker_signature", "")))
                except (ValueError, TypeError):
                    worker_signature = []
                if not worker or worker["worker_pubkey"] != payload.get("worker_pubkey") or payload.get("worker_receipt") != expected_attestation or not verify_ed25519(worker["worker_pubkey"], worker_signature, receipt_bytes(expected_attestation).decode("utf-8")):
                    raise HTTPException(401, "A matching registered worker signature is required.")
                if job['cancelled']:
                    # A terminated worker still needs a durable acknowledgment
                    # to archive its outbox; it cannot replace the cancellation.
                    if job['state'] == 'completed':
                        return job['receipt']
                    receipt = await self.settle(job)
                    return receipt or JSONResponse(status_code=202, content={"status": "settlement_pending", "task_id": job["task_id"]})
                normalized = {"output": output, "full_log": log, "exit_code": exit_code, "execution_time": duration,
                              "execution_backend": mode, "isolation": payload.get("isolation"),
                              "worker_receipt": expected_attestation, "worker_signature": payload["worker_signature"]}
                fingerprint = self.result_fingerprint(normalized)
                if job.get("result_fingerprint"):
                    if not hmac.compare_digest(job["result_fingerprint"], fingerprint):
                        raise HTTPException(409, "A different result was already recorded for this lease.")
                    if job["state"] == "completed":
                        return job["receipt"]
                elif job["state"] != "running" or job["cancelled"]:
                    raise HTTPException(409, "This execution is already cancelled or concluded.")
                normalized["execution_status"] = "completed" if exit_code == 0 else "failed"
                job.update(state="settlement_pending", result=normalized, result_fingerprint=fingerprint)
                self.store.save_job(job)  # Result evidence commits before any RPC.
                receipt = await self.settle(job)
                return receipt or JSONResponse(status_code=202, content={"status": "settlement_pending", "task_id": job["task_id"]})

        @router.post("/stop/{task_id}")
        async def stop(task_id: str, access_token: Optional[str] = Query(default=None)):
            async with self.lock:
                job = self.task(task_id, token=access_token)
                if job["state"] == "completed":
                    return {"status": "stopped", "receipt": job["receipt"]}
                job.update(state="settlement_pending", cancelled=True)
                job.setdefault("result", {"output": "EXECUTION_ABORTED_BY_USER", "full_log": "EXECUTION_ABORTED_BY_USER", "execution_status": "cancelled", "execution_time": 0})
                self.store.save_job(job)
                receipt = await self.settle(job)
                return {"status": "stopped" if receipt else "settlement_pending", "tx_sig": receipt.get("settlement_signature") if receipt else None}

        @router.get("/worker_task_status/{task_id}")
        async def worker_status(task_id: str, worker_id: str = Depends(self.require_worker)):
            job = self.task(task_id, worker_id=worker_id)
            return {"task_id": task_id, "cancelled": job["cancelled"] or time.time() >= job.get("deadline_unix", float("inf")),
                    "terminal": job["state"] == "completed", "lease_id": job.get("lease_id"),
                    "deadline_unix": job.get("deadline_unix"), "execution_deadline": job.get("deadline_unix"), "max_runtime_seconds": job["max_runtime_seconds"]}

        @router.post("/stream_log")
        async def stream(chunk: StreamChunk, worker_id: str = Depends(self.require_worker)):
            job = self.task(chunk.task_id, worker_id=worker_id)
            if job["state"] != "running" or job["cancelled"] or chunk.node_id != worker_id or chunk.lease_id != job["lease_id"]:
                raise HTTPException(409, "Active worker lease is required.")
            size = sum(len(line.encode("utf-8")) for line in chunk.lines)
            if len(job["streams"]) + len(chunk.lines) > 10000 or job["stream_bytes"] + size > 1000000:
                raise HTTPException(413, "Stream output limit exceeded.")
            job["streams"].extend(chunk.lines)
            job["stream_bytes"] += size
            self.store.save_job(job)
            return {"status": "ok", "total_lines": len(job["streams"])}

        @router.get("/result/{task_id}")
        async def result(task_id: str, access_token: Optional[str] = Query(default=None)):
            job = self.task(task_id, token=access_token)
            return {"task_id": task_id, "status": "completed" if job["state"] == "completed" else job["state"],
                    "output": job.get("result", {}).get("output"), "receipt": job.get("receipt")}

        @router.get("/receipt/{task_id}")
        async def receipt(task_id: str, access_token: Optional[str] = Query(default=None)):
            job = self.task(task_id, token=access_token)
            if not job.get("receipt"):
                raise HTTPException(409, "Receipt awaits confirmed settlement.")
            return job["receipt"]

        @router.get("/stream_log/{task_id}")
        async def stream_result(task_id: str, offset: int = Query(default=0, ge=0), access_token: Optional[str] = Query(default=None)):
            job = self.task(task_id, token=access_token)
            return {"task_id": task_id, "lines": job["streams"][offset:], "next_offset": len(job["streams"]),
                    "is_completed": job["state"] == "completed", "task_status": job["state"],
                    "output": job.get("result", {}).get("output"), "receipt": job.get("receipt")}

        @router.get("/download/{task_id}")
        async def download(task_id: str, access_token: Optional[str] = Query(default=None)):
            job = self.task(task_id, token=access_token)
            if not job.get("result"):
                raise HTTPException(404, "Result not available yet.")
            return PlainTextResponse(job["result"]["full_log"], headers={"Content-Disposition": f"attachment; filename=aperture_log_{task_id}.txt"})
