"""Functional owner/agent handoff, persistence, and delegated observation."""
import asyncio
import hashlib
import tempfile
import time
import unittest

from solders.keypair import Keypair
from agent_identity import canonical_json, sha256_text
from artifact_store import ArtifactStore
import test_api_security as fixtures


class BytesRequest:
    def __init__(self, data):
        self.data = data

    async def stream(self):
        yield self.data


def stage(store, owner, data=b"department,revenue\nresearch,0.1\nresearch,0.2\n"):
    auth = store.authorize(owner=owner, agent=owner, name="export.csv",
        digest=hashlib.sha256(data).hexdigest(), size=len(data))
    return asyncio.run(store.upload(auth["object_id"], auth["upload_token"], BytesRequest(data)))


class HandoffStoreTests(unittest.TestCase):
    def test_retry_restart_and_independent_file_lifetimes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(directory)
            original = stage(store, "owner")
            assigned = store.assign(original, owner="owner", agent="agent")
            self.assertNotEqual(original["object_id"], assigned["object_id"])
            self.assertEqual(assigned, store.assign(original, owner="owner", agent="agent"))
            self.assertEqual(store.usage(owner="owner", agent="agent")["object_count"], 1)
            store.close()
            store = ArtifactStore(directory)
            self.assertEqual(assigned, store.assign(original, owner="owner", agent="agent"))
            store.release(original, owner="owner", agent="owner")
            self.assertEqual(store.resolve(assigned, owner="owner", agent="agent").read_bytes(), b"department,revenue\nresearch,0.1\nresearch,0.2\n")
            store.release(assigned, owner="owner", agent="agent")
            self.assertEqual(store.usage(owner="owner", agent="agent")["size_bytes"], 0)
            store.close()

    def test_assignment_does_not_grant_another_owner_or_unselected_agent(self):
        store = ArtifactStore()
        try:
            original = stage(store, "owner")
            with self.assertRaises(PermissionError):
                store.assign(original, owner="other", agent="agent")
            assigned = store.assign(original, owner="owner", agent="agent")
            with self.assertRaises(PermissionError):
                store.resolve(assigned, owner="owner", agent="other-agent")
        finally:
            store.close()


