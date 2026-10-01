"""Fast, offline checks for the gateway's trust boundary."""

import unittest

from ai_engine import analyze_code_ast


class SentinelSecurityTests(unittest.TestCase):
    def test_allows_curated_compute_modules(self):
        result = analyze_code_ast("import math\nprint(math.sqrt(9))")
        self.assertEqual(result["security"], "SAFE")

    def test_allows_numpy_and_scores_submodule_imports(self):
        baseline = analyze_code_ast("print(1)")
        for source in ("import numpy as np", "import numpy.linalg as la"):
            with self.subTest(source=source):
                result = analyze_code_ast(source)
                self.assertEqual(result["security"], "SAFE")
                self.assertGreater(result["cpu"], baseline["cpu"])
                self.assertGreater(result["ram"], baseline["ram"])

        self.assertEqual(analyze_code_ast("import os")["security"], "DANGEROUS")

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

if __name__ == "__main__":
    unittest.main()
