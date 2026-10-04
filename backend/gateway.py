"""Spend-bounded admission, owner delegation, and crash-safe settlement."""
import asyncio
import hmac
import json
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
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, StrictInt, field_validator

from agent_identity import (CAPABILITIES, canonical_json, passport_message,
                            quote_message, receipt_message, sha256_text,
                            valid_public_key, verify_ed25519)
from ai_engine import MAX_SOURCE_BYTES, analyze_code_ast, calculate_ast_quote_rate
from state_store import ACTIVE_STATES, StateStore
from worker_identity import receipt_bytes
from security_config import worker_auth_is_configured, worker_id_is_valid, worker_token_is_configured
from artifact_store import ArtifactStore, MAX_INPUT_BYTES, MAX_JOB_INPUTS, validate_descriptor


def require_utf8_text(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                raise HTTPException(422, "Request text must be valid UTF-8.") from None
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return value


class Utf8Request(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def valid_utf8_text(cls, value):
        # Reject before validation errors echo an unencodable input into JSON.
        return require_utf8_text(value)


class SourceRequest(Utf8Request):
    code: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)

    @field_validator("code")
    @classmethod
    def bounded_utf8_source(cls, code):
        if not code.strip():
            raise ValueError("Source must contain a Python workload.")
        try:
            size = len(code.encode("utf-8"))
        except UnicodeEncodeError:
            raise ValueError("Source must be valid UTF-8.") from None
        if size > MAX_SOURCE_BYTES:
            raise ValueError(f"Source exceeds the {MAX_SOURCE_BYTES:,} UTF-8 byte limit.")
        return code


class WorkflowBinding(Utf8Request):
    model_config = {"extra": "forbid"}
    workflow_id: str = Field(pattern=r"^flow-[0-9a-f]{64}$")
    step_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class QuoteRequest(SourceRequest):
    wallet: str = Field(min_length=32, max_length=44)
    agent_pubkey: Optional[str] = Field(default=None, min_length=32, max_length=44)
    max_cost_lamports: int = Field(default=1_000_000, gt=0, le=1_000_000_000)
    max_runtime_seconds: int = Field(default=30, ge=1, le=180)
    job_version: Optional[Literal[1]] = None
    inputs: list[dict] = Field(default_factory=list, max_length=MAX_JOB_INPUTS)
    parameters: dict = Field(default_factory=dict)
    workflow: Optional[WorkflowBinding] = None


class ExecuteRequest(SourceRequest):
    quote_id: str = Field(min_length=16, max_length=128)
    wallet: str = Field(min_length=32, max_length=44)
    agent_pubkey: Optional[str] = Field(default=None, min_length=32, max_length=44)
    signature: list[int] = Field(min_length=64, max_length=64)
    message: str = Field(min_length=1, max_length=2048)
    job_version: Optional[Literal[1]] = None
    inputs: list[dict] = Field(default_factory=list, max_length=MAX_JOB_INPUTS)
    parameters: dict = Field(default_factory=dict)


class ObjectAuthorization(Utf8Request):
    owner: str = Field(min_length=32, max_length=44)
    agent_pubkey: str = Field(min_length=32, max_length=44)
    name: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,78}[A-Za-z0-9_-])?$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=MAX_INPUT_BYTES)
    issued_at: StrictInt = Field(gt=0)
    nonce: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    signature: list[StrictInt] = Field(min_length=64, max_length=64)


class ArtifactAuthorization(Utf8Request):
    name: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,78}[A-Za-z0-9_-])?$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=8 * 1024 * 1024)
    lease_id: str = Field(min_length=16, max_length=128)


class ObjectAccessAuthorization(Utf8Request):
    owner: str = Field(min_length=32, max_length=44)
    agent_pubkey: str = Field(min_length=32, max_length=44)
    issued_at: StrictInt = Field(gt=0)
    nonce: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    signature: list[StrictInt] = Field(min_length=64, max_length=64)


class ObjectReleaseAuthorization(ObjectAccessAuthorization):
    object_id: str = Field(pattern=r"^obj-[0-9a-f]{32}$")
    name: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,78}[A-Za-z0-9_-])?$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=MAX_INPUT_BYTES)


class PassportChallenge(Utf8Request):
    action: Literal["register", "update", "revoke"]
    owner: str = Field(min_length=32, max_length=44)
    agent_pubkey: str = Field(min_length=32, max_length=44)
    name: str = Field(default="Compute agent", min_length=1, max_length=80)
    max_cost_lamports: int = Field(default=1_000_000, gt=0, le=1_000_000_000)
    max_runtime_seconds: int = Field(default=30, ge=1, le=180)
    total_budget_lamports: int = Field(default=10_000_000, gt=0, le=100_000_000_000)
    expires_at: int = Field(gt=0)
    capabilities: list[str] = Field(default_factory=lambda: list(CAPABILITIES), min_length=1, max_length=1)


