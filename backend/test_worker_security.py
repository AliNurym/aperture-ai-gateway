"""Regression tests for worker startup safety guards."""

import subprocess
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
