"""A trusted HTTP adapter subprocess, separate from arbitrary Python execution."""
import json
import os
from pathlib import Path
import subprocess
import sys

from inference import load_providers, validate_request
from worker_sandbox import TrustedLocalExecutor, MAX_OUTPUT_BYTES


class InferenceExecutor(TrustedLocalExecutor):
    backend = "inference_proxy"
    isolation = {"sandboxed": False, "network": "configured_provider",
                 "output_limit_bytes": MAX_OUTPUT_BYTES,
                 "boundary": "Trusted adapter; model operator receives the prompt"}

    def preflight(self):
        self.providers = load_providers()
        if not self.providers:
            raise RuntimeError("Configure APERTURE_INFERENCE_CONFIG before starting an inference worker.")
        for provider in self.providers.values():
            if provider.api_key_env and not os.getenv(provider.api_key_env):
                raise RuntimeError(f"Missing credential environment variable for provider {provider.id}.")

    def launch(self, task_directory, container_name):
        spec = json.loads((task_directory / "job.json").read_text(encoding="utf-8"))
        code = (task_directory / "payload.py").read_text(encoding="utf-8")
        request = validate_request(code, spec["parameters"], self.providers)
        provider = self.providers[request.provider_id]
        safe_env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC") if name in os.environ}
        safe_env["PYTHONIOENCODING"] = "utf-8"
        safe_env["APERTURE_INFERENCE_CONFIG"] = str(Path(os.environ["APERTURE_INFERENCE_CONFIG"]).resolve())
        if provider.api_key_env:
            safe_env[provider.api_key_env] = os.environ[provider.api_key_env]
        return subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-u", str(Path(__file__).with_name("inference_runner.py")),
                                 str(task_directory)], cwd=task_directory, env=safe_env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
