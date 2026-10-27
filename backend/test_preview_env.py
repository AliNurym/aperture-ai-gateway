from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.preview_env import load_local_inference_environment


class PreviewEnvironmentTests(unittest.TestCase):
    def temporary_directory(self):
        root = Path(__file__).resolve().parents[1] / ".aperture" / "test-temp"
        root.mkdir(parents=True, exist_ok=True)
        return TemporaryDirectory(dir=root)

    def test_loads_only_inference_settings_and_preserves_process_values(self):
        with self.temporary_directory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "GEMINI_API_KEY=file-secret\n"
                "APERTURE_GEMINI_MODEL=gemini-test\n"
                "APERTURE_WORKER_RATE_LAMPORTS_SEC=2400\n"
                "BACKEND_PRIVATE_KEY=must-not-load\n",
                encoding="utf-8",
            )
            environment = {"GEMINI_API_KEY": "process-secret"}

            loaded = load_local_inference_environment(env_path, environment)

        self.assertEqual(loaded, (
            "APERTURE_GEMINI_MODEL",
            "APERTURE_WORKER_RATE_LAMPORTS_SEC",
        ))
        self.assertEqual(environment["GEMINI_API_KEY"], "process-secret")
        self.assertEqual(environment["APERTURE_GEMINI_MODEL"], "gemini-test")
        self.assertEqual(environment["APERTURE_WORKER_RATE_LAMPORTS_SEC"], "2400")
        self.assertNotIn("BACKEND_PRIVATE_KEY", environment)

    def test_missing_file_is_a_noop(self):
        with self.temporary_directory() as directory:
            environment = {}
            loaded = load_local_inference_environment(Path(directory) / ".env", environment)

        self.assertEqual(loaded, ())
        self.assertEqual(environment, {})

    def test_loads_deepseek_settings_without_copying_other_secrets(self):
        with self.temporary_directory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "DEEPSEEK_API_KEY=file-secret\n"
                "APERTURE_DEEPSEEK_MODEL=deepseek-flash\n"
                "APERTURE_WORKER_RATE_LAMPORTS_SEC=1500\n"
                "BACKEND_PRIVATE_KEY=must-not-load\n",
                encoding="utf-8",
            )
            environment = {"DEEPSEEK_API_KEY": "process-secret"}
            loaded = load_local_inference_environment(env_path, environment)

        self.assertEqual(loaded, ("APERTURE_DEEPSEEK_MODEL", "APERTURE_WORKER_RATE_LAMPORTS_SEC"))
        self.assertEqual(environment["DEEPSEEK_API_KEY"], "process-secret")
        self.assertEqual(environment["APERTURE_DEEPSEEK_MODEL"], "deepseek-flash")
        self.assertNotIn("BACKEND_PRIVATE_KEY", environment)


if __name__ == "__main__":
    unittest.main()
