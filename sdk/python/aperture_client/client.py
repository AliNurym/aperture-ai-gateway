"""Verify the exact authorization before signing; verify evidence before using output.

A signed receipt attributes a report to keys. It is not proof of correct computation.
The caller must pin gateway/program/treasury keys from its deployment configuration.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import secrets
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import base58
import requests
from nacl.signing import VerifyKey
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from .jobs import MAX_INPUT_BYTES, NAME, object_reference, workload_manifest
from .retries import retry_throttled

QUOTE_KEYS = (
    "quote_id", "wallet", "agent_pubkey", "code_sha256", "rate_lamports",
    "max_cost_lamports", "max_runtime_seconds", "expires_at", "passport_version",
    "program_id", "network", "gateway_pubkey", "treasury",
)
RECEIPT_WRAPPER_KEYS = {
    "gateway_pubkey", "gateway_signature", "signed_message", "receipt_sha256",
    "explorer_url", "status",
}
SYSTEM = "11111111111111111111111111111111"
DEVNET_GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
MAX_SOURCE_BYTES = 32_000

def validate_devnet_rpc_url(value):
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    local = host in {"localhost", "127.0.0.1", "::1"}
    require(bool(host) and parsed.username is None and parsed.password is None, "RPC URL must have a host and no embedded credentials")
    require(parsed.scheme in ({"http", "https"} if local else {"https"}), "Remote RPC must use HTTPS")
    require(local or "devnet" in host or "devnet" in parsed.path.lower(), "Mainnet and unlabelled RPC endpoints are not supported")
    return value


class IntegrityError(ValueError):
    """Evidence differs from the exact authorization or its pinned signer."""


class AdmissionUncertainError(requests.RequestException):
    """The exact signed request may already have admitted a task."""

    def __init__(self, quote_id):
        self.quote_id = quote_id
        super().__init__(
            f"Admission for quote {quote_id} could not be confirmed. "
            "Retain this authorization; use list_agent_tasks() to find its quote_id "
            "and resume_task(task_id) before requesting another workload."
        )


def validate_source(code):
    require(isinstance(code, str) and bool(code.strip()), "Source must contain a Python workload")
    try:
        size = len(code.encode("utf-8"))
    except UnicodeEncodeError:
        raise IntegrityError("Source must be valid UTF-8") from None
    require(size <= MAX_SOURCE_BYTES, f"Source exceeds the gateway limit of {MAX_SOURCE_BYTES:,} UTF-8 bytes")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256(value: str):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_quote_message(quote):
    bound = {key: quote[key] for key in QUOTE_KEYS}
    version = 2
    if "workload" in quote:
        spec = quote["workload"]
        require(isinstance(spec, dict) and set(spec) == {"version", "runtime", "source_sha256", "inputs", "parameters"}
                and spec["version"] == 1 and spec["runtime"] == "python"
                and spec["source_sha256"] == quote["code_sha256"],
                "Invalid job manifest in quote")
        require(quote.get("workload_sha256") == sha256(canonical(spec)), "Job manifest digest differs")
        # Validate descriptor, name, byte and parameter bounds independently.
        rebuilt = workload_manifest("", spec["inputs"], spec["parameters"])
        rebuilt["source_sha256"] = quote["code_sha256"]
        require(rebuilt == spec, "Job manifest is not canonical")
        bound["workload_sha256"] = quote["workload_sha256"]
        version = 3
    else:
        require("workload_sha256" not in quote, "Job digest has no manifest")
    if "workflow" in quote:
        binding = quote["workflow"]
        require(isinstance(binding, dict) and set(binding) == {"workflow_id", "step_id"}
                and isinstance(binding["workflow_id"], str) and len(binding["workflow_id"]) == 69
                and binding["workflow_id"].startswith("flow-")
                and all(c in "0123456789abcdef" for c in binding["workflow_id"][5:])
                and isinstance(binding["step_id"], str) and 0 < len(binding["step_id"]) <= 64,
                "Quote has invalid workflow binding")
        bound["workflow"] = binding
        version = 4
    return f"Aperture execution authorization v{version}\naudience:aperture-gateway\naction:execute\n" + canonical(bound)


def agent_task_access_message(*, action, owner, agent, issued_at, nonce,
                              program_id, gateway_pubkey, network,
                              task_id=None, limit=None, cursor=None):
    """Build the canonical, domain-separated message for task recovery reads."""
    return "Aperture agent task access v1\naudience:aperture-gateway\n" + canonical({
        "action": action, "owner": owner, "agent_pubkey": agent,
        "issued_at": issued_at, "nonce": nonce, "task_id": task_id,
        "limit": limit, "program_id": program_id,
        "gateway_pubkey": gateway_pubkey, "network": network,
        "cursor": cursor,
    })


def verify_recovered_quote(quote, *, owner, agent, program_id, gateway_pubkey,
                           network, treasury, max_rate_lamports):
    """Validate a persisted quote without requiring its original source text."""
    require(isinstance(quote, dict), "Recovered task has no quote")
    expected = {
        "wallet": owner, "agent_pubkey": agent, "program_id": program_id,
        "gateway_pubkey": gateway_pubkey, "network": network, "treasury": treasury,
    }
    for key, value in expected.items():
        require(quote.get(key) == value, f"Recovered quote changed {key}")
    source_hash = quote.get("code_sha256")
    require(isinstance(source_hash, str) and len(source_hash) == 64
            and all(character in "0123456789abcdef" for character in source_hash),
            "Recovered quote source hash is invalid")
    require(type(quote.get("expires_at")) is int and quote["expires_at"] > 0,
            "Recovered quote expiry is invalid")
    rate = quote.get("rate_lamports")
    cost = quote.get("max_cost_lamports")
    runtime = quote.get("max_runtime_seconds")
    require(type(rate) is int and 0 < rate <= max_rate_lamports
            and type(cost) is int and rate <= cost <= 1_000_000_000
            and type(runtime) is int and 1 <= runtime <= 180,
            "Recovered quote limits are invalid")
    require(type(quote.get("passport_version")) is int
            and quote["passport_version"] >= 0,
            "Recovered quote delegation version is invalid")
    effective_runtime = min(runtime, cost // rate)
    require(type(quote.get("effective_runtime_seconds")) is int
            and quote["effective_runtime_seconds"] == effective_runtime,
            "Recovered quote effective runtime differs from its budget and rate")
    require(isinstance(quote.get("quote_id"), str)
            and 16 <= len(quote["quote_id"]) <= 128,
            "Recovered quote identifier is invalid")
    require(all(key in quote for key in QUOTE_KEYS),
            "Recovered quote is missing signed fields")
    message = canonical_quote_message(quote)
    require(quote.get("message") == message,
            "Recovered quote message is not canonical")
    return message


def require(condition, message):
    if not condition:
        raise IntegrityError(message)


def load_keypair(path: str | Path):
    """Read a Solana CLI keypair file locally; never send it to the gateway."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    require(isinstance(raw, list) and len(raw) == 64, "Expected a local 64-byte Solana keypair file")
    return Keypair.from_bytes(bytes(raw))


