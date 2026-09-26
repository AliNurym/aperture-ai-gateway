"""Regression tests for worker startup safety guards."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import base58
import requests
from nacl.signing import VerifyKey

import worker
from worker_identity import WorkerIdentity, receipt_bytes
from worker_journal import WorkerInstanceLock, WorkerJournal
from worker_sandbox import DockerSandbox, MAX_OUTPUT_BYTES, TrustedLocalExecutor


WORKER = Path(__file__).with_name("worker.py")


class WorkerStartupSecurityTests(unittest.TestCase):
    def assert_worker_rejects(self, token: str):
        result = subprocess.run(
            [sys.executable, str(WORKER), "--token", token, "--allow-unsafe-local-execution"],
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unique 16+ character secret", result.stdout + result.stderr)

    def test_example_token_is_rejected(self):
        self.assert_worker_rejects("replace-with-a-long-random-secret")

    def test_short_token_is_rejected(self):
        self.assert_worker_rejects("short")

    def test_environment_gateway_is_used_without_argument(self):
        result = subprocess.run(
            [sys.executable, "-c", "import worker; print(worker.API_URL)"],
            cwd=WORKER.parent, env={**os.environ, "GATEWAY_API_URL": "http://remote-gateway.example:8080"},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "http://remote-gateway.example:8080")


def task_for(code, seconds=2):
    return {
        "task_id": "test-task", "code": code, "source_hash": hashlib.sha256(code.encode()).hexdigest(),
        "max_runtime_seconds": seconds, "execution_deadline": time.time() + seconds,
        "lease_id": "test-lease", "agent_pubkey": "test-agent", "quote_id": "test-quote",
    }


def idle_http():
    client = Mock()
    client.get.return_value = Mock(status_code=200, json=lambda: {"cancelled": False})
    client.post.return_value = Mock(status_code=200)
    return client


class WorkerExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_source_tampering_does_not_launch(self):
        task = task_for("print('accepted')")
        task["code"] = "print('modified')"
        executor = Mock()
        with self.assertRaisesRegex(ValueError, "source hash"):
            worker.execute_task(task, executor, self.root, idle_http())
        executor.launch.assert_not_called()

    def test_expired_deadline_does_not_launch(self):
        task = task_for("print('late')")
        task["execution_deadline"] = time.time() - 1
        executor = TrustedLocalExecutor()
        with patch.object(executor, "launch") as launch:
            result = worker.execute_task(task, executor, self.root, idle_http())
        launch.assert_not_called()
        self.assertEqual(result["exit_code"], 124)
        self.assertEqual(result["execution_time"], 0)

    def test_deadline_does_not_wait_for_hanging_gateway(self):
        client = idle_http()
        client.get.side_effect = lambda *args, **kwargs: (time.sleep(2), Mock(status_code=200, json=lambda: {}))[1]
        task = task_for("import time\ntime.sleep(5)\n", 0.8)
        started = time.monotonic()
        result = worker.execute_task(task, TrustedLocalExecutor(), self.root, client)
        self.assertLess(time.monotonic() - started, 1.7)
        self.assertEqual(result["exit_code"], 124)
        self.assertIn("DEADLINE", result["full_log"])

    def test_unbroken_output_is_bounded_and_hashed_exactly(self):
        task = task_for("print('x' * 2000000, end='')")
        result = worker.execute_task(task, TrustedLocalExecutor(), self.root, idle_http())
        self.assertLessEqual(len(result["full_log"].encode()), MAX_OUTPUT_BYTES)
        self.assertIn("OUTPUT_LIMIT", result["full_log"])
        self.assertEqual(result["exit_code"], 137)
        self.assertEqual(result["output_hash"], hashlib.sha256(result["full_log"].encode()).hexdigest())

    def test_gateway_cancellation_stops_execution(self):
        client = idle_http()
        client.get.return_value = Mock(status_code=200, json=lambda: {"cancelled": True})
        result = worker.execute_task(task_for("import time\ntime.sleep(5)", 3), TrustedLocalExecutor(), self.root, client)
        self.assertEqual(result["exit_code"], 130)
        self.assertLess(result["execution_time"], 2)

    def test_execution_output_preserves_actual_failure(self):
        result = worker.execute_task(task_for("print('before failure')\nraise ValueError('expected')"), TrustedLocalExecutor(), self.root, idle_http())
        self.assertNotEqual(result["exit_code"], 0)
        self.assertIn("before failure", result["full_log"])
        self.assertIn("ValueError: expected", result["full_log"])

    def test_worker_identity_survives_restart_and_binds_attestation(self):
        identity = WorkerIdentity(self.root)
        task = task_for("print('answer')")
        result = worker.result_payload(task, "answer\n", 0.4567, 0, TrustedLocalExecutor())
        signed = identity.attest(task, result, "worker-test")
        VerifyKey(base58.b58decode(signed["worker_pubkey"])).verify(
            receipt_bytes(signed["worker_receipt"]), base58.b58decode(signed["worker_signature"]),
        )
        self.assertEqual(identity.pubkey, WorkerIdentity(self.root).pubkey)
        self.assertEqual(signed["worker_receipt"]["execution_time_ms"], 457)
        altered = {**signed["worker_receipt"], "output_hash": "0" * 64}
        with self.assertRaises(Exception):
            VerifyKey(base58.b58decode(signed["worker_pubkey"])).verify(receipt_bytes(altered), base58.b58decode(signed["worker_signature"]))


class WorkerJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.journal = WorkerJournal(self.root)

    def tearDown(self):
        self.journal.close()
        self.temporary.cleanup()

    def test_result_survives_outage_restart_and_retries_exact_payload(self):
        task = task_for("print('durable')")
        payload = worker.result_payload(task, "durable\n", 0.1, 0, TrustedLocalExecutor())
        self.journal.begin({key: value for key, value in task.items() if key != "code"})
        self.journal.finish(task["task_id"], payload)
        failing = Mock()
        failing.post.side_effect = requests.ConnectionError("offline")
        worker.flush_results(self.journal, failing)
        self.assertTrue(self.journal.blocked())
        self.assertEqual(self.journal.pending(), [])
        self.journal.close()
        self.journal = WorkerJournal(self.root)
        self.journal.connection.execute("UPDATE jobs SET next_attempt=0")
        self.journal.connection.commit()
        recovered = idle_http()
        worker.flush_results(self.journal, recovered)
        self.assertEqual(recovered.post.call_args.kwargs["json"], payload)
        self.assertFalse(self.journal.blocked())

    def test_pending_settlement_keeps_outbox(self):
        task = task_for("print('a')")
        self.journal.begin(task)
        self.journal.finish(task["task_id"], worker.result_payload(task, "a", 1, 0, TrustedLocalExecutor()))
        client = idle_http()
        client.post.return_value.status_code = 202
        worker.flush_results(self.journal, client)
        self.assertTrue(self.journal.blocked())

    def test_interrupted_execution_is_not_reexecuted(self):
        task = task_for("print('original')")
        task.pop("code")
        self.journal.begin(task)
        executor = Mock(wraps=TrustedLocalExecutor())
        executor.backend = "trusted_local"
        executor.isolation = {}
        worker.recover_interrupted(self.journal, executor, WorkerIdentity(self.root))
        executor.recover.assert_called_once()
        executor.launch.assert_not_called()
        pending = self.journal.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["exit_code"], 125)
        self.assertIn("not re-executed", pending[0]["full_log"])
        self.assertIn("worker_signature", pending[0])

    def test_second_coordinator_cannot_share_state(self):
        first = WorkerInstanceLock(self.root)
        try:
            with self.assertRaisesRegex(RuntimeError, "Another worker"):
                WorkerInstanceLock(self.root)
        finally:
            first.close()


@unittest.skipUnless(os.getenv("APERTURE_TEST_DOCKER") == "1", "Real Docker tests require APERTURE_TEST_DOCKER=1 and aperture-task:local image")
class RealDockerIsolationTests(unittest.TestCase):
    def test_real_container_has_no_host_secrets_network_or_writable_image(self):
        self.assertIsNotNone(shutil.which("docker"), "Docker CLI must be installed")
        with tempfile.TemporaryDirectory() as directory:
            executor = DockerSandbox(os.getenv("APERTURE_SANDBOX_IMAGE", "aperture-task:local"), Path(directory))
            executor.preflight()
            code = '''import json, os, socket
result = {"uid": os.getuid(), "secret": os.getenv("APERTURE_TEST_HOST_SECRET"), "docker_socket": os.path.exists("/var/run/docker.sock")}
try:
    open("/image-write-probe", "w").write("bad")
    result["readonly"] = False
except OSError:
    result["readonly"] = True
try:
    socket.create_connection(("1.1.1.1", 443), timeout=0.5)
    result["network_blocked"] = False
except OSError:
    result["network_blocked"] = True
print(json.dumps(result))
'''
            with patch.dict(os.environ, {"APERTURE_TEST_HOST_SECRET": "never-send-to-job"}):
                result = worker.execute_task(task_for(code, 10), executor, Path(directory), idle_http())
            self.assertEqual(result["exit_code"], 0, result["full_log"])
            isolation = json.loads(result["full_log"])
            self.assertEqual(isolation, {"uid": 10001, "secret": None, "docker_socket": False, "readonly": True, "network_blocked": True})

    def test_docker_deadline_stops_silent_task(self):
        with tempfile.TemporaryDirectory() as directory:
            executor = DockerSandbox("aperture-task:local", Path(directory))
            result = worker.execute_task(task_for("import time\ntime.sleep(60)", 2), executor, Path(directory), idle_http())
            self.assertEqual(result["exit_code"], 124)
            self.assertIn("DEADLINE", result["full_log"])


if __name__ == "__main__":
    unittest.main()
