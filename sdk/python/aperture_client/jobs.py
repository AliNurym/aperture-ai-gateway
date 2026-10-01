"""Immutable data references for agent jobs."""
import hashlib
import json
import re

NAME = re.compile(r"^(?!(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$))[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,78}[A-Za-z0-9_-])?$")
OBJECT = re.compile(r"^obj-[0-9a-f]{32}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
MAX_INPUT_BYTES = 64 * 1024 * 1024


def object_reference(item):
    if (not isinstance(item, dict) or set(item) != {"object_id", "name", "sha256", "size_bytes"}
            or not isinstance(item["name"], str) or not NAME.fullmatch(item["name"])
            or not isinstance(item["object_id"], str) or not OBJECT.fullmatch(item["object_id"])
            or not isinstance(item["sha256"], str) or not DIGEST.fullmatch(item["sha256"])
            or type(item["size_bytes"]) is not int or not 0 < item["size_bytes"] <= MAX_INPUT_BYTES):
        raise ValueError("Invalid immutable job object.")
    return dict(item)


def workload_manifest(code, inputs=(), parameters=None):
    inputs = sorted([object_reference(item) for item in inputs], key=lambda item: item["name"])
    if (len(inputs) > 16 or len({item["name"].casefold() for item in inputs}) != len(inputs)
            or sum(item["size_bytes"] for item in inputs) > MAX_INPUT_BYTES):
        raise ValueError("Job inputs must have unique names and total at most 64 MiB.")
    parameters = {} if parameters is None else parameters
    if not isinstance(parameters, dict):
        raise ValueError("Job parameters must be a JSON object.")
    encoded = json.dumps(parameters, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 32_000:
        raise ValueError("Job parameters exceed 32,000 UTF-8 bytes.")
    return {"version": 1, "runtime": "python", "source_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "inputs": inputs, "parameters": json.loads(encoded)}
