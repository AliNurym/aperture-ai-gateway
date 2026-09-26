"""Fast, offline checks for the gateway's trust boundary."""

import hashlib
import unittest

from ai_engine import analyze_code_ast
from task_auth import execution_message


class SentinelSecurityTests(unittest.TestCase):
    def test_allows_curated_compute_modules(self):
        result = analyze_code_ast("import math\nprint(math.sqrt(9))")
        self.assertEqual(result["security"], "SAFE")

    def test_blocks_dynamic_import(self):
        result = analyze_code_ast("__import__('os').system('whoami')")
        self.assertEqual(result["security"], "DANGEROUS")

    def test_blocks_unapproved_module(self):
        result = analyze_code_ast("import pathlib")
        self.assertEqual(result["security"], "DANGEROUS")

    def test_blocks_private_module_escape(self):
        result = analyze_code_ast("import random\nrandom._os.listdir('.')")
        self.assertEqual(result["security"], "DANGEROUS")

    def test_enforces_source_limit(self):
        result = analyze_code_ast("#" * 32_001)
        self.assertEqual(result["security"], "DANGEROUS")

    def test_execution_message_is_payload_bound(self):
        wallet = "wallet-one"
        code = "print('safe')"
        other_code = "print('different')"
        expected = execution_message(wallet, code)
        other = execution_message(wallet, other_code)
        self.assertIn(hashlib.sha256(code.encode()).hexdigest(), expected)
        self.assertNotEqual(expected, other)


if __name__ == "__main__":
    unittest.main()
