"""Per-task execution boundary. The coordinator never enters the task container."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


MAX_OUTPUT_BYTES = 1_000_000
MAX_RUNTIME_SECONDS = 180.0
MEMORY_BYTES = 512 * 1024 * 1024
CPU_LIMIT = "1.0"
PID_LIMIT = 64


class DockerSandbox:
    backend = "docker"
    isolation = {
        "network": "none", "read_only": True, "user": "10001:10001",
        "memory_bytes": MEMORY_BYTES, "cpus": float(CPU_LIMIT), "pids": PID_LIMIT,
        "output_limit_bytes": MAX_OUTPUT_BYTES,
    }

    def __init__(self, image: str, state_root: Path, host_state_root: str | None = None):
        self.image = image
        self.state_root = state_root.resolve()
        self.host_state_root = host_state_root

    def preflight(self):
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.OSType}}"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0 or result.stdout.strip() != "linux":
                raise RuntimeError("Docker must be running with Linux containers.")
            result = subprocess.run(
                ["docker", "image", "inspect", self.image],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "Sandbox image is missing. Build it with: "
                    "docker build -f backend/Dockerfile.sandbox -t aperture-task:local backend"
                )
        except FileNotFoundError as exc:
            raise RuntimeError("Docker CLI is missing. Install Docker with Linux container support.") from exc

    def host_source(self, task_directory: Path) -> str:
        directory = task_directory.resolve()
        relative = directory.relative_to(self.state_root)
        if self.host_state_root:
            source = self.host_state_root.rstrip("/\\") + "/" + relative.as_posix()
        else:
            source = str(directory)
        # --mount uses comma-separated fields, without a shell. Refuse an
        # ambiguous path rather than accidentally mounting any other source.
        if "," in source or "\n" in source or "\r" in source:
            raise ValueError("Sandbox source path cannot contain commas or line breaks.")
        return source

    def command(self, task_directory: Path, container_name: str):
        return [
            "docker", "run", "--rm", "--pull=never", "--name", container_name,
            "--network=none", "--read-only", "--user=10001:10001",
            "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
            "--memory", str(MEMORY_BYTES), "--memory-swap", str(MEMORY_BYTES),
            "--cpus", CPU_LIMIT, "--pids-limit", str(PID_LIMIT),
            "--ulimit", "nofile=64:64", "--ulimit", "core=0:0",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=33554432,mode=1777",
            "--mount", f"type=bind,source={self.host_source(task_directory)},target=/task,readonly",
            "--workdir", "/tmp", "--env", "PYTHONIOENCODING=utf-8",
            "--env", "OPENBLAS_NUM_THREADS=1", "--env", "OMP_NUM_THREADS=1",
            "--entrypoint", "python", self.image, "-I", "-u", "/task/payload.py",
        ]

    def launch(self, task_directory: Path, container_name: str):
        return subprocess.Popen(
            self.command(task_directory, container_name), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0,
        )

    def stop(self, process, container_name: str):
        self.recover(container_name)
        if process.poll() is None:
            process.kill()

    def recover(self, container_name: str):
        # This only names a container generated from this worker/task identity.
        subprocess.run(
            ["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=10, check=False,
        )


class TrustedLocalExecutor:
    """Explicit development fallback. It is deliberately not labeled a sandbox."""
    backend = "trusted_local"
    isolation = {"sandboxed": False, "output_limit_bytes": MAX_OUTPUT_BYTES}

    def preflight(self):
        pass

    def launch(self, task_directory: Path, container_name: str):
        safe_env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC") if name in os.environ}
        safe_env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.Popen(
            [sys.executable, "-I", "-u", str(task_directory / "payload.py")],
            cwd=task_directory, env=safe_env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0,
        )

    def stop(self, process, container_name: str):
        if process.poll() is None:
            process.kill()

    def recover(self, container_name: str):
        pass
