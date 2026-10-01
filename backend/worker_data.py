"""Stage immutable inputs and publish named results outside the job container."""
import base64
import hashlib
import json
import time
from pathlib import Path

from artifact_store import (MAX_ARTIFACT_BYTES, MAX_ARTIFACT_TOTAL_BYTES,
                            MAX_INPUT_BYTES, SAFE_NAME, validate_descriptor)

PREFIX = b"APERTURE_ARTIFACT_V1:"


def prepare_job(task, directory, *, http, api_url, headers):
    spec = task["workload"]
    encoded = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if (hashlib.sha256(encoded.encode()).hexdigest() != task.get("workload_sha256")
            or spec.get("version") != 1 or spec.get("runtime") != "python"
            or spec.get("source_sha256") != task.get("source_hash", task.get("code_sha256"))):
        raise ValueError("Job manifest does not match its admission.")
    inputs = spec.get("inputs")
    if not isinstance(inputs, list):
        raise ValueError("Invalid bounded job inputs.")
    inputs = [validate_descriptor(item) for item in inputs]
    if (len(inputs) > 16
            or len({item["name"].casefold() for item in inputs}) != len(inputs)
            or sum(item["size_bytes"] for item in inputs) > MAX_INPUT_BYTES):
        raise ValueError("Invalid bounded job inputs.")
    input_root = directory / "inputs"
    input_root.mkdir()
    for item in inputs:
        digest, size = hashlib.sha256(), 0
        with http.get(f"{api_url}/tasks/{task['task_id']}/inputs/{item['object_id']}",
                      headers={**headers, "X-Aperture-Lease": task["lease_id"]},
                      stream=True, timeout=(5, 5), allow_redirects=False) as response:
            response.raise_for_status()
            with (input_root / item["name"]).open("xb") as target:
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > item["size_bytes"] or time.time() >= task["execution_deadline"]:
                        raise ValueError("Input download exceeds authorized size or deadline.")
                    digest.update(chunk)
                    target.write(chunk)
        if size != item["size_bytes"] or digest.hexdigest() != item["sha256"]:
            raise ValueError("Input bytes differ from their authorized digest.")
        (input_root / item["name"]).chmod(0o444)
    (directory / "job.json").write_text(encoded, encoding="utf-8")
    runtime = directory / "runtime"
    runtime.mkdir()
    runtime.joinpath("aperture.py").write_bytes(Path(__file__).with_name("aperture_runtime.py").read_bytes())
    runner = (
        "import pathlib,runpy,sys\n"
        "root=pathlib.Path(__file__).resolve().parent\n"
        "sys.path.insert(0,str(root/'runtime'))\n"
        "runpy.run_path(str(root/'payload.py'),run_name='__main__')\n"
    )
    (directory / "runner.py").write_text(runner, encoding="utf-8")


class ResultFrames:
    def __init__(self, append_log):
        self.append_log = append_log
        self.buffer = bytearray()
        self.artifacts = []
        self.names = set()
        self.artifact_bytes = 0
        self.stream_bytes = 0

    def feed(self, chunk):
        self.stream_bytes += len(chunk)
        if self.stream_bytes > 1_000_000 + MAX_ARTIFACT_TOTAL_BYTES * 2:
            raise ValueError("Job result stream exceeds its bounded capacity.")
        self.buffer.extend(chunk)
        while b"\n" in self.buffer:
            line, _, remaining = self.buffer.partition(b"\n")
            self.buffer = bytearray(remaining)
            self.line(bytes(line), terminated=True)
        maximum = MAX_ARTIFACT_BYTES * 2 if self.buffer.startswith(PREFIX) else 1_000_000
        if len(self.buffer) > maximum:
            raise ValueError("Job result frame exceeds its bounded capacity.")

    def line(self, line, terminated):
        if not line.startswith(PREFIX):
            self.append_log(line + (b"\n" if terminated else b""))
            return
        item = json.loads(line[len(PREFIX):])
        if (not isinstance(item, dict) or set(item) != {"name", "content"}
                or not isinstance(item["name"], str) or not SAFE_NAME.fullmatch(item["name"])
                or item["name"].casefold() in self.names or len(self.names) >= 16
                or not isinstance(item["content"], str) or len(item["content"]) > MAX_ARTIFACT_BYTES * 2):
            raise ValueError("Invalid job artifact frame.")
        data = base64.b64decode(item["content"], validate=True)
        if not 0 < len(data) <= MAX_ARTIFACT_BYTES or self.artifact_bytes + len(data) > MAX_ARTIFACT_TOTAL_BYTES:
            raise ValueError("Job artifact capacity exceeded.")
        self.names.add(item["name"].casefold())
        self.artifact_bytes += len(data)
        self.artifacts.append(item)
        self.append_log(f"[Result file: {item['name']} · {len(data)} bytes]\n".encode())

    def finish(self):
        if self.buffer:
            self.line(bytes(self.buffer), terminated=False)
            self.buffer.clear()


def publish_artifacts(task, payload, *, http, api_url, headers):
    artifacts = []
    for item in payload.get("_artifact_blobs", []):
        data = base64.b64decode(item["content"], validate=True)
        digest = hashlib.sha256(data).hexdigest()
        response = http.post(f"{api_url}/tasks/{task['task_id']}/artifacts/authorize",
            headers=headers, timeout=(5, 15), allow_redirects=False,
            json={"name": item["name"], "sha256": digest,
                  "size_bytes": len(data), "lease_id": task["lease_id"]})
        response.raise_for_status()
        authorization = response.json()
        descriptor = {key: authorization[key] for key in ("object_id", "name", "sha256", "size_bytes")}
        validate_descriptor(descriptor)
        if descriptor["name"] != item["name"] or descriptor["sha256"] != digest or descriptor["size_bytes"] != len(data):
            raise ValueError("Artifact upload authorization changed its content.")
        if not authorization.get("uploaded"):
            upload = http.put(f"{api_url}/objects/{descriptor['object_id']}", data=data,
                headers={"X-Aperture-Upload-Token": authorization["upload_token"],
                         "Content-Type": "application/octet-stream"},
                timeout=(5, 30), allow_redirects=False)
            upload.raise_for_status()
            if upload.json() != descriptor:
                raise ValueError("Artifact upload did not retain its immutable descriptor.")
        artifacts.append(descriptor)
    return artifacts
