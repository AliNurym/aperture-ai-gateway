"""Rates depend on the exact reviewed template, never its AST size or input size."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import test_api_security as fixtures
from compute_profiles import SOURCES, csv_rate
from worker_sandbox import DockerSandbox


class ComputeProfileTests(unittest.TestCase):
    def test_operator_tariff_binds_rate_and_affordable_runtime(self):
        with patch.dict(os.environ, {"APERTURE_CSV_RATE_LAMPORTS_SEC": "2500"}):
            fixture = fixtures.GatewayApiSecurityTests()
            fixture.setUp()
        try:
            quote = fixture.quote(code=SOURCES["batch"], budget=10000, runtime=10).json()
            self.assertEqual(quote["rate_lamports"], 2500)
            self.assertEqual(quote["effective_runtime_seconds"], 4)
            self.assertEqual(quote["analysis"]["compute_profile"], "cpu-csv-v2")
            self.assertIsNone(quote["analysis"]["predicted_sec"])
            self.assertEqual(quote["analysis"]["pricing"], "published_cpu_tariff_v1")
            self.assertEqual(fixture.quote(code=SOURCES["batch"], budget=2499).status_code, 422)
            changed = fixture.quote(code=SOURCES["batch"] + "\n# custom source\n").json()
            self.assertIsNone(changed["analysis"]["compute_profile"])
            self.assertEqual(changed["analysis"]["pricing"], "deterministic_ast_lamports_v1")
        finally:
            fixture.tearDown()

    def test_invalid_tariffs_fail_configuration(self):
        for value in ("0", "-1", "1.5", "true", "1000000001", "١٢"):
            with self.subTest(value=value), patch.dict(os.environ, {"APERTURE_CSV_RATE_LAMPORTS_SEC": value}):
                with self.assertRaises(ValueError):
                    csv_rate()

    def test_worker_resolves_mutable_tag_once_and_runs_retained_image_id(self):
        identifier = "sha256:" + "a" * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executor = DockerSandbox("aperture-task:local", root)
            with patch("worker_sandbox.subprocess.run", side_effect=[
                subprocess.CompletedProcess([], 0, stdout="linux\n"),
                subprocess.CompletedProcess([], 0, stdout=identifier + "\n")]):
                executor.preflight()
            command = executor.command(root, "profile-test")
            self.assertIn(identifier, command)
            self.assertNotIn("aperture-task:local", command)
            self.assertEqual(executor.isolation["image_id"], identifier)
            self.assertEqual(executor.isolation["memory_bytes"], 512 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