class PassportAuthorization(Utf8Request):
    nonce: str = Field(min_length=16, max_length=128)
    signature: list[int] = Field(min_length=64, max_length=64)
    message: str = Field(min_length=1, max_length=4096)


class PassportUsageAuthorization(Utf8Request):
    owner: str = Field(min_length=32, max_length=44)
    issued_at: int = Field(gt=0)
    nonce: str = Field(min_length=16, max_length=128)
    signature: list[int] = Field(min_length=64, max_length=64)


class AgentTaskListAuthorization(Utf8Request):
    owner: str = Field(min_length=32, max_length=44)
    agent_pubkey: str = Field(min_length=32, max_length=44)
    issued_at: StrictInt = Field(gt=0)
    nonce: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    limit: StrictInt = Field(default=20, ge=1, le=50)
    cursor: Optional[str] = Field(default=None, min_length=37, max_length=37,
                                  pattern=r"^task-[0-9a-f]{32}$")
    signature: list[StrictInt] = Field(min_length=64, max_length=64)


class AgentTaskResumeAuthorization(Utf8Request):
    owner: str = Field(min_length=32, max_length=44)
    agent_pubkey: str = Field(min_length=32, max_length=44)
    task_id: str = Field(min_length=37, max_length=37, pattern=r"^task-[0-9a-f]{32}$")
    issued_at: StrictInt = Field(gt=0)
    nonce: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    signature: list[StrictInt] = Field(min_length=64, max_length=64)


class StreamChunk(Utf8Request):
    task_id: str
    lines: list[str] = Field(max_length=10_000)
    node_id: Optional[str] = None
    lease_id: Optional[str] = None


def configured_task_limit(name, default):
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None and raw.strip() else default
    except ValueError:
        raise HTTPException(503, f"{name} must be a positive integer.") from None
    if value < 1 or value > 100_000:
        raise HTTPException(503, f"{name} must be between 1 and 100000.")
    return value