class OwnerWorkspaceApiTests(unittest.TestCase):
    def test_report_plan_rejects_steps_unrelated_to_final_result(self):
        import copy
        plan = self.plan()
        extra = copy.deepcopy(plan["steps"][0])
        extra["id"] = "unused"
        plan["steps"].insert(0, extra)
        plan["max_cost_lamports"] += extra["max_cost_lamports"]
        body = self.control("submit-workflow", body={"plan": plan, "request_id": "ab" * 16},
            task_id=sha256_text(canonical_json(plan)), limit=plan["max_cost_lamports"], cursor="ab" * 16)
        response = self.client.post("/owners/workflows/submit", json=body)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("contribute to the final report", response.text)

    def plan(self):
        from workflow_inbox import SOURCES
        reference = self.core.objects.assign(stage(self.core.objects, self.owner), owner=self.owner, agent=self.agent)
        return {"version": 1, "max_cost_lamports": 200000, "steps": [
            {"id": "batch", "source": SOURCES["batch"], "inputs": [reference],
             "parameters": {"input_name": reference["name"], "output_name": "batch.json", "csv_output": False},
             "max_cost_lamports": 100000, "max_runtime_seconds": 10},
            {"id": "report", "source": SOURCES["merge"], "inputs": [{"from_step": "batch", "artifact": "batch.json"}],
             "parameters": {"input_names": ["batch.json"], "output_name": "report.json", "final": True},
             "max_cost_lamports": 100000, "max_runtime_seconds": 10}]}

    def submit_plan(self, plan, request_id="ab" * 16):
        request = self.control("submit-workflow", body={"plan": plan, "request_id": request_id},
            task_id=sha256_text(canonical_json(plan)), limit=plan["max_cost_lamports"], cursor=request_id)
        response = self.client.post("/owners/workflows/submit", json=request)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def agent_control(self, action, *, body=None, task_id=None, limit=None, cursor=None):
        request = {"owner": self.owner, "agent_pubkey": self.agent, "issued_at": int(time.time()),
            "nonce": bytes(Keypair()).hex()[:32]}
        message = "Aperture agent task access v1\naudience:aperture-gateway\n" + canonical_json({"action": action,
            **request, "task_id": task_id, "limit": limit, "cursor": cursor,
            "program_id": str(self.fixture.chain.program_id), "gateway_pubkey": str(self.fixture.chain.ai_signer.pubkey()), "network": "off_chain"})
        return {**request, **(body or {}), "signature": list(bytes(self.fixture.agent.sign_message(message.encode())))}

    def test_same_console_request_retains_one_plan_and_original_host(self):
        plan = self.plan()
        flow = self.submit_plan(plan)
        self.assertEqual(flow, self.submit_plan(plan))
        identifier, host = flow["workflow_id"], "cd" * 16
        claim = self.client.post("/agents/workflows/claim", json=self.agent_control("claim-assigned-workflow",
            body={"workflow_id": identifier, "host_id": host}, task_id=identifier, cursor=host))
        self.assertEqual(claim.status_code, 200, claim.text)
        self.assertEqual(claim.json()["plan"], plan)
        copied = self.client.post("/agents/workflows/claim", json=self.agent_control("claim-assigned-workflow",
            body={"workflow_id": identifier, "host_id": "ef" * 16}, task_id=identifier, cursor="ef" * 16))
        self.assertEqual(copied.status_code, 409)
        progress = {"status": "completed", "steps": []}
        invalid = self.client.post("/agents/workflows/publish", json=self.agent_control("publish-assigned-workflow",
            body={"workflow_id": identifier, "lease_token": claim.json()["lease_token"], "progress": progress}, task_id=identifier,
            cursor=sha256_text(claim.json()["lease_token"] + "\n" + canonical_json(progress))))
        self.assertEqual(invalid.status_code, 409)

    def test_stop_blocks_a_signed_quote_and_does_not_admit_a_new_task(self):
        plan = self.plan()
        flow = self.submit_plan(plan)
        identifier, host = flow["workflow_id"], "cd" * 16
        response = self.client.post("/agents/workflows/claim", json=self.agent_control("claim-assigned-workflow",
            body={"workflow_id": identifier, "host_id": host}, task_id=identifier, cursor=host))
        self.assertEqual(response.status_code, 200, response.text)
        step = plan["steps"][0]
        quote = self.client.post("/quotes", json={"wallet": self.owner, "agent_pubkey": self.agent, "code": step["source"],
            "job_version": 1, "inputs": step["inputs"], "parameters": step["parameters"],
            "max_cost_lamports": 100000, "max_runtime_seconds": 10, "workflow": {"workflow_id": identifier, "step_id": "batch"}})
        self.assertEqual(quote.status_code, 200, quote.text)
        self.assertTrue(quote.json()["message"].startswith("Aperture execution authorization v4\n"))
        stop = self.client.post("/owners/workflows/stop", json=self.control("stop-assigned-workflow",
            body={"workflow_id": identifier}, task_id=identifier))
        self.assertEqual(stop.status_code, 200, stop.text)
        execute = self.client.post("/execute", json={**self.fixture.signed_run(quote.json(), self.fixture.agent, step["source"]),
            "job_version": 1, "inputs": step["inputs"], "parameters": step["parameters"]})
        self.assertEqual(execute.status_code, 409, execute.text)
        self.assertEqual(self.core.store.list("jobs"), [])

    def test_admission_and_workflow_step_commit_together_before_publication(self):
        plan = self.plan()
        identifier, host = self.submit_plan(plan)["workflow_id"], "cd" * 16
        self.client.post("/agents/workflows/claim", json=self.agent_control("claim-assigned-workflow",
            body={"workflow_id": identifier, "host_id": host}, task_id=identifier, cursor=host))
        step = plan["steps"][0]
        body = {"wallet": self.owner, "agent_pubkey": self.agent, "code": step["source"], "job_version": 1,
            "inputs": step["inputs"], "parameters": step["parameters"], "max_cost_lamports": 100000,
            "max_runtime_seconds": 10, "workflow": {"workflow_id": identifier, "step_id": "batch"}}
        quote = self.client.post("/quotes", json=body).json()
        request = {**self.fixture.signed_run(quote, self.fixture.agent, step["source"]), "job_version": 1,
            "inputs": step["inputs"], "parameters": step["parameters"]}
        admitted = self.client.post("/execute", json=request)
        self.assertEqual(admitted.status_code, 200, admitted.text)
        self.assertEqual(self.core.store.assigned_workflow(identifier)["tasks"], {"batch": admitted.json()["task_id"]})
        self.assertEqual(self.client.post("/execute", json=request).json()["task_id"], admitted.json()["task_id"])
        stopped = self.client.post("/owners/workflows/stop", json=self.control("stop-assigned-workflow",
            body={"workflow_id": identifier}, task_id=identifier))
        self.assertEqual(stopped.status_code, 200, stopped.text)
        job = self.core.store.get("jobs", admitted.json()["task_id"])
        self.assertTrue(job["cancelled"])
        self.assertEqual(job["state"], "completed")

    def test_owner_stops_a_leased_task_without_a_live_receiver(self):
        from workflow_inbox import workflow_summary
        plan = self.plan()
        identifier, host = self.submit_plan(plan)["workflow_id"], "cd" * 16
        self.client.post("/agents/workflows/claim", json=self.agent_control("claim-assigned-workflow",
            body={"workflow_id": identifier, "host_id": host}, task_id=identifier, cursor=host))
        step = plan["steps"][0]
        body = {"wallet": self.owner, "agent_pubkey": self.agent, "code": step["source"], "job_version": 1,
            "inputs": step["inputs"], "parameters": step["parameters"], "max_cost_lamports": 100000,
            "max_runtime_seconds": 10, "workflow": {"workflow_id": identifier, "step_id": "batch"}}
        quote = self.client.post("/quotes", json=body).json()
        admitted = self.client.post("/execute", json={**self.fixture.signed_run(quote, self.fixture.agent, step["source"]),
            "job_version": 1, "inputs": step["inputs"], "parameters": step["parameters"]}).json()
        leased = self.fixture.claim()
        self.assertEqual(leased["task_id"], admitted["task_id"])
        stopped = self.client.post("/owners/workflows/stop", json=self.control("stop-assigned-workflow",
            body={"workflow_id": identifier}, task_id=identifier))
        self.assertEqual(stopped.status_code, 200, stopped.text)
        job = self.core.store.get("jobs", admitted["task_id"])
        self.assertTrue(job["cancelled"])
        self.assertEqual(job["receipt"]["execution_status"], "cancelled")
        self.assertEqual(workflow_summary(self.core, self.core.store.assigned_workflow(identifier))["status"], "stopped")
        self.assertEqual(self.client.post("/quotes", json=body).status_code, 409)
        self.assertEqual(len(self.core.store.list("jobs")), 1)

    def setUp(self):
        self.fixture = fixtures.GatewayApiSecurityTests()
        self.fixture.setUp()
        self.core = self.fixture.core
        self.client = self.fixture.client
        self.owner = str(self.fixture.owner.pubkey())
        self.agent = str(self.fixture.agent.pubkey())
        self.fixture.passport()

    def tearDown(self):
        if self.core._objects is not None:
            self.core._objects.close()
        self.fixture.tearDown()

    def control(self, action, *, signer=None, agent=None, body=None, task_id=None, limit=None, cursor=None):
        request = {"owner": self.owner, "agent_pubkey": agent or self.agent,
            "issued_at": int(time.time()), "nonce": bytes(Keypair()).hex()[:32]}
        message = "Aperture owner control v1\naudience:aperture-gateway\n" + canonical_json({
            "action": action, **request, "task_id": task_id, "limit": limit, "cursor": cursor,
            "program_id": str(self.fixture.chain.program_id),
            "gateway_pubkey": str(self.fixture.chain.ai_signer.pubkey()), "network": "off_chain"})
        return {**request, **(body or {}), "signature": list(bytes((signer or self.fixture.owner).sign_message(message.encode())))}

    def test_owner_uploaded_file_becomes_a_real_delegated_job_input(self):
        original = stage(self.core.objects, self.owner)
        request = self.control("assign-object", body=original, task_id=original["object_id"],
            limit=original["size_bytes"], cursor=original["name"] + ":" + original["sha256"])
        response = self.client.post("/owners/objects/assign", json=request)
        self.assertEqual(response.status_code, 200, response.text)
        assigned = response.json()["reference"]
        quote = self.fixture.quote(agent=self.fixture.agent)
        self.assertEqual(quote.status_code, 200, quote.text)
        job = self.client.post("/quotes", json={"wallet": self.owner, "agent_pubkey": self.agent,
            "code": "from aperture import read_csv\nprint(list(read_csv('export.csv')))\n",
            "max_cost_lamports": 100000, "max_runtime_seconds": 10, "job_version": 1,
            "inputs": [assigned], "parameters": {}})
        self.assertEqual(job.status_code, 200, job.text)
        replay = self.client.post("/owners/objects/assign", json=request)
        self.assertEqual(replay.status_code, 401)

    def test_agent_cannot_sign_owner_handoff(self):
        item = stage(self.core.objects, self.owner)
        request = self.control("assign-object", signer=self.fixture.agent, body=item,
            task_id=item["object_id"], limit=item["size_bytes"], cursor=item["name"] + ":" + item["sha256"])
        self.assertEqual(self.client.post("/owners/objects/assign", json=request).status_code, 401)

    def test_observation_is_read_only_scoped_and_reusable_without_new_signatures(self):
        task = self.fixture.admit(agent=self.fixture.agent)
        response = self.client.post("/owners/agents/observe", json=self.control("observe-agent"))
        self.assertEqual(response.status_code, 200, response.text)
        headers = {"X-Aperture-Owner-View": response.json()["view_token"]}
        for _ in range(2):
            response = self.client.get(f"/owners/agents/{self.agent}/overview", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["tasks"][0]["task_id"], task["task_id"])
            self.assertNotIn("task_access_token", response.text)
        other = str(Keypair().pubkey())
        self.assertEqual(self.client.get(f"/owners/agents/{other}/overview", headers=headers).status_code, 401)
        self.assertEqual(self.client.get(f"/owners/agents/{self.agent}/overview").status_code, 401)


if __name__ == "__main__":
    unittest.main()
