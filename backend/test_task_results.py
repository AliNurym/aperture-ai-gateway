"""End-to-end result evidence without submitting real Solana transactions."""
import os
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("APERTURE_WORKER_TOKEN", "test-worker-secret")
from solders.keypair import Keypair
os.environ.setdefault("BACKEND_PRIVATE_KEY", json.dumps(list(bytes(Keypair()))))
from fastapi.testclient import TestClient
import main


class TaskResultTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.task_id = "task-result-regression"
        self.token = "result-reader-capability"
        self.headers = {"X-Aperture-Worker-Token": main.WORKER_TOKEN, "X-Aperture-Worker-Id": "result-worker"}
        main.active_tasks_rates[self.task_id] = {
            "wallet": "11111111111111111111111111111111", "rate_sol": 0.000001,
            "ai_verdict": "allowed", "access_token": self.token,
        }
        main.claimed_tasks[self.task_id] = {"worker_id": "result-worker", "claimed_at": time.time()}

    def tearDown(self):
        for mapping in (main.active_tasks_rates, main.claimed_tasks, main.completed_tasks,
                        main.completed_task_access, main.completed_task_times,
                        main.completed_receipts, main.full_logs):
            mapping.pop(self.task_id, None)
        self.client.close()

    def test_failed_process_keeps_failure_and_settlement_evidence(self):
        original_demo_mode = main.DEMO_MODE
        try:
            main.DEMO_MODE = True
            with patch.object(main.solana_client, "update_burn_rate", new=AsyncMock(return_value=None)):
                response = self.client.post("/submit_result", headers=self.headers, json={
                    "task_id": self.task_id, "output": "ZeroDivisionError", "execution_time": 0.1, "exit_code": 1,
                })
        finally:
            main.DEMO_MODE = original_demo_mode
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f"/result/{self.task_id}").status_code, 404)
        for route in ("result", "stream_log"):
            result = self.client.get(f"/{route}/{self.task_id}", params={"access_token": self.token}).json()
            self.assertEqual(result["receipt"]["execution_status"], "failed")
            self.assertEqual(result["receipt"]["exit_code"], 1)
            self.assertEqual(result["receipt"]["worker_id"], "result-worker")
            self.assertEqual(result["receipt"]["settlement_type"], "OFF_CHAIN")
            self.assertIsNone(result["receipt"]["explorer_url"])

    def test_invalid_exit_code_does_not_consume_the_task(self):
        response = self.client.post("/submit_result", headers=self.headers, json={
            "task_id": self.task_id, "output": "hello", "exit_code": "success",
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn(self.task_id, main.active_tasks_rates)

    def test_expired_lease_is_not_a_successful_execution(self):
        main.store_completed_task(self.task_id, "EXECUTION_LEASE_EXPIRED", "", self.token)
        result = self.client.get(f"/stream_log/{self.task_id}", params={"access_token": self.token}).json()
        self.assertEqual(result["receipt"]["execution_status"], "failed")
        self.assertEqual(result["receipt"]["settlement_type"], "UNKNOWN")


class WorkerExitStatusTests(unittest.TestCase):
    def test_python_exception_is_reported_as_nonzero_exit(self):
        import worker
        with patch("worker.requests.post"):
            output, duration, exit_code = worker.run_python_code_with_heartbeat("print(1 / 0)", "test-failure")
        self.assertNotEqual(exit_code, 0)
        self.assertIn("ZeroDivisionError", output)
        self.assertGreaterEqual(duration, 0)

    def test_successful_python_output_retains_zero_exit(self):
        import worker
        with patch("worker.requests.post"):
            output, _, exit_code = worker.run_python_code_with_heartbeat("print(6 * 7)", "test-success")
        self.assertEqual(exit_code, 0)
        self.assertEqual(output.strip(), "42")


if __name__ == "__main__":
    unittest.main()