def effective_runtime_limit(task):
    maximum = task.get("max_runtime_seconds")
    budget = task.get("max_cost_lamports")
    rate = task.get("rate_lamports")
    if (type(maximum) is not int or maximum < 1
            or type(budget) is not int or budget < 1
            or type(rate) is not int or rate < 1 or budget < rate):
        return 0
    return min(maximum, budget // rate)


class Gateway:
    def __init__(self, solana, demo_mode, worker_token, store=None, worker_credentials=None):
        from compute_profiles import csv_rate
        self.csv_tariff = csv_rate()
        self.solana = solana
        self.demo_mode = demo_mode
        self.worker_token = (worker_token or "").strip()
        self.worker_credentials = dict(worker_credentials or {})
        self.worker_auth_configured = worker_auth_is_configured(self.worker_credentials, self.worker_token)
        self.store = store or StateStore(os.getenv("APERTURE_STATE_DB", str(Path(__file__).parent / "data" / "gateway.sqlite3")))
        self.lock = asyncio.Lock()
        self.router = APIRouter()
        self.recovery_task = None
        self._objects = None
        self._mount()

    @property
    def objects(self):
        if self._objects is None:
            database = self.store.connection.execute("PRAGMA database_list").fetchone()[2]
            root = os.getenv("APERTURE_OBJECT_STORE")
            root = root or (str(Path(database).parent / (Path(database).stem + "-objects")) if database else None)
            self._objects = ArtifactStore(root)
        return self._objects

    def job_manifest(self, req, *, resolve=True):
        if req.job_version is None and not req.inputs and not req.parameters:
            return None
        if req.job_version != 1:
            raise HTTPException(422, "Data jobs require job_version=1.")
        try:
            inputs = sorted([validate_descriptor(item) for item in req.inputs], key=lambda item: item["name"])
            if len({item["name"].casefold() for item in inputs}) != len(inputs) or sum(item["size_bytes"] for item in inputs) > MAX_INPUT_BYTES:
                raise ValueError("Job input names must be unique and total size must not exceed 64 MiB.")
            encoded = json.dumps(req.parameters, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > 32_000:
                raise ValueError("Job parameters exceed 32,000 UTF-8 bytes.")
            if resolve:
                for item in inputs:
                    self.objects.resolve(item, owner=req.wallet, agent=req.agent_pubkey or req.wallet)
            return {"version": 1, "runtime": "python", "source_sha256": sha256_text(req.code),
                    "inputs": inputs, "parameters": req.parameters}
        except (ValueError, PermissionError, OSError, RecursionError) as error:
            raise HTTPException(422, str(error)) from None

    def require_worker(self, x_aperture_worker_token: Optional[str] = Header(default=None), x_aperture_worker_id: Optional[str] = Header(default=None)):
        if not worker_id_is_valid(x_aperture_worker_id):
            raise HTTPException(401, "Worker identity is required.")
        if self.worker_credentials:
            expected_token = self.worker_credentials.get(x_aperture_worker_id)
            if not expected_token:
                raise HTTPException(401, "Invalid worker credentials.")
        else:
            expected_token = self.worker_token
        if not worker_token_is_configured(expected_token):
            raise HTTPException(503, "Worker authentication is not configured.")
        if not x_aperture_worker_token or not hmac.compare_digest(x_aperture_worker_token, expected_token):
            raise HTTPException(401, "Invalid worker credentials.")
        return x_aperture_worker_id

    def task(self, task_id, token=None, worker_id=None):
        job = self.store.get("jobs", task_id)
        if not job or (token is not None and not hmac.compare_digest(job["access_token"], token)) or (worker_id is not None and job.get("worker_id") != worker_id):
            raise HTTPException(404, "Task not found.")
        if token is None and worker_id is None:
            raise HTTPException(404, "Task access token is required.")
        return job

    def require_task_token(self, x_aperture_task_token: Optional[str] = Header(default=None, alias="X-Aperture-Task-Token")):
        if not x_aperture_task_token:
            raise HTTPException(404, "Task not found.")
        return x_aperture_task_token

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
        jobs = self.store.list_active_jobs(agent_pubkey=agent)
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

    async def passport_allowance_summary(self, item):
        """Return usage from the same ledger that enforces this passport's allowance."""
        source = "gateway_ledger" if self.demo_mode else "solana_devnet"
        try:
            if self.demo_mode:
                spent = self.store.spent_for_agent(item["agent_pubkey"])
                reserved = sum(
                    job["max_cost_lamports"]
                    for job in self.store.list_active_jobs(agent_pubkey=item["agent_pubkey"])
                )
                total = item["total_budget_lamports"]
            else:
                chain = await self.solana.get_agent_passport(item["agent_pubkey"])
                policy_matches = chain and chain.get("owner") == item["owner"] \
                    and chain.get("metadata_hash") == item["metadata_hash"] \
                    and chain.get("max_cost_lamports") == item["max_cost_lamports"] \
                    and chain.get("max_runtime_seconds") == item["max_runtime_seconds"] \
                    and chain.get("valid_until") == item["expires_at"] \
                    and chain.get("total_budget_lamports") == item["total_budget_lamports"] \
                    and chain.get("revoked") == bool(item["revoked"])
                if not policy_matches:
                    raise ValueError("The on-chain passport is missing or differs from the saved policy.")
                spent = chain["spent_lamports"]
                reserved = chain["reserved_lamports"]
                total = chain["total_budget_lamports"]

            if any(type(value) is not int or value < 0 for value in (spent, reserved, total)):
                raise ValueError("The passport allowance counters are invalid.")
            return {
                "allowance_status": "available",
                "allowance_source": source,
                "spent_lamports": spent,
                "reserved_lamports": reserved,
                "remaining_lamports": max(0, total - spent - reserved),
            }
        except Exception:
            # Never turn an RPC or stale-policy failure into a misleading zero balance.
            return {
                "allowance_status": "unavailable",
                "allowance_source": source,
                "spent_lamports": None,
                "reserved_lamports": None,
                "remaining_lamports": None,
            }

    async def issue_quote(self, req):
        agent = req.agent_pubkey or req.wallet
        self._valid_keys(req.wallet, agent)
        passport = await self.passport(req.wallet, agent, req.max_cost_lamports, req.max_runtime_seconds)
        manifest = self.job_manifest(req)
        audit = analyze_code_ast(req.code)
        if audit.get("security") == "DANGEROUS":
            raise HTTPException(403, audit.get("reason", "Source policy rejected workload."))
        complexity = audit.get('cpu', 20) + audit.get('ram', 15)
        from compute_profiles import source_profile
        profile = source_profile(req.code)
        rate = self.csv_tariff if profile else max(1, int(round(calculate_ast_quote_rate(complexity) * 1_000_000_000)))
        analysis = {'security': 'SAFE', 'status': 'success', 'complexity_score': complexity,
                    'predicted_sec': None if profile else audit.get('predicted_sec', 3), 'scores': audit,
                    'calculated_rate_sol_sec': rate / 1e9, 'calculated_rate_lamports_sec': rate,
                    'sol_market_price': None, 'reason': audit.get('reason'),
                    'pricing': 'published_cpu_tariff_v1' if profile else 'deterministic_ast_lamports_v1',
                    'compute_profile': profile}
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
        if manifest is not None:
            manifest_text = canonical_json(manifest)
            quote.update(workload=manifest, workload_sha256=sha256_text(manifest_text), workload_canonical=manifest_text)
        if req.workflow is not None:
            quote["workflow"] = req.workflow.model_dump()
            from workflow_inbox import validate_bound_step
            validate_bound_step(self, quote, req.code)
        quote["message"] = quote_message(quote)
        async with self.lock:
            # RPC and passport checks can yield. Recheck retained input bytes while
            # holding the same lock used by release, then publish the authorization.
            if manifest is not None:
                self.job_manifest(req)
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
            manifest = self.job_manifest(req, resolve=False)
            if manifest != quote.get("workload"):
                raise HTTPException(401, "Job inputs or parameters differ from the signed authorization.")
            if not verify_ed25519(agent, req.signature, req.message):
                raise HTTPException(401, "Invalid agent signature.")
            existing = self.store.job_for_quote(req.quote_id)
            if existing:
                return self.execution_response(existing)
            if manifest is not None:
                self.job_manifest(req)
            if quote['expires_at'] < int(time.time()):
                raise HTTPException(401, "Quote expired. Request a fresh quote.")
            if "workflow" in quote:
                from workflow_inbox import validate_bound_step
                validate_bound_step(self, quote, req.code)
            passport = await self.passport(req.wallet, agent, quote["max_cost_lamports"], quote["max_runtime_seconds"])
            if (passport["version"] if passport else 0) != quote["passport_version"]:
                raise HTTPException(403, "Agent policy changed after this quote was issued.")
            if not self.demo_mode:
                channel = await self.solana.get_channel_state(req.wallet)
                if not channel or channel.get("effective_balance_lamports", channel["balance_lamports"]) < quote["max_cost_lamports"] or channel["burn_rate_lamports"]:
                    raise HTTPException(409, "Fund an idle compatible payment channel to cover the maximum authorized cost.")
            task_id = "task-" + uuid.uuid4().hex
            job = {**quote, "task_id": task_id, "task_hash": sha256_text(task_id), "code": req.code,
                   "agent_signature": req.signature, "access_token": secrets.token_urlsafe(32), "state": "queued", "created_at": time.time(),
                   "cancelled": False, "worker_id": None, "lease_id": None, "streams": [], "stream_bytes": 0}
            try:
                max_pending = configured_task_limit("APERTURE_MAX_PENDING_TASKS", 100)
                max_active = configured_task_limit("APERTURE_MAX_ACTIVE_TASKS", 200)
                self.store.admit(req.quote_id, job, max_pending, max_active)
            except sqlite3.IntegrityError:
                raise HTTPException(409, "This payment channel already has an active task.")
            except ValueError as error:
                reason = str(error)
                if reason == "quote_consumed":
                    raise HTTPException(401, "Quote already consumed.")
                if reason == "active_tasks_full":
                    raise HTTPException(429, "Gateway active task capacity is full; retry shortly.")
                if reason == "queue_full":
                    raise HTTPException(429, "Compute queue is full; retry shortly.")
                if reason in {"workflow_stopped", "workflow_step_admitted"}:
                    raise HTTPException(409, "Assigned workflow was stopped or this step already has a retained admission.") from None
                raise HTTPException(503, "Task admission capacity configuration is invalid.") from error
            return self.execution_response(job)

    def execution_response(self, job):
        return {"status": job['state'], "task_id": job['task_id'], "task_access_token": job["access_token"],
                "quote_id": job["quote_id"], "code_sha256": job["code_sha256"],
                "burn_rate": job["rate_lamports"] / 1e9, "burn_rate_lamports": job["rate_lamports"],
                "max_cost_lamports": job["max_cost_lamports"], "max_runtime_seconds": job["max_runtime_seconds"],
                "complexity_score": job["analysis"].get("complexity_score"), "ai_analysis": job["analysis"]}

    @staticmethod
    def worker_task_payload(job):
        fields = ("task_id", "code", "wallet", "agent_pubkey", "quote_id", "lease_id",
                  "code_sha256", "max_cost_lamports", "max_runtime_seconds", "deadline_unix")
        return {key: job[key] for key in fields} | {
            "source_hash": job["code_sha256"], "execution_deadline": job["deadline_unix"],
            **({key: job[key] for key in ("workload", "workload_sha256")} if "workload" in job else {}),
        }

    def result_fingerprint(self, payload):
        fields = ("output", "full_log", "exit_code", "execution_time", "execution_backend", "isolation")
        if "artifacts" in payload:
            fields += ("artifacts",)
        return sha256_text(canonical_json({key: payload.get(key) for key in fields}))

    def cancelled_result(self, job, message):
        started_at = job.get("started_at")
        elapsed = 0.0
        if isinstance(started_at, (int, float)) and not isinstance(started_at, bool):
            elapsed = min(max(0.0, time.time() - started_at), float(effective_runtime_limit(job)))
        return {
            "output": message,
            "full_log": message,
            "execution_status": "cancelled",
            "execution_time": elapsed,
        }

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
        elapsed = min(float(result.get("execution_time", 0)), effective_runtime_limit(job))
        charged = settlement.get("charged_lamports") if settlement else (0 if not job.get("start_intent") else None)
        if settlement and settlement.get("evidence") == "expired_unlanded_start_transaction":
            settlement_type = "NOT_STARTED"
        elif settlement:
            settlement_type = "DEVNET"
        else:
            settlement_type = "OFF_CHAIN" if job.get("start_intent") else "NOT_STARTED"
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
            "cost_is_exact": charged is not None, "settlement_type": settlement_type,
            "settlement_signature": settlement.get("signature") if settlement else None,
            "settlement_evidence": settlement.get("evidence") if settlement else None,
            "worker_receipt": result.get("worker_receipt"), "worker_signature": result.get("worker_signature"),
            "settled_at": int(time.time()), "attestation": "gateway-reported execution and canonical hashes; not a proof of faithful remote execution",
        }
        if "workload" in job:
            evidence.update(workload_sha256=job["workload_sha256"], artifacts=result.get("artifacts", []))
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
            for job in self.store.list_active_jobs():
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
                    started_at = job.get("started_at")
                    elapsed = 0.0
                    if isinstance(started_at, (int, float)) and not isinstance(started_at, bool):
                        elapsed = min(max(0.0, now - started_at), float(effective_runtime_limit(job)))
                    job.update(cancelled=True, state="settlement_pending", result={"output": "EXECUTION_LEASE_EXPIRED", "full_log": "EXECUTION_LEASE_EXPIRED", "execution_status": "failed", "execution_time": elapsed})
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
        if self._objects is not None:
            self._objects.close()

    def authorize_agent_task_read(self, *, owner, agent_pubkey, issued_at,
                                  nonce, signature, action, task_id=None,
                                  limit=None, cursor=None, owner_control=False):
        """Authenticate a short-lived, one-use request signed by the task agent."""
        self._valid_keys(owner, agent_pubkey)
        now = int(time.time())
        if type(issued_at) is not int or issued_at < now - 60 or issued_at > now + 30:
            raise HTTPException(401, "Agent task authorization expired; sign a fresh request.")
        if (not isinstance(nonce, str) or not 16 <= len(nonce) <= 128
                or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in nonce)):
            raise HTTPException(422, "Agent task authorization nonce is invalid.")
        if (not isinstance(signature, list) or len(signature) != 64
                or any(type(value) is not int or value < 0 or value > 255 for value in signature)):
            raise HTTPException(422, "Agent signature must contain 64 bytes.")

        domain = "Aperture owner control v1" if owner_control else "Aperture agent task access v1"
        message = domain + "\naudience:aperture-gateway\n" + canonical_json({
            "action": action, "owner": owner, "agent_pubkey": agent_pubkey,
            "issued_at": issued_at, "nonce": nonce, "task_id": task_id,
            "limit": limit, "program_id": str(self.solana.program_id),
            "gateway_pubkey": str(self.solana.ai_signer.pubkey()),
            "network": "off_chain" if self.demo_mode else "devnet",
            "cursor": cursor,
        })
        if not verify_ed25519(owner if owner_control else agent_pubkey, signature, message):
            raise HTTPException(401, "Agent authorization for task access is invalid.")
        try:
            self.store.consume_read_nonce(
                nonce, issued_at + 61, scope="owner-control" if owner_control else "agent-task-access"
            )
        except ValueError as error:
            if str(error) == "challenge_capacity":
                raise HTTPException(429, "Signed request capacity is full; retry after existing authorizations expire.") from None
            raise HTTPException(401, "Agent authorization has already been used; sign a new request.") from None

    @staticmethod
    def recovery_task_summary(job):
        receipt = job.get("receipt") or {}
        result = job.get("result") or {}
        return {
            "task_id": job["task_id"],
            "status": "completed" if job.get("state") == "completed" else job.get("state", "unknown"),
            "created_at": job.get("created_at"),
            "quote_id": job.get("quote_id"),
            "code_sha256": job.get("code_sha256"),
            "max_cost_lamports": job.get("max_cost_lamports"),
            "max_runtime_seconds": job.get("max_runtime_seconds"),
            "execution_status": receipt.get("execution_status", result.get("execution_status")),
            "settlement_type": receipt.get("settlement_type"),
            "charged_lamports": receipt.get("charged_lamports"),
            "settlement_signature": receipt.get("settlement_signature"),
            "receipt_available": bool(receipt),
        }

    def _mount(self):
        router = self.router
        from owner_workspace import mount_owner_workspace
        mount_owner_workspace(self)
        from workflow_inbox import mount_workflow_inbox
        mount_workflow_inbox(self)

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
            try:
                self.store.put("challenges", nonce, challenge)
            except ValueError as error:
                if str(error) == "challenge_capacity":
                    raise HTTPException(429, "Signed request capacity is full; retry after existing authorizations expire.") from None
                raise
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
                    for job in self.store.list_active_jobs(agent_pubkey=policy["agent_pubkey"]):
                        if job["agent_pubkey"] == policy["agent_pubkey"] and job["state"] in ACTIVE_STATES:
                            job.update(cancelled=True, state="settlement_pending")
                            job.setdefault("result", self.cancelled_result(job, "AGENT_REVOKED"))
                            self.store.save_job(job)
                            await self.settle(job)
                return policy

        @router.post("/agents/usage")
        async def agents_usage(req: PassportUsageAuthorization):
            self._valid_keys(req.owner)
            now = int(time.time())
            if req.issued_at < now - 60 or req.issued_at > now + 30:
                raise HTTPException(401, "Allowance authorization expired; sign a fresh request.")
            if any(type(value) is not int or value < 0 or value > 255 for value in req.signature):
                raise HTTPException(422, "Wallet signature must contain 64 bytes.")
            message = "Aperture agent allowance read v1\naudience:aperture-gateway\n" + canonical_json({
                "owner": req.owner, "issued_at": req.issued_at, "nonce": req.nonce,
            })
            if not verify_ed25519(req.owner, req.signature, message):
                raise HTTPException(401, "Wallet authorization for allowance data is invalid.")
            try:
                self.store.consume_read_nonce(req.nonce, req.issued_at + 61)
            except ValueError as error:
                if str(error) == "challenge_capacity":
                    raise HTTPException(429, "Signed request capacity is full; retry after existing authorizations expire.") from None
                raise HTTPException(401, "Wallet authorization has already been used; sign a new request.") from None
            items = [item for item in self.store.list("agents") if item["owner"] == req.owner]
            semaphore = asyncio.Semaphore(8)

            async def with_allowance(item):
                async with semaphore:
                    allowance = await self.passport_allowance_summary(item)
                return {**item, **allowance}

            return await asyncio.gather(*(with_allowance(item) for item in items))

        @router.post("/agents/tasks/list")
        async def list_agent_tasks(req: AgentTaskListAuthorization):
            self.authorize_agent_task_read(
                owner=req.owner, agent_pubkey=req.agent_pubkey,
                issued_at=req.issued_at, nonce=req.nonce,
                signature=req.signature, action="list", limit=req.limit,
                cursor=req.cursor,
            )
            jobs = self.store.list_agent_jobs(
                req.owner, req.agent_pubkey, req.limit + 1, cursor=req.cursor
            )
            has_more = len(jobs) > req.limit
            page = jobs[:req.limit]
            return {
                "tasks": [self.recovery_task_summary(job) for job in page],
                "next_cursor": page[-1]["task_id"] if has_more and page else None,
            }

        @router.post("/agents/tasks/resume")
        async def resume_agent_task(req: AgentTaskResumeAuthorization):
            self.authorize_agent_task_read(
                owner=req.owner, agent_pubkey=req.agent_pubkey,
                issued_at=req.issued_at, nonce=req.nonce,
                signature=req.signature, action="resume", task_id=req.task_id,
            )
            job = self.store.get("jobs", req.task_id)
            if (not job or job.get("wallet") != req.owner
                    or job.get("agent_pubkey") != req.agent_pubkey):
                raise HTTPException(404, "Task not found.")
            quote = {key: job[key] for key in (
                "quote_id", "wallet", "agent_pubkey", "code_sha256", "rate_lamports",
                "max_cost_lamports", "max_runtime_seconds", "expires_at", "passport_version",
                "program_id", "network", "gateway_pubkey", "treasury",
            )}
            quote.update({
                "effective_runtime_seconds": job["effective_runtime_seconds"],
                "analysis": job["analysis"], "message": job["message"],
            })
            if "workload" in job:
                quote.update(workload=job["workload"], workload_sha256=job["workload_sha256"])
                if "workload_canonical" in job:
                    quote["workload_canonical"] = job["workload_canonical"]
            if "workflow" in job:
                quote["workflow"] = job["workflow"]
            return {
                **self.recovery_task_summary(job),
                "task_access_token": job["access_token"],
                "quote": quote,
                "agent_signature": job.get("agent_signature"),
            }

        @router.get("/agents")
        async def unsigned_agents_read():
            raise HTTPException(405, "Agent passport reads require an owner-signed POST to /agents/usage.")

        @router.get("/agents/{agent_pubkey}")
        async def unsigned_agent_read(agent_pubkey: str):
            raise HTTPException(405, "Agent passport reads require an owner-signed POST to /agents/usage.")

        @router.get("/get_task")
        async def get_task(worker_id: str = Depends(self.require_worker)):
            if not self.store.get('workers', worker_id):
                raise HTTPException(409, "Register this worker's stable signing key before claiming tasks.")
            await self.recover_once()
            async with self.lock:
                active_jobs = self.store.list_active_jobs()
                # A worker may lose the response after a claim was persisted.
                # Recover its original lease before assigning any new workload.
                leases = [job for job in active_jobs if job.get("worker_id") == worker_id]
                if leases:
                    job = leases[0]
                    if (len(leases) == 1 and job["state"] == "running"
                            and not job.get("cancelled") and time.time() < job["deadline_unix"]):
                        return self.worker_task_payload(job)
                    return {"task_id": None}
                for job in active_jobs:
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
                    return self.worker_task_payload(job)
            return {"task_id": None}

        @router.post("/submit_result")
        async def submit_result(payload: dict, worker_id: str = Depends(self.require_worker)):
            require_utf8_text(payload)
            async with self.lock:
                job = self.task(payload.get("task_id"), worker_id=worker_id)
                if payload.get("lease_id") != job.get("lease_id"):
                    raise HTTPException(409, "Result lease identity does not match.")
                output = payload.get("output", "")
                log = payload.get("full_log", output)
                exit_code = payload.get("exit_code", 0)
                duration = payload.get("execution_time", 0)
                runtime_limit = effective_runtime_limit(job)
                if not isinstance(output, str) or not isinstance(log, str) or type(exit_code) is not int or type(duration) not in (int, float) or not math.isfinite(duration) or runtime_limit < 1 or duration < 0 or duration > runtime_limit:
                    raise HTTPException(422, "Invalid bounded execution result.")
                if output != log:
                    raise HTTPException(422, "Displayed output must match the signed full log.")
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
                artifacts = payload.get("artifacts", [])
                if "workload" in job:
                    if (payload.get("workload_sha256") != job["workload_sha256"]
                            or not isinstance(artifacts, list) or len(artifacts) > 16):
                        raise HTTPException(422, "Job result does not match its authorized manifest.")
                    try:
                        artifacts = [validate_descriptor(item) for item in artifacts]
                        if len({item["name"].casefold() for item in artifacts}) != len(artifacts):
                            raise ValueError("Artifact names must be unique.")
                        for item in artifacts:
                            if not (job["state"] == "completed" and job.get("result_fingerprint")):
                                self.objects.resolve(item, owner=job["wallet"], agent=job["agent_pubkey"], task_id=job["task_id"])
                    except (ValueError, PermissionError, OSError, KeyError, TypeError) as error:
                        raise HTTPException(422, "Invalid job artifact manifest.") from error
                    expected_attestation.update(workload_sha256=job["workload_sha256"], artifacts=artifacts)
                elif artifacts:
                    raise HTTPException(422, "Artifact results require a data job authorization.")
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
                if "workload" in job:
                    normalized["artifacts"] = artifacts
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
        async def stop(task_id: str, access_token: str = Depends(self.require_task_token)):
            async with self.lock:
                job = self.task(task_id, token=access_token)
                if job["state"] == "completed":
                    return {"status": "stopped", "receipt": job["receipt"]}
                job.update(state="settlement_pending", cancelled=True)
                job.setdefault("result", self.cancelled_result(job, "EXECUTION_ABORTED_BY_USER"))
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
        async def result(task_id: str, access_token: str = Depends(self.require_task_token)):
            job = self.task(task_id, token=access_token)
            return {"task_id": task_id, "status": "completed" if job["state"] == "completed" else job["state"],
                    "output": job.get("result", {}).get("output"), "receipt": job.get("receipt")}

        @router.get("/receipt/{task_id}")
        async def receipt(task_id: str, access_token: str = Depends(self.require_task_token)):
            job = self.task(task_id, token=access_token)
            if not job.get("receipt"):
                raise HTTPException(409, "Receipt awaits confirmed settlement.")
            return job["receipt"]

        @router.get("/stream_log/{task_id}")
        async def stream_result(task_id: str, offset: int = Query(default=0, ge=0), access_token: str = Depends(self.require_task_token)):
            job = self.task(task_id, token=access_token)
            return {"task_id": task_id, "lines": job["streams"][offset:], "next_offset": len(job["streams"]),
                    "is_completed": job["state"] == "completed", "task_status": job["state"],
                    "output": job.get("result", {}).get("output"), "receipt": job.get("receipt")}

        @router.get("/download/{task_id}")
        async def download(task_id: str, access_token: str = Depends(self.require_task_token)):
            job = self.task(task_id, token=access_token)
            if not job.get("result"):
                raise HTTPException(404, "Result not available yet.")
            return PlainTextResponse(job["result"]["full_log"], headers={"Content-Disposition": f"attachment; filename=aperture_log_{task_id}.txt"})

        @router.post("/objects/authorize")
        async def authorize_object(req: ObjectAuthorization):
            async with self.lock:
                self.authorize_agent_task_read(owner=req.owner, agent_pubkey=req.agent_pubkey,
                    issued_at=req.issued_at, nonce=req.nonce, signature=req.signature,
                    action="upload-object", task_id=req.sha256, limit=req.size_bytes, cursor=req.name)
                await self.passport(req.owner, req.agent_pubkey, 1, 1)
                try:
                    return self.objects.authorize(owner=req.owner, agent=req.agent_pubkey,
                        name=req.name, digest=req.sha256, size=req.size_bytes)
                except ValueError as error:
                    raise HTTPException(413, str(error)) from None

        @router.put("/objects/{object_id}")
        async def upload_object(object_id: str, request: Request,
                                token: Optional[str] = Header(default=None, alias="X-Aperture-Upload-Token")):
            try:
                row = self.objects.upload_authorization(object_id, token)
                # Valid worker outputs have their own per-object bucket. Input staging
                # cannot consume a result's publication window or execution deadline.
                limiter = getattr(self, "object_rate_limiter", None)
                if limiter is not None:
                    if row[9] is None:
                        limiter("object-input", row[1] + ":" + row[2], 30)
                    else:
                        limiter("object-result", object_id, 30)
                return await self.objects.upload(object_id, token, request)
            except PermissionError:
                raise HTTPException(401, "Invalid object upload capability.") from None
            except ValueError as error:
                raise HTTPException(422, str(error)) from None

        @router.post("/objects/usage")
        async def object_usage(req: ObjectAccessAuthorization):
            self.authorize_agent_task_read(owner=req.owner, agent_pubkey=req.agent_pubkey,
                issued_at=req.issued_at, nonce=req.nonce, signature=req.signature, action="object-usage")
            return self.objects.usage(owner=req.owner, agent=req.agent_pubkey)

        @router.post("/objects/release")
        async def release_object(req: ObjectReleaseAuthorization):
            async with self.lock:
                self.authorize_agent_task_read(owner=req.owner, agent_pubkey=req.agent_pubkey,
                    issued_at=req.issued_at, nonce=req.nonce, signature=req.signature,
                    action="release-object", task_id=req.object_id, limit=req.size_bytes, cursor=req.name + ":" + req.sha256)
                reference = {key: getattr(req, key) for key in ("object_id", "name", "sha256", "size_bytes")}
                try:
                    try:
                        row = self.objects.get(req.object_id)
                    except ValueError:
                        return self.objects.release(reference, owner=req.owner, agent=req.agent_pubkey)
                    if row[1:3] != (req.owner, req.agent_pubkey):
                        raise PermissionError("Object belongs to another execution identity.")
                    active = self.store.list_active_jobs()
                    if any(job["task_id"] == row[9] or any(item["object_id"] == req.object_id
                        for item in job.get("workload", {}).get("inputs", [])) for job in active):
                        raise HTTPException(409, "Object is still required by an active task.")
                    if any(quote["expires_at"] >= time.time() and any(item["object_id"] == req.object_id
                        for item in quote.get("workload", {}).get("inputs", []))
                        for quote in self.store.list_unused_quotes()):
                        raise HTTPException(409, "Object is bound to an unexpired unused quote.")
                    from workflow_inbox import workflow_summary
                    if any(workflow_summary(self, flow)["status"] not in {"completed", "failed", "stopped", "archived"}
                        and any(item.get("object_id") == req.object_id for step in flow["plan"]["steps"] for item in step["inputs"])
                        for flow in self.store.assigned_workflows(req.owner, req.agent_pubkey)):
                        raise HTTPException(409, "Object is still required by an approved agent workflow; stop it first.")
                    return self.objects.release(reference, owner=req.owner, agent=req.agent_pubkey)
                except PermissionError:
                    raise HTTPException(403, "Object belongs to another execution identity.") from None
                except ValueError as error:
                    raise HTTPException(409, str(error)) from None

        @router.get("/tasks/{task_id}/inputs/{object_id}")
        async def worker_input(task_id: str, object_id: str,
                               lease: Optional[str] = Header(default=None, alias="X-Aperture-Lease"),
                               worker_id: str = Depends(self.require_worker)):
            job = self.task(task_id, worker_id=worker_id)
            if job["state"] != "running" or job.get("cancelled") or lease != job.get("lease_id"):
                raise HTTPException(409, "An active worker lease is required.")
            item = next((item for item in job.get("workload", {}).get("inputs", []) if item["object_id"] == object_id), None)
            if item is None:
                raise HTTPException(404, "Job input not found.")
            path = self.objects.resolve(item, owner=job["wallet"], agent=job["agent_pubkey"])
            return FileResponse(path, media_type="application/octet-stream")

        @router.post("/tasks/{task_id}/artifacts/authorize")
        async def authorize_artifact(task_id: str, req: ArtifactAuthorization,
                                     worker_id: str = Depends(self.require_worker)):
            async with self.lock:
                job = self.task(task_id, worker_id=worker_id)
                if "workload" not in job or job["state"] != "running" or job.get("cancelled") or req.lease_id != job.get("lease_id"):
                    raise HTTPException(409, "An active data job lease is required.")
                try:
                    return self.objects.authorize(owner=job["wallet"], agent=job["agent_pubkey"],
                        name=req.name, digest=req.sha256, size=req.size_bytes, task_id=task_id)
                except ValueError as error:
                    raise HTTPException(413, str(error)) from None

        @router.get("/tasks/{task_id}/artifacts/{object_id}")
        async def download_artifact(task_id: str, object_id: str,
                                    access_token: str = Depends(self.require_task_token)):
            job = self.task(task_id, token=access_token)
            if job["state"] != "completed" or not job.get("receipt"):
                raise HTTPException(409, "Artifacts require a settled job receipt.")
            item = next((item for item in job["receipt"].get("artifacts", []) if item["object_id"] == object_id), None)
            if item is None:
                raise HTTPException(404, "Job artifact not found.")
            path = self.objects.resolve(item, owner=job["wallet"], agent=job["agent_pubkey"], task_id=task_id)
            return FileResponse(path, filename=item["name"], media_type="application/octet-stream")
