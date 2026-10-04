"""Per-task execution boundary. The coordinator never enters the task container."""

from __future__ import annotations

import os
import hashlib
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
        self.isolation = dict(type(self).isolation)
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
                ["docker", "image", "inspect", "--format", "{{.Id}}", self.image],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "Sandbox image is missing. Build it with: "
                    "docker build -f backend/Dockerfile.sandbox -t aperture-task:local backend"
                )
            image_id = result.stdout.strip()
            if not image_id.startswith("sha256:") or len(image_id) != 71 or any(char not in "0123456789abcdef" for char in image_id[7:]):
                raise RuntimeError("Docker did not report a valid immutable task image ID.")
            self.image = image_id
            self.isolation["image_id"] = image_id
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
            "--entrypoint", "python", self.image, "-I", "-u",
            "/task/runner.py" if (task_directory / "runner.py").exists() else "/task/payload.py",
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

    def __init__(self, approved_source_directory: Path | None = None):
        self.approved_source_directory = approved_source_directory
        self.approved_hashes = None
        self.isolation = dict(type(self).isolation)
        self.isolation["python_version"] = sys.version.split()[0]

    def preflight(self):
        if self.approved_source_directory is None:
            return
        directory = self.approved_source_directory.resolve(strict=True)
        if not directory.is_dir():
            raise RuntimeError("Trusted source directory must be a directory of reviewed Python files.")
        sources = list(directory.glob("*.py"))
        if not sources:
            raise RuntimeError("Trusted source directory contains no reviewed Python files.")
        self.approved_hashes = set()
        for source in sources:
            data = source.read_bytes()
            if not data or len(data) > 65_536:
                raise RuntimeError("Approved Python sources must contain between 1 and 65,536 bytes.")
            data.decode("utf-8")
            self.approved_hashes.add(hashlib.sha256(data).hexdigest())
        self.isolation.update({"source_policy": "exact_hash_allowlist", "approved_source_count": len(self.approved_hashes)})

    def launch(self, task_directory: Path, container_name: str):
        if self.approved_source_directory is not None and self.approved_hashes is None:
            raise RuntimeError("Trusted source preflight must complete before execution.")
        if self.approved_hashes is not None:
            source_hash = hashlib.sha256((task_directory / "payload.py").read_bytes()).hexdigest()
            if source_hash not in self.approved_hashes:
                raise PermissionError("Source was not approved by this trusted local worker's operator.")
        safe_env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC") if name in os.environ}
        safe_env["PYTHONIOENCODING"] = "utf-8"
        safe_env["OPENBLAS_NUM_THREADS"] = "1"
        safe_env["OMP_NUM_THREADS"] = "1"
        return subprocess.Popen(
            [sys.executable, "-I", "-u", str(task_directory / ("runner.py" if (task_directory / "runner.py").exists() else "payload.py"))],
            cwd=task_directory, env=safe_env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0,
        )

    def stop(self, process, container_name: str):
        if process.poll() is None:
            process.kill()

    def recover(self, container_name: str):
        pass
