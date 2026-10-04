import copy
import json
import sys
import types
import unittest
from pathlib import Path

from solders.keypair import Keypair

sys.path.insert(0, str(Path(__file__).parents[1] / "python"))
from aperture_client.client import canonical, sha256
from aperture_client.assigned_workflows import verify_assigned_plan


class AssignedPlanTests(unittest.TestCase):
    def setUp(self):
        owner, agent = Keypair(), Keypair()
        self.client = types.SimpleNamespace(owner=str(owner.pubkey()), agent=str(agent.pubkey()),
            program_id=str(Keypair().pubkey()), gateway_pubkey=str(Keypair().pubkey()), network="off_chain")
        plan = {"version": 1, "max_cost_lamports": 10000,
            "steps": [{"id": "one", "source": "print(42)", "inputs": [], "parameters": {},
                       "max_cost_lamports": 10000, "max_runtime_seconds": 10}]}
        request_id = "ab" * 16
        digest = sha256(canonical(plan))
        message = "Aperture owner control v1\naudience:aperture-gateway\n" + canonical({"action": "submit-workflow",
            "owner": self.client.owner, "agent_pubkey": self.client.agent, "issued_at": 1700000000,
            "nonce": "c" * 32, "task_id": digest, "limit": 10000, "cursor": request_id,
            "program_id": self.client.program_id, "gateway_pubkey": self.client.gateway_pubkey, "network": "off_chain"})
        self.value = {"plan": plan, "owner": self.client.owner, "agent_pubkey": self.client.agent,
            "request_id": request_id, "plan_sha256": digest, "owner_signed_message": message,
            "owner_signature": list(bytes(owner.sign_message(message.encode()))),
            "workflow_id": "flow-" + sha256(canonical({"owner": self.client.owner, "agent_pubkey": self.client.agent, "request_id": request_id}))}

    def test_original_owner_approval_remains_verifiable_after_restart(self):
        restored = json.loads(json.dumps(self.value))
        self.assertEqual(verify_assigned_plan(self.client, restored), self.value)

    def test_changing_budget_and_digest_does_not_change_owner_approval(self):
        changed = copy.deepcopy(self.value)
        changed["plan"]["max_cost_lamports"] = 20000
        changed["plan_sha256"] = sha256(canonical(changed["plan"]))
        with self.assertRaisesRegex(ValueError, "different plan, budget or deployment"):
            verify_assigned_plan(self.client, changed)

    def test_signed_plan_is_bound_to_this_host_deployment(self):
        self.client.gateway_pubkey = str(Keypair().pubkey())
        with self.assertRaisesRegex(ValueError, "different plan, budget or deployment"):
            verify_assigned_plan(self.client, self.value)


if __name__ == "__main__":
    unittest.main()
