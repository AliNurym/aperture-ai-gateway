"""Inference client uses the same canonical authorization and integrity checks."""
import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "python"))
from aperture_client.client import canonical, canonical_quote_message, IntegrityError
from aperture_client.jobs import inference_source, workload_manifest


class InferenceCommitmentTests(unittest.TestCase):
    def test_inference_manifest_preserves_runtime_and_detects_changed_prompt(self):
        parameters = {"inference": {"provider_id": "local", "messages": [{"role": "user", "content": "Бюджет"}], "max_tokens": 64},
                      "offer": {"id": "local", "model": "model", "rate_lamports_sec": 1000}}
        code = inference_source(parameters)
        spec = workload_manifest(code, parameters=parameters)
        self.assertEqual(spec["runtime"], "inference.chat")
        quote = {key: 1 for key in ("quote_id", "wallet", "agent_pubkey", "rate_lamports", "max_cost_lamports",
            "max_runtime_seconds", "expires_at", "passport_version", "program_id", "network", "gateway_pubkey", "treasury")}
        quote.update(code_sha256=hashlib.sha256(code.encode()).hexdigest(), workload=spec,
                     workload_sha256=hashlib.sha256(canonical(spec).encode()).hexdigest())
        message = canonical_quote_message(quote)
        self.assertTrue(message.startswith("Aperture execution authorization v3\n"))
        changed = copy.deepcopy(quote)
        changed["workload"]["parameters"]["inference"]["messages"][0]["content"] = "Different"
        changed["workload_sha256"] = hashlib.sha256(canonical(changed["workload"]).encode()).hexdigest()
        with self.assertRaises(IntegrityError):
            canonical_quote_message(changed)
        with self.assertRaises(ValueError):
            workload_manifest(code, parameters=changed["workload"]["parameters"])

    def test_ordinary_python_parameter_names_do_not_enable_inference(self):
        spec = workload_manifest("print(42)", parameters={"inference": True})
        self.assertEqual(spec["runtime"], "python")


if __name__ == "__main__":
    unittest.main()
