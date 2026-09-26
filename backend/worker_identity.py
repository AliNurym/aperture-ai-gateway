"""Stable worker key and canonical, independently verifiable execution attestation."""

import json
import os
from pathlib import Path

import base58
from nacl.signing import SigningKey


def receipt_bytes(receipt: dict) -> bytes:
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class WorkerIdentity:
    def __init__(self, state_root: Path):
        state_root.mkdir(parents=True, exist_ok=True)
        path = state_root / "worker_signing.key"
        if not path.exists():
            key = SigningKey.generate()
            try:
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
                    handle.write(bytes(key))
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                pass
        seed = path.read_bytes()
        if len(seed) != 32:
            raise ValueError("Invalid worker signing key; restore the worker state backup.")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        self.key = SigningKey(seed)
        self.pubkey = base58.b58encode(bytes(self.key.verify_key)).decode("ascii")

    def attest(self, task: dict, result: dict, worker_id: str):
        receipt = {
            "domain": "aperture.worker.result.v1",
            "task_id": result["task_id"], "lease_id": result["lease_id"],
            "source_hash": result["source_hash"], "output_hash": result["output_hash"],
            "execution_mode": result["execution_mode"],
            "execution_time_ms": round(result["execution_time"] * 1000),
            "exit_code": result["exit_code"], "worker_id": worker_id,
            "worker_pubkey": self.pubkey, "agent_pubkey": task.get("agent_pubkey"),
            "quote_id": task.get("quote_id"),
        }
        signed = self.key.sign(receipt_bytes(receipt))
        return {**result, "worker_pubkey": self.pubkey, "worker_receipt": receipt,
                "worker_signature": base58.b58encode(signed.signature).decode("ascii")}
