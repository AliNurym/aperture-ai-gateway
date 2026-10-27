"""Validate mixed owner-approved plans and resolve explicit model context."""
import copy
import hashlib
import re

from ai_engine import analyze_code_ast
from artifact_store import SAFE_NAME, validate_descriptor
from inference import PREFIX, request_code, validate_request

FIELDS = {"id", "source", "inputs", "parameters", "depends_on", "max_cost_lamports",
          "max_runtime_seconds", "worker_target", "message_inputs"}


def validate_general_plan(core, plan, owner, agent):
    from gateway import QuoteRequest
    by_id, dependencies, cost = {}, {}, 0
    for step in plan["steps"]:
        if (not isinstance(step, dict) or set(step) - FIELDS
                or not isinstance(step.get("id"), str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", step["id"])
                or step["id"] in by_id or not isinstance(step.get("source"), str)
                or type(step.get("max_cost_lamports")) is not int or not 0 < step["max_cost_lamports"] <= 1_000_000_000
                or type(step.get("max_runtime_seconds")) is not int or not 1 <= step["max_runtime_seconds"] <= 180
                or not isinstance(step.get("inputs", []), list) or len(step.get("inputs", [])) > 16
                or not isinstance(step.get("parameters", {}), dict)
                or not isinstance(step.get("depends_on", []), list)
                or any(not isinstance(item, str) for item in step.get("depends_on", []))):
            raise ValueError("Invalid mixed workflow step or explicit bounds.")
        absolute, deps, names = [], set(step.get("depends_on", [])), set()
        for item in step.get("inputs", []):
            if isinstance(item, dict) and set(item) == {"from_step", "artifact"}:
                if not isinstance(item["from_step"], str) or not isinstance(item["artifact"], str) or not SAFE_NAME.fullmatch(item["artifact"]):
                    raise ValueError("Invalid result-file dependency.")
                deps.add(item["from_step"]); name = item["artifact"]
            else:
                item = validate_descriptor(item)
                core.objects.resolve(item, owner=owner, agent=agent)
                absolute.append(item); name = item["name"]
            if name.casefold() in names:
                raise ValueError("Workflow input filenames must be unique.")
            names.add(name.casefold())
        bindings = step.get("message_inputs", [])
        if not isinstance(bindings, list) or len(bindings) > 8:
            raise ValueError("Use at most eight explicit model context files.")
        inference = step["source"].startswith(PREFIX)
        if inference:
            if step.get("inputs"):
                raise ValueError("Use message_inputs to explicitly send verified files to a model.")
            request = validate_request(step["source"], step["parameters"], core.inference_providers)
        elif bindings or analyze_code_ast(step["source"]).get("security") == "DANGEROUS":
            raise ValueError("Python source policy rejected this workflow step.")
        seen = set()
        for binding in bindings:
            if (not isinstance(binding, dict) or set(binding) != {"from_step", "artifact", "message_index"}
                    or not isinstance(binding["from_step"], str)
                    or not isinstance(binding["artifact"], str) or not SAFE_NAME.fullmatch(binding["artifact"])
                    or type(binding["message_index"]) is not int
                    or not 0 <= binding["message_index"] < len(request.messages)
                    or request.messages[binding["message_index"]].role != "user"):
                raise ValueError("Model context must name a result file and a user message.")
            key = (binding["from_step"], binding["artifact"], binding["message_index"])
            if key in seen:
                raise ValueError("Duplicate model context file.")
            seen.add(key); deps.add(binding["from_step"])
        core.job_manifest(QuoteRequest(wallet=owner, agent_pubkey=agent, code=step["source"], job_version=1,
            inputs=absolute, parameters=step.get("parameters", {}), worker_target=step.get("worker_target"),
            max_cost_lamports=step["max_cost_lamports"], max_runtime_seconds=step["max_runtime_seconds"]), resolve=False)
        by_id[step["id"]] = step; dependencies[step["id"]] = deps; cost += step["max_cost_lamports"]
    if cost > plan["max_cost_lamports"]:
        raise ValueError("Step spending caps exceed the owner's total workflow cap.")
    pending, done = set(by_id), set()
    if any(not deps <= set(by_id) or identifier in deps for identifier, deps in dependencies.items()):
        raise ValueError("Unknown or self-dependent workflow step.")
    while pending:
        ready = {identifier for identifier in pending if dependencies[identifier] <= done}
        if not ready:
            raise ValueError("Workflow contains a dependency cycle.")
        pending -= ready; done |= ready


def resolve_step(core, flow, step):
    parameters = copy.deepcopy(step.get("parameters", {}))
    for binding in step.get("message_inputs", []):
        parent = core.store.get("jobs", flow["tasks"].get(binding["from_step"], "")) or {}
        receipt = parent.get("receipt") or {}
        item = next((item for item in receipt.get("artifacts", []) if item["name"] == binding["artifact"]), None)
        if receipt.get("execution_status") != "completed" or item is None:
            raise ValueError("Explicit model context is not successfully settled yet.")
        if not 0 < item["size_bytes"] <= 16000:
            raise ValueError("Explicit model context exceeds 16,000 bytes per file.")
        data = core.objects.resolve(item, owner=flow["owner"], agent=flow["agent_pubkey"]).read_bytes()
        if len(data) != item["size_bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Model context differs from its signed result file.")
        message = parameters["inference"]["messages"][binding["message_index"]]
        message["content"] += "\n\n[Aperture input " + binding["from_step"] + "/" + binding["artifact"] + "]\n" + data.decode("utf-8", errors="strict")
    source = request_code(parameters) if step["source"].startswith(PREFIX) else step["source"]
    if step["source"].startswith(PREFIX):
        validate_request(source, parameters, core.inference_providers)
    return source, parameters
