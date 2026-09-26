"""Verify the exact authorization before signing; verify evidence before using output.

A signed receipt attributes a report to keys. It is not proof of correct computation.
The caller must pin gateway/program/treasury keys from its deployment configuration.
"""
from __future__ import annotations

import base64
import hashlib
import json
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


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256(value: str):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
                 max_rate_lamports, program_id, gateway_pubkey, network, treasury, now=None):
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
    require(type(quote.get("expires_at")) is int and now < quote["expires_at"] <= now + 120, "Quote expired or expiry is implausible")
    require(type(quote.get("rate_lamports")) is int and 0 < quote["rate_lamports"] <= max_rate_lamports, "Quote rate exceeds caller policy")
    require(type(quote.get("passport_version")) is int and quote["passport_version"] >= 0, "Missing delegation version")
    require(isinstance(quote.get("quote_id"), str) and 16 <= len(quote["quote_id"]) <= 128, "Invalid quote id")
    require(max_cost_lamports >= quote["rate_lamports"], "Budget cannot cover a second of execution")
    message = "Aperture execution authorization v2\naudience:aperture-gateway\naction:execute\n" + canonical({key: quote[key] for key in QUOTE_KEYS})
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
    elapsed = receipt.get("execution_time")
    require(type(elapsed) in (int, float) and 0 <= elapsed <= quote["max_runtime_seconds"], "Receipt runtime exceeds authorization")
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
        for key, value in worker_expected.items():
            require(worker.get(key) == value, f"Worker attestation changed {key}")
        require(worker.get("execution_mode") == receipt.get("execution_backend"), "Worker execution mode differs")
        require(type(worker.get("execution_time_ms")) is int and 0 <= worker["execution_time_ms"] <= quote["max_runtime_seconds"] * 1000 + 1000, "Worker runtime exceeds limit")
    else:
        require(receipt.get("execution_status") != "completed", "Successful execution has no signed worker evidence")
    return evidence


@dataclass(frozen=True)
class Task:
    task_id: str
    access_token: str
    quote: dict


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
        self.http = session or requests.Session()

    def request(self, method, path, **kwargs):
        response = self.http.request(method, self.url + path, timeout=(5, 15), **kwargs)
        response.raise_for_status()
        return response

    def quote(self, code, *, max_cost_lamports=100_000, max_runtime_seconds=30, max_rate_lamports=25_000):
        if self.network == "devnet":
            self.verify_protocol_config()
        quote = self.request("POST", "/quotes", json={"wallet": self.owner, "agent_pubkey": self.agent, "code": code,
            "max_cost_lamports": max_cost_lamports, "max_runtime_seconds": max_runtime_seconds}).json()
        verify_quote(quote, owner=self.owner, agent=self.agent, code=code, max_cost_lamports=max_cost_lamports,
            max_runtime_seconds=max_runtime_seconds, max_rate_lamports=max_rate_lamports, program_id=self.program_id,
            gateway_pubkey=self.gateway_pubkey, network=self.network, treasury=self.treasury)
        return quote

    def execute(self, quote, code, *, max_rate_lamports=25_000):
        message = verify_quote(quote, owner=self.owner, agent=self.agent, code=code,
            max_cost_lamports=quote["max_cost_lamports"], max_runtime_seconds=quote["max_runtime_seconds"],
            max_rate_lamports=max_rate_lamports, program_id=self.program_id, gateway_pubkey=self.gateway_pubkey,
            network=self.network, treasury=self.treasury)
        payload = {"quote_id": quote["quote_id"], "wallet": self.owner, "agent_pubkey": self.agent,
                   "code": code, "message": message, "signature": list(bytes(self.key.sign_message(message.encode("utf-8"))))}
        # Repeat the same authorization if the first response was lost. Never
        # request a fresh quote automatically after ambiguous admission.
        for attempt in range(2):
            try:
                result = self.request("POST", "/execute", json=payload).json()
                require(result.get("quote_id") == quote["quote_id"] and result.get("code_sha256") == quote["code_sha256"], "Admission differs from quote")
                return Task(result["task_id"], result["task_access_token"], quote)
            except (requests.Timeout, requests.ConnectionError):
                if attempt:
                    raise

    def poll(self, task):
        return self.request("GET", f"/result/{task.task_id}", params={"access_token": task.access_token}).json()

    def cancel(self, task):
        return self.request("POST", f"/stop/{task.task_id}", params={"access_token": task.access_token}).json()

    def wait(self, task, *, timeout_seconds=300, cancel_on_timeout=True):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result = self.poll(task)
            if result.get("status") == "completed":
                receipt = result["receipt"]
                full_log = self.request("GET", f"/download/{task.task_id}", params={"access_token": task.access_token}).content.decode("utf-8")
                verify_receipt(receipt, quote=task.quote, task_id=task.task_id, full_log=full_log)
                if receipt.get("settlement_type") == "DEVNET":
                    self.verify_devnet_task_receipt(task, receipt)
                return {**result, "full_log": full_log}
            time.sleep(0.5)
        if cancel_on_timeout:
            self.cancel(task)
        raise TimeoutError("Task still pending; retain its capability and poll for final settlement")

    def rpc(self, method, params):
        require(self.rpc_url is not None, "Configure an independent Devnet/local-validator RPC")
        response = self.http.post(self.rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=(5, 20))
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise RuntimeError(f"RPC {method} failed: {body['error'].get('message', 'unknown error')}")
        return body["result"]

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
        charged = struct.unpack("<Q", data[176:184])[0]
        require(charged == receipt["charged_lamports"] and charged <= task.quote["max_cost_lamports"], "On-chain settlement differs from signed receipt")
        require(receipt["settlement_signature"], "Devnet settlement transaction signature is absent")
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
