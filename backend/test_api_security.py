"""HTTP-level tests for gateway trust boundaries (no Solana RPC required)."""

import os
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

os.environ["APERTURE_WORKER_TOKEN"] = "test-worker-secret"
os.environ["APERTURE_DEMO_MODE"] = "false"

from fastapi.testclient import TestClient
from solders.keypair import Keypair

os.environ["BACKEND_PRIVATE_KEY"] = json.dumps(list(bytes(Keypair())))
import main
from task_auth import execution_message


class GatewayApiSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.worker_headers = {
            "X-Aperture-Worker-Token": "test-worker-secret",
            "X-Aperture-Worker-Id": "test-worker-a",
        }

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")

    def test_health_does_not_expose_secrets(self):
        with patch.object(main.solana_client, "get_protocol_config", new=AsyncMock(return_value=None)):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["worker_auth_configured"])
        self.assertNotIn("test-worker-secret", response.text)

    def test_example_worker_token_is_rejected(self):
        original_token = main.WORKER_TOKEN
        try:
            main.WORKER_TOKEN = "replace-with-a-long-random-secret"
            self.assertFalse(self.client.get("/health").json()["worker_auth_configured"])
            response = self.client.get("/get_task", headers={
                "X-Aperture-Worker-Token": main.WORKER_TOKEN,
                "X-Aperture-Worker-Id": "worker",
            })
            self.assertEqual(response.status_code, 503)
        finally:
            main.WORKER_TOKEN = original_token

    def test_rate_limit_rejects_excess_requests_in_window(self):
        original_buckets = dict(main.request_rate_buckets)
        try:
            main.request_rate_buckets.clear()
            main.enforce_rate_limit("execute", "test-client", 2)
            main.enforce_rate_limit("execute", "test-client", 2)
            with self.assertRaises(main.HTTPException) as blocked:
                main.enforce_rate_limit("execute", "test-client", 2)
            self.assertEqual(blocked.exception.status_code, 429)
        finally:
            main.request_rate_buckets.clear()
            main.request_rate_buckets.update(original_buckets)

    def test_worker_queue_requires_authentication(self):
        self.assertEqual(self.client.get("/get_task").status_code, 401)
        self.assertEqual(self.client.get("/get_task", headers={"X-Aperture-Worker-Token": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/get_task", headers=self.worker_headers).status_code, 200)

    def test_unknown_task_cannot_be_streamed_or_settled(self):
        stream = self.client.post("/stream_log", headers=self.worker_headers, json={"task_id": "task-unknown", "lines": ["hello"]})
        result = self.client.post("/submit_result", headers=self.worker_headers, json={"task_id": "task-unknown", "output": "hello", "execution_time": 0.1})
        self.assertEqual(stream.status_code, 404)
        self.assertEqual(result.status_code, 404)

    def test_request_signature_message_must_match_payload(self):
        challenge = self.client.post("/execute/challenge", json={"code": "print('hello')", "wallet": "DEMO_DEVNET_SOLANA_GUEST"}).json()
        response = self.client.post("/execute", json={
            "code": "print('hello')",
            "wallet": "DEMO_DEVNET_SOLANA_GUEST",
            "signature": [0] * 64,
            "message": "a stale signature message",
            "authorization_nonce": challenge["nonce"],
            "authorization_expires_at": challenge["expires_at"],
        })
        self.assertEqual(response.status_code, 401)

    def test_authenticated_worker_can_complete_a_known_task(self):
        wallet = "11111111111111111111111111111111"
        code = "import math\nprint(math.sqrt(9))"
        payload = {
            "code": code,
            "wallet": wallet,
            "signature": [1] * 64,
        }
        challenge = self.client.post("/execute/challenge", json={"code": code, "wallet": wallet}).json()
        payload.update({
            "message": execution_message(wallet, code, challenge["nonce"], challenge["expires_at"]),
            "authorization_nonce": challenge["nonce"],
            "authorization_expires_at": challenge["expires_at"],
        })
        with patch("main.verify_signature", return_value=True), patch.object(main.solana_client, "get_channel_state", new=AsyncMock(return_value={"balance_lamports": 1_000_000_000})), patch.object(main.solana_client, "update_burn_rate", new=AsyncMock(return_value="devnet-test-signature")):
            submitted = self.client.post("/execute", json=payload)
            self.assertEqual(submitted.status_code, 200)
            task_id = submitted.json()["task_id"]
            task_access_token = submitted.json()["task_access_token"]

            claimed = self.client.get("/get_task", headers=self.worker_headers)
            self.assertEqual(claimed.status_code, 200)
            self.assertEqual(claimed.json()["task_id"], task_id)

            streamed = self.client.post("/stream_log", headers=self.worker_headers, json={"task_id": task_id, "node_id": "test-worker-a", "lines": ["3.0\n"]})
            self.assertEqual(streamed.status_code, 200)

            settled = self.client.post("/submit_result", headers=self.worker_headers, json={"task_id": task_id, "output": "3.0\n", "full_log": "3.0\n", "execution_time": 0.1})
            self.assertEqual(settled.status_code, 200)
            self.assertEqual(settled.json()["settlement_type"], "DEVNET")

        result = self.client.get(f"/result/{task_id}?access_token={task_access_token}")
        self.assertEqual(result.json()["status"], "completed")

    def test_execution_authorization_cannot_be_replayed(self):
        wallet = "11111111111111111111111111111111"
        code = "print('once')"
        challenge = self.client.post("/execute/challenge", json={"code": code, "wallet": wallet}).json()
        payload = {
            "code": code,
            "wallet": wallet,
            "signature": [1] * 64,
            "message": challenge["message"],
            "authorization_nonce": challenge["nonce"],
            "authorization_expires_at": challenge["expires_at"],
        }
        with patch("main.verify_signature", return_value=True), patch.object(main.solana_client, "get_channel_state", new=AsyncMock(return_value={"balance_lamports": 1_000_000_000})), patch.object(main.solana_client, "update_burn_rate", new=AsyncMock(return_value="devnet-test-signature")):
            first = self.client.post("/execute", json=payload)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(self.client.post("/execute", json=payload).status_code, 401)
        task_id = first.json()["task_id"]
        main.active_tasks_rates.pop(task_id, None)
        main.pending_tasks[:] = [task for task in main.pending_tasks if task["task_id"] != task_id]

    def test_payment_channel_rejects_parallel_tasks(self):
        wallet = "11111111111111111111111111111111"
        main.active_tasks_rates["task-existing"] = {"wallet": wallet}
        try:
            code = "print('parallel')"
            challenge = self.client.post("/execute/challenge", json={"code": code, "wallet": wallet}).json()
            payload = {"code": code, "wallet": wallet, "signature": [1] * 64, "message": challenge["message"], "authorization_nonce": challenge["nonce"], "authorization_expires_at": challenge["expires_at"]}
            with patch("main.verify_signature", return_value=True):
                self.assertEqual(self.client.post("/execute", json=payload).status_code, 409)
        finally:
            main.active_tasks_rates.pop("task-existing", None)

    def test_task_output_requires_its_capability_token(self):
        task_id = "task-private-output"
        token = "private-capability-token"
        main.active_tasks_rates[task_id] = {"wallet": "wallet", "access_token": token}
        try:
            self.assertEqual(self.client.get(f"/stream_log/{task_id}").status_code, 404)
            self.assertEqual(self.client.get(f"/stream_log/{task_id}?access_token=wrong").status_code, 404)
            self.assertEqual(self.client.get(f"/stream_log/{task_id}?access_token={token}").status_code, 200)
            self.assertEqual(self.client.post(f"/stop/{task_id}").status_code, 404)
        finally:
            main.active_tasks_rates.pop(task_id, None)

    def test_failed_live_settlement_keeps_task_available_for_retry(self):
        task_id = "task-off-chain"
        main.active_tasks_rates[task_id] = {
            "wallet": "11111111111111111111111111111111",
            "rate_sol": 0.000001,
            "ai_verdict": "allowed",
            "access_token": "off-chain-capability",
        }
        main.claimed_tasks[task_id] = {"task": {"task_id": task_id}, "worker_id": "test-worker-a", "claimed_at": time.time()}
        try:
            with patch.object(main.solana_client, "update_burn_rate", new=AsyncMock(return_value=None)):
                response = self.client.post("/submit_result", headers=self.worker_headers, json={"task_id": task_id, "output": "done", "execution_time": 1})
            self.assertEqual(response.status_code, 503)
            self.assertIn(task_id, main.active_tasks_rates)
            self.assertIn(task_id, main.claimed_tasks)
        finally:
            main.active_tasks_rates.pop(task_id, None)
            main.claimed_tasks.pop(task_id, None)

    def test_demo_settlement_is_explicitly_off_chain(self):
        task_id = "task-demo-off-chain"
        main.active_tasks_rates[task_id] = {
            "wallet": "11111111111111111111111111111111",
            "rate_sol": 0.000001,
            "ai_verdict": "allowed",
            "access_token": "demo-capability",
        }
        main.claimed_tasks[task_id] = {"task": {"task_id": task_id}, "worker_id": "test-worker-a", "claimed_at": time.time()}
        original_demo_mode = main.DEMO_MODE
        try:
            main.DEMO_MODE = True
            with patch.object(main.solana_client, "update_burn_rate", new=AsyncMock(return_value=None)):
                response = self.client.post("/submit_result", headers=self.worker_headers, json={"task_id": task_id, "output": "done", "execution_time": 1})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["settlement_type"], "OFF_CHAIN")
            self.assertIsNone(response.json()["explorer_url"])
        finally:
            main.DEMO_MODE = original_demo_mode
            main.active_tasks_rates.pop(task_id, None)
            main.claimed_tasks.pop(task_id, None)

    def test_expired_worker_lease_stops_billing_without_duplicate_execution(self):
        task_id = "task-expired-lease"
        task = {"task_id": task_id, "code": "print(1)", "wallet": "11111111111111111111111111111111"}
        main.active_tasks_rates[task_id] = {"wallet": task["wallet"], "access_token": "expired-capability"}
        main.claimed_tasks[task_id] = {"task": task, "worker_id": "crashed-worker", "claimed_at": time.time() - main.TASK_LEASE_SECONDS - 1}
        try:
            with patch.object(main.solana_client, "update_burn_rate", new=AsyncMock(return_value="stop-signature")):
                response = self.client.get("/get_task", headers=self.worker_headers)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["task_id"])
            self.assertEqual(main.completed_tasks[task_id], "EXECUTION_LEASE_EXPIRED")
        finally:
            main.claimed_tasks.pop(task_id, None)
            main.active_tasks_rates.pop(task_id, None)

    def test_worker_cannot_settle_another_workers_lease(self):
        task_id = "task-owned-by-another-worker"
        main.active_tasks_rates[task_id] = {"wallet": "wallet", "rate_sol": 0, "access_token": "token"}
        main.claimed_tasks[task_id] = {"task": {"task_id": task_id}, "worker_id": "worker-a", "claimed_at": time.time()}
        other_worker_headers = {
            "X-Aperture-Worker-Token": "test-worker-secret",
            "X-Aperture-Worker-Id": "worker-b",
        }
        try:
            response = self.client.post("/submit_result", headers=other_worker_headers, json={"task_id": task_id, "output": "nope", "execution_time": 1})
            self.assertEqual(response.status_code, 409)
        finally:
            main.active_tasks_rates.pop(task_id, None)
            main.claimed_tasks.pop(task_id, None)

    def test_cancellation_is_visible_only_to_the_leasing_worker(self):
        task_id = "task-cancelled"
        access_token = "cancel-capability"
        main.active_tasks_rates[task_id] = {"wallet": "wallet", "access_token": access_token}
        main.claimed_tasks[task_id] = {"task": {"task_id": task_id}, "worker_id": "test-worker-a", "claimed_at": time.time()}
        try:
            with patch.object(main.solana_client, "update_burn_rate", new=AsyncMock(return_value="devnet-test-signature")):
                stopped = self.client.post(f"/stop/{task_id}?access_token={access_token}")
            self.assertEqual(stopped.status_code, 200)
            status = self.client.get(f"/worker_task_status/{task_id}", headers=self.worker_headers)
            self.assertEqual(status.status_code, 200)
            self.assertTrue(status.json()["cancelled"])
            other_headers = {"X-Aperture-Worker-Token": "test-worker-secret", "X-Aperture-Worker-Id": "worker-b"}
            self.assertEqual(self.client.get(f"/worker_task_status/{task_id}", headers=other_headers).status_code, 404)
        finally:
            main.active_tasks_rates.pop(task_id, None)
            main.claimed_tasks.pop(task_id, None)
            main.cancelled_tasks.pop(task_id, None)

    def test_completed_artifact_retention_is_bounded(self):
        original_limit = main.MAX_COMPLETED_TASKS
        snapshots = [dict(mapping) for mapping in (
            main.completed_tasks,
            main.completed_task_access,
            main.completed_task_times,
            main.full_logs,
            main.streamed_logs,
            main.streamed_log_bytes,
        )]
        try:
            main.MAX_COMPLETED_TASKS = 2
            for mapping in (main.completed_tasks, main.completed_task_access, main.completed_task_times, main.full_logs, main.streamed_logs, main.streamed_log_bytes):
                mapping.clear()
            for task_id in ("task-old", "task-middle", "task-new"):
                main.store_completed_task(task_id, task_id, task_id, f"cap-{task_id}")
            self.assertNotIn("task-old", main.completed_tasks)
            self.assertEqual(set(main.completed_tasks), {"task-middle", "task-new"})
            self.assertNotIn("task-old", main.full_logs)
        finally:
            main.MAX_COMPLETED_TASKS = original_limit
            for mapping, snapshot in zip(
                (main.completed_tasks, main.completed_task_access, main.completed_task_times, main.full_logs, main.streamed_logs, main.streamed_log_bytes),
                snapshots,
            ):
                mapping.clear()
                mapping.update(snapshot)


if __name__ == "__main__":
    unittest.main()