def verify_signature(public_key, signature, message):
    try:
        raw = base58.b58decode(signature) if isinstance(signature, str) else bytes(signature)
        VerifyKey(base58.b58decode(public_key)).verify(message.encode("utf-8"), raw)
    except Exception as error:
        raise IntegrityError("Ed25519 signature verification failed") from error


def verify_quote(quote, *, owner, agent, code, max_cost_lamports, max_runtime_seconds,
                 max_rate_lamports, program_id, gateway_pubkey, network, treasury, now=None, workload=None, workflow=None):
    """Reconstruct the signed payload, binding source, environment and caller bounds."""
    now = int(time.time()) if now is None else now
    expected = {
        "wallet": owner, "agent_pubkey": agent, "code_sha256": sha256(code),
        "program_id": program_id, "gateway_pubkey": gateway_pubkey,
        "network": network, "treasury": treasury,
        "max_cost_lamports": max_cost_lamports, "max_runtime_seconds": max_runtime_seconds,
    }
    for key, value in expected.items():
        require(quote.get(key) == value, f"Quote changed {key}")
    require(quote.get("workload") == workload, "Quote changed job inputs or parameters")
    require(quote.get("workflow") == workflow, "Quote changed its assigned workflow step")
    require(type(quote.get("expires_at")) is int and now < quote["expires_at"] <= now + 120, "Quote expired or expiry is implausible")
    require(type(quote.get("rate_lamports")) is int and 0 < quote["rate_lamports"] <= max_rate_lamports, "Quote rate exceeds caller policy")
    require(type(quote.get("passport_version")) is int and quote["passport_version"] >= 0, "Missing delegation version")
    require(isinstance(quote.get("quote_id"), str) and 16 <= len(quote["quote_id"]) <= 128, "Invalid quote id")
    require(max_cost_lamports >= quote["rate_lamports"], "Budget cannot cover a second of execution")
    effective_runtime = min(max_runtime_seconds, max_cost_lamports // quote["rate_lamports"])
    require(type(quote.get("effective_runtime_seconds")) is int
            and quote["effective_runtime_seconds"] == effective_runtime,
            "Quote effective runtime differs from the approved budget and rate")
    message = canonical_quote_message(quote)
    require(quote.get("message") == message, "Quote message does not match canonical authorization")
    return message


def verify_receipt(receipt, *, quote, task_id, full_log):
    """Check gateway and worker attestations against the approved quote and raw log.

    Chain finality is separate: require DEVNET plus independently read TaskReceipt
    for chain assurance. Worker honesty remains a trust assumption.
    """
    evidence = {key: value for key, value in receipt.items() if key not in RECEIPT_WRAPPER_KEYS}
    message = "Aperture compute receipt v1\n" + canonical(evidence)
    require(receipt.get("signed_message") == message, "Receipt fields differ from signed evidence")
    require(receipt.get("receipt_sha256") == sha256(message), "Receipt digest differs")
    require(receipt.get("gateway_pubkey") == quote["gateway_pubkey"], "Receipt signer differs from pinned gateway")
    verify_signature(quote["gateway_pubkey"], receipt.get("gateway_signature", []), message)
    rate = quote.get("rate_lamports")
    budget = quote.get("max_cost_lamports")
    maximum_runtime = quote.get("max_runtime_seconds")
    require(type(rate) is int and rate > 0 and type(budget) is int and budget >= rate
            and type(maximum_runtime) is int and maximum_runtime > 0,
            "Approved quote has invalid runtime bounds")
    effective_runtime = min(maximum_runtime, budget // rate)
    require(type(quote.get("effective_runtime_seconds")) is int
            and quote["effective_runtime_seconds"] == effective_runtime,
            "Approved quote effective runtime differs from its budget and rate")
    expected = {
        "receipt_version": 1, "task_id": task_id, "task_hash": sha256(task_id),
        "quote_id": quote["quote_id"], "owner_wallet": quote["wallet"],
        "agent_pubkey": quote["agent_pubkey"], "passport_version": quote["passport_version"],
        "code_sha256": quote["code_sha256"], "output_sha256": sha256(full_log),
        "rate_lamports": quote["rate_lamports"], "max_cost_lamports": quote["max_cost_lamports"],
        "max_runtime_seconds": quote["max_runtime_seconds"],
    }
    for key, value in expected.items():
        require(receipt.get(key) == value, f"Receipt changed {key}")
    artifacts = receipt.get("artifacts", [])
    if "workload" in quote:
        require(receipt.get("workload_sha256") == quote["workload_sha256"],
                "Receipt changed the authorized data job")
        require(isinstance(artifacts, list) and len(artifacts) <= 16, "Invalid result artifact list")
        artifacts = [object_reference(item) for item in artifacts]
        require(len({item["name"].casefold() for item in artifacts}) == len(artifacts)
                and all(item["size_bytes"] <= 8 * 1024 * 1024 for item in artifacts)
                and sum(item["size_bytes"] for item in artifacts) <= 16 * 1024 * 1024,
                "Result artifacts exceed bounded job limits")
    else:
        require(not artifacts and "workload_sha256" not in receipt, "Unexpected data job result")
    allowed_settlement_types = {
        "devnet": ("DEVNET", "NOT_STARTED"),
        "off_chain": ("OFF_CHAIN", "NOT_STARTED"),
    }
    settlement_type = receipt.get("settlement_type")
    require(isinstance(settlement_type, str)
            and settlement_type in allowed_settlement_types.get(quote.get("network"), ()),
            "Receipt settlement type differs from the approved network")
    elapsed = receipt.get("execution_time")
    require(type(elapsed) in (int, float) and 0 <= elapsed <= effective_runtime, "Receipt runtime exceeds the budgeted execution limit")
    charged = receipt.get("charged_lamports")
    require(charged is None or (type(charged) is int and 0 <= charged <= quote["max_cost_lamports"]), "Receipt charge exceeds authorization")
    if receipt.get("settlement_type") == "DEVNET":
        require(quote["network"] == "devnet" and charged is not None and receipt.get("settlement_signature"), "Incomplete Devnet settlement report")
    worker = receipt.get("worker_receipt")
    if worker:
        require(worker.get("domain") == "aperture.worker.result.v1", "Unknown worker signature domain")
        verify_signature(worker["worker_pubkey"], receipt.get("worker_signature", ""), canonical(worker))
        worker_expected = {
            "task_id": task_id, "lease_id": receipt["lease_id"], "source_hash": quote["code_sha256"],
            "output_hash": sha256(full_log), "quote_id": quote["quote_id"], "agent_pubkey": quote["agent_pubkey"],
            "worker_id": receipt["worker_id"], "exit_code": receipt["exit_code"],
        }
        if "workload" in quote:
            worker_expected.update(workload_sha256=quote["workload_sha256"], artifacts=artifacts)
        for key, value in worker_expected.items():
            require(worker.get(key) == value, f"Worker attestation changed {key}")
        require(worker.get("execution_mode") == receipt.get("execution_backend"), "Worker execution mode differs")
        require(type(worker.get("execution_time_ms")) is int and 0 <= worker["execution_time_ms"] <= effective_runtime * 1000, "Worker runtime exceeds the budgeted execution limit")
    else:
        require(receipt.get("execution_status") != "completed", "Successful execution has no signed worker evidence")
    return evidence


@dataclass(frozen=True)
class Task:
    task_id: str
    access_token: str
    quote: dict
    status: str = "queued"


class ApertureClient:
    def __init__(self, gateway_url, *, owner, agent_keypair, program_id, gateway_pubkey,
                 network="devnet", treasury=None, rpc_url=None, session=None):
        parsed = urlparse(gateway_url)
        require(parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}), "Use HTTPS outside localhost")
        require(network in {"devnet", "off_chain"}, "Client supports Devnet or explicit off-chain development")
        self.url = gateway_url.rstrip("/")
        self.owner = str(Pubkey.from_string(owner))
        self.key = agent_keypair
        self.agent = str(agent_keypair.pubkey())
        self.program_id = str(Pubkey.from_string(program_id))
        self.gateway_pubkey = str(Pubkey.from_string(gateway_pubkey))
        self.network, self.treasury = network, treasury
        require(network == "off_chain" or treasury is not None, "Pin the Devnet treasury")
        self.rpc_url = validate_devnet_rpc_url(rpc_url or "https://api.devnet.solana.com") if network == "devnet" else rpc_url
        self._devnet_cluster_verified = network != "devnet" or urlparse(self.rpc_url).hostname in {"localhost", "127.0.0.1", "::1"}
        self.http = session or requests.Session()

    def request(self, method, path, **kwargs):
        response = self.http.request(method, self.url + path, timeout=(5, 15), allow_redirects=False, **kwargs)
        response.raise_for_status()
        require(response.status_code < 300, "Gateway redirects are not supported; configure its final URL")
        return response

    def quote(self, code, *, max_cost_lamports=100_000, max_runtime_seconds=30, max_rate_lamports=25_000):
        validate_source(code)
        if self.network == "devnet":
            self.verify_protocol_config()
        quote = self.request("POST", "/quotes", json={"wallet": self.owner, "agent_pubkey": self.agent, "code": code,
            "max_cost_lamports": max_cost_lamports, "max_runtime_seconds": max_runtime_seconds}).json()
        verify_quote(quote, owner=self.owner, agent=self.agent, code=code, max_cost_lamports=max_cost_lamports,
            max_runtime_seconds=max_runtime_seconds, max_rate_lamports=max_rate_lamports, program_id=self.program_id,
            gateway_pubkey=self.gateway_pubkey, network=self.network, treasury=self.treasury)
        return quote

    def execute(self, quote, code, *, max_rate_lamports=25_000, inputs=None, parameters=None):
        spec = workload_manifest(code, inputs or [], parameters) if inputs is not None or parameters is not None else None
        message = verify_quote(quote, owner=self.owner, agent=self.agent, code=code,
            max_cost_lamports=quote["max_cost_lamports"], max_runtime_seconds=quote["max_runtime_seconds"],
            max_rate_lamports=max_rate_lamports, program_id=self.program_id, gateway_pubkey=self.gateway_pubkey,
            network=self.network, treasury=self.treasury, workload=spec, workflow=getattr(self, "workflow_binding", None))
        payload = {"quote_id": quote["quote_id"], "wallet": self.owner, "agent_pubkey": self.agent,
                   "code": code, "message": message, "signature": list(bytes(self.key.sign_message(message.encode("utf-8"))))}
        if spec is not None:
            payload.update(job_version=1, inputs=spec["inputs"], parameters=spec["parameters"])
        # Repeat the same authorization if the first response was lost. Never
        # request a fresh quote automatically after ambiguous admission.
        for attempt in range(2):
            try:
                result = self.request("POST", "/execute", json=payload).json()
                require(isinstance(result, dict), "Gateway returned an invalid admission response")
                require(result.get("quote_id") == quote["quote_id"] and result.get("code_sha256") == quote["code_sha256"], "Admission differs from quote")
                require(self._valid_task_id(result.get("task_id")), "Gateway returned an invalid task identifier")
                token = result.get("task_access_token")
                require(isinstance(token, str) and 32 <= len(token) <= 128
                        and all(character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in token),
                        "Gateway returned an invalid task capability")
                status = result.get("status")
                require(isinstance(status, str) and status in {"queued", "starting", "running", "settlement_pending", "completed"},
                        "Gateway returned an invalid admitted task status")
                return Task(result["task_id"], token, quote, status)
            except requests.HTTPError as error:
                response = error.response
                if response is not None and response.status_code == 429:
                    detail = None
                    try:
                        body = response.json()
                        if isinstance(body, dict):
                            detail = body.get("detail")
                    except ValueError:
                        pass
                    detail = detail if isinstance(detail, str) and detail else "Gateway admission was rate limited or is at capacity."
                    raise requests.HTTPError(
                        f"{detail} This attempt was rate limited. Retain the same quote; "
                        "retry execute(quote, code) before it expires, or use list_agent_tasks() "
                        "and resume_task() to recover an earlier uncertain admission.",
                        response=response,
                    ) from error
                if response is not None and (response.status_code == 408 or response.status_code >= 500):
                    if attempt:
                        raise AdmissionUncertainError(quote["quote_id"]) from error
                    continue
                raise
            except (requests.Timeout, requests.ConnectionError, ValueError) as error:
                if attempt:
                    raise AdmissionUncertainError(quote["quote_id"]) from error

    def upload_input(self, data, *, name=None):
        """Upload caller-selected bytes or a file; verify retained size and hash."""
        path = Path(data) if isinstance(data, (str, Path)) else None
        if path is not None:
            name = name or path.name
            size = path.stat().st_size
            require(0 < size <= MAX_INPUT_BYTES, "Input must contain 1 byte to 64 MiB")
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(64 * 1024), b""):
                    digest.update(chunk)
            digest = digest.hexdigest()
        else:
            require(isinstance(data, bytes), "Input must be bytes or a caller-selected path")
            size, digest = len(data), hashlib.sha256(data).hexdigest()
        require(type(size) is int and 0 < size <= MAX_INPUT_BYTES, "Input must contain 1 byte to 64 MiB")
        require(isinstance(name, str) and NAME.fullmatch(name), "Input requires a safe filename")
        def authorize():
            issued_at, nonce = int(time.time()), secrets.token_urlsafe(24)
            message = agent_task_access_message(action="upload-object", owner=self.owner, agent=self.agent,
                issued_at=issued_at, nonce=nonce, task_id=digest, limit=size, cursor=name,
                program_id=self.program_id, gateway_pubkey=self.gateway_pubkey, network=self.network)
            return self.request("POST", "/objects/authorize", json={
                "owner": self.owner, "agent_pubkey": self.agent, "name": name, "sha256": digest,
                "size_bytes": size, "issued_at": issued_at, "nonce": nonce,
                "signature": list(bytes(self.key.sign_message(message.encode()))),
            }).json()
        authorization = retry_throttled(authorize)
        descriptor = object_reference({key: authorization[key] for key in ("object_id", "name", "sha256", "size_bytes")})
        require(descriptor["name"] == name and descriptor["sha256"] == digest
                and descriptor["size_bytes"] == size, "Upload authorization changed input content")
        token = authorization.get("upload_token")
        require(isinstance(token, str) and 32 <= len(token) <= 128, "Invalid upload capability")
        headers = {"X-Aperture-Upload-Token": token, "Content-Type": "application/octet-stream"}
        def upload():
            # Reopen the selected file on every retry; never reuse its consumed stream.
            if path is not None:
                with path.open("rb") as source:
                    return self.request("PUT", f"/objects/{descriptor['object_id']}", data=source, headers=headers).json()
            return self.request("PUT", f"/objects/{descriptor['object_id']}", data=data, headers=headers).json()
        result = retry_throttled(upload)
        require(result == descriptor, "Input upload changed its immutable descriptor")
        return descriptor

    def storage_usage(self):
        """Read this agent's private objects and retained capacity."""
        def read():
            issued_at, nonce = int(time.time()), secrets.token_urlsafe(24)
            message = agent_task_access_message(action="object-usage", owner=self.owner, agent=self.agent,
                issued_at=issued_at, nonce=nonce, program_id=self.program_id,
                gateway_pubkey=self.gateway_pubkey, network=self.network)
            return self.request("POST", "/objects/usage", json={"owner": self.owner,
                "agent_pubkey": self.agent, "issued_at": issued_at, "nonce": nonce,
                "signature": list(bytes(self.key.sign_message(message.encode())))}).json()
        usage = retry_throttled(read)
        require(isinstance(usage, dict) and isinstance(usage.get("objects"), list)
                and type(usage.get("object_count")) is int and usage["object_count"] == len(usage["objects"])
                and 0 <= usage["object_count"] <= 512, "Gateway returned invalid object capacity")
        total = 0
        for item in usage["objects"]:
            object_reference({key: item[key] for key in ("object_id", "name", "sha256", "size_bytes")})
            require(item.get("state") in {"authorized", "uploading", "ready", "deleting"}, "Invalid object state")
            total += item["size_bytes"]
        require(usage.get("size_bytes") == total and usage.get("max_size_bytes") == 256 * 1024 * 1024
                and usage.get("max_object_count") == 512, "Gateway returned inconsistent object capacity")
        return usage

    def assign_inputs(self, inputs, *, owner_keypair):
        """Owner approves private files for this client agent in one request.

        The caller deliberately supplies the owner key locally. It is used only
        to sign this exact handoff, never sent to or retained by the gateway.
        Returned references belong to the agent and work in quote_job/workflows.
        """
        require(str(owner_keypair.pubkey()) == self.owner, "Handoff signer must be the configured owner")
        require(isinstance(inputs, (list, tuple)) and 0 < len(inputs) <= 200,
                "Assign 1 to 200 owner-uploaded inputs")
        files = [object_reference(item) for item in inputs]
        size = sum(item["size_bytes"] for item in files)
        require(len({item["object_id"] for item in files}) == len(files) and size <= 256 * 1024 * 1024,
                "Assign unique inputs totaling at most 256 MiB")
        def assign():
            issued_at, nonce = int(time.time()), secrets.token_urlsafe(24)
            fields = {"owner": self.owner, "agent_pubkey": self.agent, "issued_at": issued_at, "nonce": nonce}
            message = "Aperture owner control v1\naudience:aperture-gateway\n" + canonical({
                "action": "assign-inputs", **fields, "task_id": sha256(canonical(files)), "limit": size,
                "cursor": None, "program_id": self.program_id, "gateway_pubkey": self.gateway_pubkey, "network": self.network})
            return self.request("POST", "/owners/objects/assign-batch", json={**fields, "inputs": files,
                "signature": list(bytes(owner_keypair.sign_message(message.encode())))}).json()
        result = retry_throttled(assign)
        require(isinstance(result, dict) and result.get("owner") == self.owner and result.get("agent_pubkey") == self.agent
                and isinstance(result.get("inputs"), list) and len(result["inputs"]) == len(files),
                "Handoff response changed execution identity or input count")
        references = [object_reference(item) for item in result["inputs"]]
        require(all(all(item[key] == original[key] for key in ("name", "sha256", "size_bytes"))
                    for item, original in zip(references, files)), "Assigned input changed its content")
        return references

    def release_object(self, reference):
        """Explicitly remove retained bytes. Active jobs and unused quotes block removal.

        Download needed outputs first. Historical receipts remain signed metadata,
        but released files cannot be downloaded or used by new jobs.
        """
        item = object_reference(reference)
        def release():
            issued_at, nonce = int(time.time()), secrets.token_urlsafe(24)
            message = agent_task_access_message(action="release-object", owner=self.owner, agent=self.agent,
                issued_at=issued_at, nonce=nonce, task_id=item["object_id"], limit=item["size_bytes"],
                cursor=item["name"] + ":" + item["sha256"], program_id=self.program_id,
                gateway_pubkey=self.gateway_pubkey, network=self.network)
            return self.request("POST", "/objects/release", json={"owner": self.owner,
                "agent_pubkey": self.agent, **item, "issued_at": issued_at, "nonce": nonce,
                "signature": list(bytes(self.key.sign_message(message.encode())))}).json()
        result = retry_throttled(release)
        require(result == {"object_id": item["object_id"], "status": "released", "size_bytes": item["size_bytes"]},
                "Object release differs from the selected file")
        return result

    def quote_job(self, code, *, inputs=(), parameters=None, max_cost_lamports=100_000,
                  max_runtime_seconds=30, max_rate_lamports=25_000):
        validate_source(code)
        spec = workload_manifest(code, inputs, parameters)
        if self.network == "devnet":
            self.verify_protocol_config()
        quote = self.request("POST", "/quotes", json={"code": code, "wallet": self.owner,
            "agent_pubkey": self.agent, "job_version": 1, "inputs": spec["inputs"], "parameters": spec["parameters"],
            "max_cost_lamports": max_cost_lamports, "max_runtime_seconds": max_runtime_seconds,
            **({"workflow": self.workflow_binding} if getattr(self, "workflow_binding", None) else {})}).json()
        verify_quote(quote, owner=self.owner, agent=self.agent, code=code,
            max_cost_lamports=max_cost_lamports, max_runtime_seconds=max_runtime_seconds,
            max_rate_lamports=max_rate_lamports, program_id=self.program_id,
            gateway_pubkey=self.gateway_pubkey, network=self.network, treasury=self.treasury, workload=spec,
            workflow=getattr(self, "workflow_binding", None))
        return quote

    def execute_job(self, quote, code, *, inputs=(), parameters=None, max_rate_lamports=25_000):
        return self.execute(quote, code, inputs=list(inputs), parameters=parameters or {},
                            max_rate_lamports=max_rate_lamports)

    def download_artifact(self, task, receipt, name):
        """Verify receipt signatures, then download and hash the named result bytes."""
        full_log = self.request("GET", f"/download/{task.task_id}",
            headers={"X-Aperture-Task-Token": task.access_token}).content.decode("utf-8")
        verify_receipt(receipt, quote=task.quote, task_id=task.task_id, full_log=full_log)
        if receipt["settlement_type"] == "DEVNET":
            self.verify_devnet_task_receipt(task, receipt)
        item = next((item for item in receipt.get("artifacts", []) if item["name"] == name), None)
        require(item is not None, "Named artifact is absent from the signed result")
        with self.request("GET", f"/tasks/{task.task_id}/artifacts/{item['object_id']}",
                          headers={"X-Aperture-Task-Token": task.access_token}, stream=True) as response:
            data = bytearray()
            for chunk in response.iter_content(64 * 1024):
                data.extend(chunk)
                require(len(data) <= item["size_bytes"], "Artifact exceeds its attested size")
        require(len(data) == item["size_bytes"] and hashlib.sha256(data).hexdigest() == item["sha256"],
                "Downloaded artifact differs from its signed digest")
        return bytes(data)

    def poll(self, task):
        result = self.request("GET", f"/result/{task.task_id}", headers={"X-Aperture-Task-Token": task.access_token}).json()
        require(isinstance(result, dict) and isinstance(result.get("status"), str) and result["status"] in {
            "queued", "starting", "running", "settlement_pending", "completed",
        }, "Gateway returned an invalid task status")
        return result

    def cancel(self, task):
        return self.request("POST", f"/stop/{task.task_id}", headers={"X-Aperture-Task-Token": task.access_token}).json()

    def wait(self, task, *, timeout_seconds=300, cancel_on_timeout=True, should_stop=None):
        require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
                and timeout_seconds > 0, "Wait timeout must be a positive finite number")
        require(should_stop is None or callable(should_stop), "Stop signal must be callable")
        deadline = time.monotonic() + timeout_seconds
        failures = 0
        last_error = None
        completion_reported = False
        cancellation_requested = False
        while time.monotonic() < deadline:
            stop_requested = should_stop is not None and should_stop()
            try:
                if stop_requested and not cancellation_requested:
                    self.cancel(task)
                    cancellation_requested = True
                result = self.poll(task)
                if result.get("status") == "completed":
                    completion_reported = True
                    receipt = result.get("receipt")
                    require(isinstance(receipt, dict), "Completed task has no valid receipt")
                    full_log = self.request("GET", f"/download/{task.task_id}", headers={"X-Aperture-Task-Token": task.access_token}).content.decode("utf-8")
                    verify_receipt(receipt, quote=task.quote, task_id=task.task_id, full_log=full_log)
                    if receipt.get("settlement_type") == "DEVNET":
                        self.verify_devnet_task_receipt(task, receipt)
                    return {**result, "output": full_log, "full_log": full_log}
                failures = 0
                last_error = None
            except (requests.Timeout, requests.ConnectionError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.JSONDecodeError, json.JSONDecodeError) as error:
                failures += 1
                last_error = error
            except requests.HTTPError as error:
                status = error.response.status_code if error.response is not None else None
                if status not in (408, 429) and not (status is not None and status >= 500):
                    raise
                failures += 1
                last_error = error
            remaining = deadline - time.monotonic()
            if remaining > 0:
                pause = min(remaining, 0.5 * 2 ** min(failures, 4))
                if should_stop is None or cancellation_requested or stop_requested:
                    time.sleep(pause)
                else:
                    wake = time.monotonic() + pause
                    while time.monotonic() < wake:
                        if should_stop():
                            break
                        time.sleep(min(0.25, max(0, wake - time.monotonic())))
        if completion_reported:
            raise TimeoutError("Task result could not be verified before timeout; retain its capability and retry wait()") from last_error
        if cancel_on_timeout:
            try:
                self.cancel(task)
            except requests.RequestException as error:
                raise TimeoutError("Task wait timed out and cancellation could not be confirmed; retain its capability and poll for final settlement") from error
        raise TimeoutError("Task wait timed out; retain its capability and poll for final settlement") from last_error

    def _agent_task_access_request(self, action, *, task_id=None, limit=None,
                                   cursor=None):
        issued_at = int(time.time())
        nonce = secrets.token_urlsafe(24)
        message = agent_task_access_message(
            action=action, owner=self.owner, agent=self.agent,
            issued_at=issued_at, nonce=nonce, task_id=task_id, limit=limit,
            program_id=self.program_id, gateway_pubkey=self.gateway_pubkey,
            network=self.network, cursor=cursor,
        )
        return {
            "owner": self.owner, "agent_pubkey": self.agent,
            "issued_at": issued_at, "nonce": nonce,
            "signature": list(bytes(self.key.sign_message(message.encode("utf-8")))),
        }

    @staticmethod
    def _valid_task_id(task_id):
        return (isinstance(task_id, str) and len(task_id) == 37
                and task_id.startswith("task-")
                and all(character in "0123456789abcdef" for character in task_id[5:]))

    def list_agent_tasks(self, *, limit=20, cursor=None):
        """List one page of history scoped to this signed owner/agent pair."""
        require(type(limit) is int and 1 <= limit <= 50,
                "Task history limit must be between 1 and 50")
        require(cursor is None or self._valid_task_id(cursor),
                "Task history cursor is invalid")
        body = self._agent_task_access_request(
            "list", limit=limit, cursor=cursor
        )
        body["limit"] = limit
        body["cursor"] = cursor
        response = self.request("POST", "/agents/tasks/list", json=body).json()
        require(isinstance(response, dict),
                "Gateway returned an invalid agent task list")
        tasks = response.get("tasks")
        require(isinstance(tasks, list) and len(tasks) <= limit,
                "Gateway returned an invalid agent task list")
        next_cursor = response.get("next_cursor")
        require(next_cursor is None or self._valid_task_id(next_cursor),
                "Gateway returned an invalid task history cursor")
        valid_statuses = {"queued", "starting", "running", "settlement_pending", "completed"}
        for item in tasks:
            require(isinstance(item, dict) and self._valid_task_id(item.get("task_id")),
                    "Gateway returned an invalid task identifier")
            require(isinstance(item.get("status"), str) and item["status"] in valid_statuses,
                    "Gateway returned an invalid task status")
            require(isinstance(item.get("quote_id"), str)
                    and 16 <= len(item["quote_id"]) <= 128,
                    "Gateway returned an invalid task quote identifier")
            source_hash = item.get("code_sha256")
            require(isinstance(source_hash, str) and len(source_hash) == 64
                    and all(character in "0123456789abcdef" for character in source_hash),
                    "Gateway returned an invalid task source hash")
            require(type(item.get("max_cost_lamports")) is int
                    and 0 < item["max_cost_lamports"] <= 1_000_000_000
                    and type(item.get("max_runtime_seconds")) is int
                    and 1 <= item["max_runtime_seconds"] <= 180,
                    "Gateway returned invalid task limits")
            require(type(item.get("receipt_available")) is bool,
                    "Gateway returned an invalid receipt availability flag")
        return {"tasks": tasks, "next_cursor": next_cursor}

    def resume_task(self, task_id):
        """Reacquire a task capability without submitting or charging a new job."""
        require(self._valid_task_id(task_id), "Invalid task identifier")
        body = self._agent_task_access_request("resume", task_id=task_id)
        body["task_id"] = task_id
        response = self.request("POST", "/agents/tasks/resume", json=body).json()
        require(isinstance(response, dict) and response.get("task_id") == task_id,
                "Gateway returned another task during recovery")
        quote = response.get("quote")
        message = verify_recovered_quote(
            quote, owner=self.owner, agent=self.agent, program_id=self.program_id,
            gateway_pubkey=self.gateway_pubkey, network=self.network,
            treasury=self.treasury, max_rate_lamports=1_000_000_000,
        )
        require(response.get("quote_id") == quote["quote_id"]
                and response.get("code_sha256") == quote["code_sha256"],
                "Recovered task differs from its signed quote")
        admission_signature = response.get("agent_signature")
        if admission_signature is not None:
            verify_signature(self.agent, admission_signature, message)
        token = response.get("task_access_token")
        require(isinstance(token, str) and 32 <= len(token) <= 128
                and all(character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in token),
                "Gateway returned an invalid task capability")
        status = response.get("status")
        require(isinstance(status, str)
                and status in {"queued", "starting", "running", "settlement_pending", "completed"},
                "Gateway returned an invalid recovered task status")
        return Task(task_id, token, quote, status)

    def rpc(self, method, params):
        require(self.rpc_url is not None, "Configure an independent Devnet/local-validator RPC")
        if self.network == "devnet" and not self._devnet_cluster_verified and method != "getGenesisHash":
            self.rpc("getGenesisHash", [])
        response = self.http.post(self.rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=(5, 20))
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise RuntimeError(f"RPC {method} failed: {body['error'].get('message', 'unknown error')}")
        result = body["result"]
        if self.network == "devnet" and method == "getGenesisHash":
            observed = (
                result
                if isinstance(result, str) and len(result) <= 64 and result.isascii() and result.isalnum()
                else "<invalid response>"
            )
            require(
                result == DEVNET_GENESIS_HASH,
                f"Configured RPC returned genesis hash {observed}; expected canonical Solana Devnet hash {DEVNET_GENESIS_HASH}",
            )
            self._devnet_cluster_verified = True
        return result

    def send_instruction(self, instruction, owner_keypair):
        # These instructions are constructed locally after validating the policy.
        blockhash = self.rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
        transaction = VersionedTransaction(Message.new_with_blockhash([instruction], owner_keypair.pubkey(), Hash.from_string(blockhash)), [owner_keypair])
        signature = self.rpc("sendTransaction", [base64.b64encode(bytes(transaction)).decode(), {"encoding": "base64", "preflightCommitment": "confirmed"}])
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            status = self.rpc("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])["value"][0]
            if status:
                require(status.get("err") is None, "Owner transaction failed")
                if status.get("confirmationStatus") in {"confirmed", "finalized"}:
                    return signature
            time.sleep(0.5)
        raise TimeoutError(f"Transaction confirmation uncertain; recover the same policy before retry: {signature}")

    def account(self, address):
        response = self.rpc("getAccountInfo", [str(address), {"encoding": "base64", "commitment": "confirmed"}])["value"]
        if response is None:
            return None
        return response["owner"], base64.b64decode(response["data"][0])

    def verify_protocol_config(self):
        program = Pubkey.from_string(self.program_id)
        config, _ = Pubkey.find_program_address([b"config"], program)
        found = self.account(config)
        require(found is not None, "Devnet protocol config is not initialized")
        account_owner, data = found
        discriminator = hashlib.sha256(b"account:ProtocolConfig").digest()[:8]
        require(account_owner == self.program_id and len(data) == 107 and data[:8] == discriminator,
                "Devnet program config has the wrong owner or account layout")
        require(struct.unpack("<H", data[105:107])[0] == 2, "Devnet protocol version 2 is required")
        oracle = str(Pubkey.from_bytes(data[40:72]))
        treasury = str(Pubkey.from_bytes(data[72:104]))
        require(oracle == self.gateway_pubkey and treasury == self.treasury, "Pinned gateway signer or treasury differs from protocol config")
        return {"oracle": oracle, "treasury": treasury, "version": 2}

    def verify_devnet_task_receipt(self, task, receipt):
        task_hash = bytes.fromhex(receipt["task_hash"])
        require(len(task_hash) == 32 and receipt["task_hash"] == sha256(task.task_id), "Invalid task receipt identifier")
        program = Pubkey.from_string(self.program_id)
        address, _ = Pubkey.find_program_address([b"task", task_hash], program)
        found = self.account(address)
        require(found is not None, "Persistent on-chain TaskReceipt is absent")
        account_owner, data = found
        discriminator = hashlib.sha256(b"account:TaskReceipt").digest()[:8]
        require(account_owner == self.program_id and len(data) == 186 and data[:8] == discriminator and data[184] == 1,
                "Persistent on-chain TaskReceipt is unsettled or incompatible")
        require(str(Pubkey.from_bytes(data[8:40])) == self.owner, "On-chain receipt has another owner")
        require(str(Pubkey.from_bytes(data[40:72])) == self.agent, "On-chain receipt has another agent")
        require(data[72:104] == task_hash and data[104:136].hex() == task.quote["code_sha256"], "On-chain task/source hash differs")
        require(struct.unpack("<Q", data[136:144])[0] == task.quote["rate_lamports"], "On-chain rate differs from signed quote")
        require(struct.unpack("<Q", data[144:152])[0] == task.quote["max_cost_lamports"], "On-chain cap differs from signed quote")
        rate = task.quote.get("rate_lamports")
        budget = task.quote.get("max_cost_lamports")
        runtime = task.quote.get("max_runtime_seconds")
        require(type(rate) is int and rate > 0 and type(budget) is int and budget >= rate
                and type(runtime) is int and runtime > 0, "Approved quote has invalid runtime bounds")
        effective_runtime = min(runtime, budget // rate)
        require(type(task.quote.get("effective_runtime_seconds")) is int
                and task.quote["effective_runtime_seconds"] == effective_runtime,
                "Approved quote effective runtime differs from its budget and rate")
        started_at, deadline = struct.unpack("<qq", data[152:168])
        require(started_at > 0 and started_at < deadline <= started_at + effective_runtime,
                "On-chain task runtime exceeds the approved quote limit")
        charged = struct.unpack("<Q", data[176:184])[0]
        require(charged == receipt["charged_lamports"] and charged <= task.quote["max_cost_lamports"], "On-chain settlement differs from signed receipt")
        require(receipt["settlement_signature"], "Devnet settlement transaction signature is absent")
        history = self.rpc("getSignaturesForAddress", [str(address), {"limit": 20, "commitment": "confirmed"}])
        require(any(item.get("signature") == receipt["settlement_signature"] and item.get("err") is None
                    for item in history), "Settlement transaction does not reference this task receipt account")
        status = self.rpc("getSignatureStatuses", [[receipt["settlement_signature"]], {"searchTransactionHistory": True}])["value"][0]
        require(status is not None and status.get("err") is None and status.get("confirmationStatus") in {"confirmed", "finalized"},
                "Devnet settlement transaction has not confirmed successfully")
        return {"address": str(address), "charged_lamports": charged}

    def fund_channel(self, owner_keypair, lamports):
        require(self.network == "devnet" and str(owner_keypair.pubkey()) == self.owner, "Owner Devnet key required")
        require(type(lamports) is int and 0 < lamports <= 1_000_000_000, "Explicit development deposit capped at 1 SOL per call")
        self.verify_protocol_config()
        program = Pubkey.from_string(self.program_id)
        channel, _ = Pubkey.find_program_address([b"channel", bytes(owner_keypair.pubkey())], program)
        found = self.account(channel)
        if found is None:
            config, _ = Pubkey.find_program_address([b"config"], program)
            data = hashlib.sha256(b"global:open_channel").digest()[:8] + struct.pack("<Q", lamports)
            accounts = [AccountMeta(config, False, False), AccountMeta(channel, False, True),
                        AccountMeta(owner_keypair.pubkey(), True, True), AccountMeta(Pubkey.from_string(SYSTEM), False, False)]
        else:
            owner, data_account = found
            require(owner == self.program_id and len(data_account) == 225 and data_account[:8] == hashlib.sha256(b"account:ChannelState").digest()[:8],
                    "Payment channel has the wrong program owner or layout")
            require(str(Pubkey.from_bytes(data_account[8:40])) == self.owner, "Payment channel belongs to another wallet")
            data = hashlib.sha256(b"global:top_up").digest()[:8] + struct.pack("<Q", lamports)
            accounts = [AccountMeta(channel, False, True), AccountMeta(owner_keypair.pubkey(), True, True),
                        AccountMeta(Pubkey.from_string(SYSTEM), False, False)]
        signature = self.send_instruction(Instruction(program, data, accounts), owner_keypair)
        return signature

    def list_agent_passports(self, owner_keypair):
        """Read the configured owner's passports and usage with a short-lived signature."""
        require(str(owner_keypair.pubkey()) == self.owner, "Only the configured owner reads agent passports")
        issued_at = int(time.time())
        nonce = secrets.token_urlsafe(24)
        message = "Aperture agent allowance read v1\naudience:aperture-gateway\n" + canonical({
            "owner": self.owner, "issued_at": issued_at, "nonce": nonce,
        })
        signature = list(bytes(owner_keypair.sign_message(message.encode("utf-8"))))
        passports = self.request("POST", "/agents/usage", json={
            "owner": self.owner, "issued_at": issued_at, "nonce": nonce, "signature": signature,
        }).json()
        require(isinstance(passports, list), "Gateway returned an invalid passport list")
        for passport in passports:
            self._verify_agent_passport(passport)
        return passports

    def _verify_agent_passport(self, item):
        require(isinstance(item, dict) and item.get("owner") == self.owner,
                "Gateway returned a passport for another owner")
        policy_keys = (
            "owner", "agent_pubkey", "name", "max_cost_lamports", "max_runtime_seconds",
            "total_budget_lamports", "expires_at", "capabilities", "program_id", "network",
            "version", "metadata_hash",
        )
        policy = {key: item.get(key) for key in policy_keys}
        require(str(Pubkey.from_string(policy["agent_pubkey"])) == policy["agent_pubkey"], "Passport agent key is invalid")
        require(policy["program_id"] == self.program_id and policy["network"] == self.network,
                "Passport program or network differs from the client configuration")
        expected_attestation = "SOLANA_DEVNET" if self.network == "devnet" else "OWNER_SIGNED_OFF_CHAIN"
        require(item.get("attestation") == expected_attestation, "Passport attestation differs from the client network")
        require(isinstance(policy["name"], str) and 1 <= len(policy["name"]) <= 80 and bool(policy["name"].strip()), "Passport name is invalid")
        require(type(policy["max_cost_lamports"]) is int and 0 < policy["max_cost_lamports"] <= 1_000_000_000
                and type(policy["max_runtime_seconds"]) is int and 1 <= policy["max_runtime_seconds"] <= 180
                and type(policy["total_budget_lamports"]) is int and policy["max_cost_lamports"] <= policy["total_budget_lamports"] <= 100_000_000_000
                and type(policy["expires_at"]) is int and policy["expires_at"] > 0
                and type(policy["version"]) is int and policy["version"] > 0
                and policy["capabilities"] == ["python.execute"], "Passport policy bounds are invalid")
        require(isinstance(policy["metadata_hash"], str)
                and policy["metadata_hash"] == sha256(canonical({key: value for key, value in policy.items() if key != "metadata_hash"})),
                "Passport metadata hash differs")

        prefix = "Aperture agent delegation v1\naudience:aperture-gateway\n"
        message = item.get("owner_signed_message")
        require(isinstance(message, str) and message.startswith(prefix), "Passport has no canonical owner-signed message")
        payload_text = message[len(prefix):]
        try:
            signed = json.loads(payload_text)
        except (TypeError, ValueError) as error:
            raise IntegrityError("Owner-signed passport message is not valid JSON") from error
        try:
            canonical_message = canonical(signed)
        except (TypeError, ValueError) as error:
            raise IntegrityError("Owner-signed passport message is not canonical JSON") from error
        require(canonical_message == payload_text and isinstance(signed, dict)
                and set(signed) == {"action", "passport", "nonce", "challenge_expires_at"}
                and isinstance(signed.get("action"), str)
                and signed["action"] in {"register", "update", "revoke"}
                and isinstance(signed.get("nonce"), str) and 16 <= len(signed["nonce"]) <= 128
                and type(signed.get("challenge_expires_at")) is int and signed["challenge_expires_at"] > 0
                and canonical(signed.get("passport")) == canonical(policy)
                and type(item.get("revoked")) is bool and item["revoked"] == (signed["action"] == "revoke"),
                "Returned passport differs from the owner-signed policy")
        verify_signature(self.owner, item.get("owner_signature", []), message)

        source = "solana_devnet" if self.network == "devnet" else "gateway_ledger"
        require(item.get("allowance_source") == source, "Allowance source differs from the passport network")
        if item.get("allowance_status") == "available":
            spent, reserved, remaining = (item.get("spent_lamports"), item.get("reserved_lamports"), item.get("remaining_lamports"))
            require(all(type(value) is int and value >= 0 for value in (spent, reserved, remaining))
                    and remaining == max(0, policy["total_budget_lamports"] - spent - reserved),
                    "Allowance counters are invalid or inconsistent")
        else:
            require(item.get("allowance_status") == "unavailable"
                    and item.get("spent_lamports") is None and item.get("reserved_lamports") is None
                    and item.get("remaining_lamports") is None, "Allowance status is invalid")

    def passport(self, owner_keypair, *, action="register", name="Risk analysis agent", max_cost_lamports=100_000,
                 max_runtime_seconds=30, total_budget_lamports=1_000_000, expires_at=None):
        require(str(owner_keypair.pubkey()) == self.owner, "Only the configured owner issues delegation")
        expires_at = expires_at or int(time.time()) + 86400
        policy = {"owner": self.owner, "agent_pubkey": self.agent, "name": name, "max_cost_lamports": max_cost_lamports,
            "max_runtime_seconds": max_runtime_seconds, "total_budget_lamports": total_budget_lamports,
            "expires_at": expires_at, "capabilities": ["python.execute"]}
        challenge = self.request("POST", "/agents/challenge", json={"action": action, **policy}).json()
        actual = challenge["passport"]
        for key, value in {**policy, "program_id": self.program_id, "network": self.network}.items():
            require(actual.get(key) == value, f"Delegation changed {key}")
        require(type(actual.get("version")) is int and actual["version"] > 0, "Invalid delegation version")
        require(actual.get("metadata_hash") == sha256(canonical({key: value for key, value in actual.items() if key != "metadata_hash"})), "Delegation metadata hash differs")
        require(challenge["action"] == action and int(time.time()) < challenge["expires_at"] <= int(time.time()) + 120, "Invalid owner challenge")
        message = "Aperture agent delegation v1\naudience:aperture-gateway\n" + canonical({"action": action, "passport": actual,
            "nonce": challenge["nonce"], "challenge_expires_at": challenge["expires_at"]})
        require(challenge["message"] == message, "Owner challenge is not the canonical policy")
        if self.network == "devnet" and challenge.get("chain_instruction"):
            chain_action = challenge["chain_instruction"]["kind"]
            require(chain_action in ({"register", "update"} if action == "register" else {action}), "Unexpected chain action")
            program = Pubkey.from_string(self.program_id)
            passport, _ = Pubkey.find_program_address([b"agent", bytes(self.key.pubkey())], program)
            data = hashlib.sha256(f"global:{chain_action}_agent".encode()).digest()[:8]
            if chain_action != "revoke":
                data += bytes.fromhex(actual["metadata_hash"]) + struct.pack("<QIqQ", max_cost_lamports, max_runtime_seconds, expires_at, total_budget_lamports)
            accounts = [AccountMeta(passport, False, True), AccountMeta(owner_keypair.pubkey(), True, chain_action == "register")]
            if chain_action == "register":
                accounts += [AccountMeta(self.key.pubkey(), False, False), AccountMeta(Pubkey.from_string(SYSTEM), False, False)]
            self.send_instruction(Instruction(program, data, accounts), owner_keypair)
        return self.request("POST", "/agents", json={"nonce": challenge["nonce"], "message": message,
            "signature": list(bytes(owner_keypair.sign_message(message.encode("utf-8"))))}).json()

    def open_channel(self, owner_keypair, lamports):
        return self.fund_channel(owner_keypair, lamports)
