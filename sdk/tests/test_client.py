import hashlib
import sys
import unittest
from pathlib import Path

from nacl.signing import SigningKey
import base58
from solders.keypair import Keypair

sys.path.insert(0, str(Path(__file__).parents[1] / "python"))
from aperture_client import ApertureClient, IntegrityError, verify_quote, verify_receipt
from aperture_client.client import QUOTE_KEYS, canonical, sha256


class ClientEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.gateway = SigningKey.generate()
        self.worker = SigningKey.generate()
        self.owner = base58.b58encode(bytes(SigningKey.generate().verify_key)).decode()
        self.agent_key = SigningKey.generate()
        self.agent = base58.b58encode(bytes(self.agent_key.verify_key)).decode()
        self.gateway_pubkey = base58.b58encode(bytes(self.gateway.verify_key)).decode()
        self.worker_pubkey = base58.b58encode(bytes(self.worker.verify_key)).decode()
        self.code = "print('risk')"
        self.now = 1_800_000_000
        self.quote = {
            "quote_id": "quote-0123456789abcdef", "wallet": self.owner, "agent_pubkey": self.agent,
            "code_sha256": sha256(self.code), "rate_lamports": 1500, "max_cost_lamports": 50_000,
            "max_runtime_seconds": 20, "expires_at": self.now + 90, "passport_version": 3,
            "program_id": base58.b58encode(bytes(SigningKey.generate().verify_key)).decode(),
            "network": "devnet", "gateway_pubkey": self.gateway_pubkey,
            "treasury": base58.b58encode(bytes(SigningKey.generate().verify_key)).decode(),
        }
        self.quote["message"] = "Aperture execution authorization v2\naudience:aperture-gateway\naction:execute\n" + canonical({key: self.quote[key] for key in QUOTE_KEYS})

    def verify(self, quote=None, code=None):
        quote = self.quote if quote is None else quote
        return verify_quote(quote, owner=self.owner, agent=self.agent, code=self.code if code is None else code,
            max_cost_lamports=50_000, max_runtime_seconds=20, max_rate_lamports=25_000,
            program_id=self.quote["program_id"], gateway_pubkey=self.gateway_pubkey,
            network="devnet", treasury=self.quote["treasury"], now=self.now)

    def test_valid_quote_is_bound_to_one_source_and_deployment(self):
        self.assertEqual(self.verify(), self.quote["message"])

    def test_rejects_tampered_budget_or_source_even_if_message_is_unchanged(self):
        for field, value in (("max_cost_lamports", 60_000), ("code_sha256", "0" * 64), ("network", "off_chain")):
            altered = dict(self.quote, **{field: value})
            with self.subTest(field=field), self.assertRaises(IntegrityError):
                self.verify(altered)

    def test_rejects_expired_and_excessive_rates(self):
        altered = dict(self.quote, expires_at=self.now)
        altered["message"] = "Aperture execution authorization v2\naudience:aperture-gateway\naction:execute\n" + canonical({key: altered[key] for key in QUOTE_KEYS})
        with self.assertRaises(IntegrityError):
            self.verify(altered)

    def test_devnet_agent_refuses_a_mainnet_rpc(self):
        with self.assertRaises(IntegrityError):
            ApertureClient("https://gateway.example", owner=self.owner, agent_keypair=Keypair(),
                program_id=self.quote["program_id"], gateway_pubkey=self.gateway_pubkey,
                network="devnet", treasury=self.quote["treasury"],
                rpc_url="https://api.mainnet-beta.solana.com")
        altered = dict(self.quote, rate_lamports=25_001)
        altered["message"] = "Aperture execution authorization v2\naudience:aperture-gateway\naction:execute\n" + canonical({key: altered[key] for key in QUOTE_KEYS})
        with self.assertRaises(IntegrityError):
            self.verify(altered)

    def make_receipt(self, full_log="risk result\n"):
        task_id = "task-test-123"
        worker = {
            "domain": "aperture.worker.result.v1", "task_id": task_id, "lease_id": "lease-abc",
            "source_hash": self.quote["code_sha256"], "output_hash": sha256(full_log), "execution_mode": "docker",
            "execution_time_ms": 1234, "exit_code": 0, "worker_id": "worker-a",
            "worker_pubkey": self.worker_pubkey, "agent_pubkey": self.agent, "quote_id": self.quote["quote_id"],
        }
        evidence = {
            "receipt_version": 1, "task_id": task_id, "task_hash": sha256(task_id), "quote_id": self.quote["quote_id"],
            "owner_wallet": self.owner, "agent_pubkey": self.agent, "passport_version": 3,
            "code_sha256": self.quote["code_sha256"], "output_sha256": sha256(full_log),
            "source_hash": self.quote["code_sha256"], "output_hash": sha256(full_log), "worker_id": "worker-a",
            "lease_id": "lease-abc", "execution_status": "completed", "exit_code": 0,
            "execution_time": 1.234, "execution_backend": "docker", "execution_mode": "docker", "isolation": "docker",
            "rate_lamports": 1500, "max_cost_lamports": 50_000, "max_runtime_seconds": 20,
            "charged_lamports": 2_000, "cost_sol": 0.000002, "cost_is_exact": True, "settlement_type": "DEVNET",
            "settlement_signature": "sig", "settlement_evidence": {"charged_lamports": 2_000},
            "worker_receipt": worker,
            "worker_signature": base58.b58encode(self.worker.sign(canonical(worker).encode()).signature).decode(),
            "settled_at": self.now, "attestation": "gateway-reported execution",
        }
        message = "Aperture compute receipt v1\n" + canonical(evidence)
        return {**evidence, "gateway_pubkey": self.gateway_pubkey,
            "gateway_signature": list(self.gateway.sign(message.encode()).signature), "signed_message": message,
            "receipt_sha256": sha256(message), "status": "saved", "explorer_url": None}, task_id

    def test_verifies_gateway_and_worker_signatures_and_raw_output(self):
        receipt, task = self.make_receipt()
        self.assertEqual(verify_receipt(receipt, quote=self.quote, task_id=task, full_log="risk result\n")["task_id"], task)
        with self.assertRaises(IntegrityError):
            verify_receipt(receipt, quote=self.quote, task_id=task, full_log="edited")

    def test_rejects_forged_signer_budget_or_worker_fields(self):
        receipt, task = self.make_receipt()
        for change in (
            {"gateway_pubkey": self.worker_pubkey},
            {"charged_lamports": 50_001},
            {"worker_receipt": {**receipt["worker_receipt"], "exit_code": 1}},
        ):
            altered = dict(receipt, **change)
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                verify_receipt(altered, quote=self.quote, task_id=task, full_log="risk result\n")


if __name__ == "__main__":
    unittest.main()
