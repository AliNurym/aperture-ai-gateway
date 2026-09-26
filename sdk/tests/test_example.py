import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).parents[2] / "sdk" / "python"))
from ai_engine import analyze_code_ast


class BudgetedRiskExampleTests(unittest.TestCase):
    def test_agent_example_is_allowlisted_and_reproducible(self):
        project = Path(__file__).parents[2]
        namespace = {"__name__": "aperture_risk_example"}
        exec(compile((project / "examples" / "budgeted_risk_agent.py").read_text(encoding="utf-8"),
                     "budgeted_risk_agent.py", "exec"), namespace)
        source = namespace["CODE"]
        self.assertEqual(analyze_code_ast(source)["security"], "SAFE")
        outputs = [
            subprocess.run([sys.executable, "-I", "-c", source], capture_output=True, text=True,
                           timeout=30, check=True).stdout
            for _ in range(2)
        ]
        self.assertEqual(outputs[0], outputs[1])
        result = json.loads(outputs[0])
        self.assertEqual(result["simulations"], 50_000)
        self.assertEqual(result["seed"], 20260927)
        self.assertIn("Synthetic assumptions", result["caveat"])


if __name__ == "__main__":
    unittest.main()
