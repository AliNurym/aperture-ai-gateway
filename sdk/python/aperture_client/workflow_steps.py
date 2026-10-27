"""Explicit model context and executor bindings for durable workflow steps."""
import json
import re

from solders.pubkey import Pubkey

from .jobs import INFERENCE_PREFIX, NAME, inference_source

MAX_CONTEXT_BYTES = 16000


def step_extensions(step, dependencies):
    extras = {}
    if "worker_target" in step:
        target = step["worker_target"]
        if (not isinstance(target, dict) or set(target) != {"node_id", "worker_pubkey"}
                or not isinstance(target["node_id"], str) or not re.fullmatch(r"[!-~]{1,64}", target["node_id"])
                or not isinstance(target["worker_pubkey"], str)
                or str(Pubkey.from_string(target["worker_pubkey"])) != target["worker_pubkey"]):
            raise ValueError("Invalid workflow worker target")
        extras["worker_target"] = dict(target)
    bindings = step.get("message_inputs", [])
    if not isinstance(bindings, list) or len(bindings) > 8:
        raise ValueError("Use at most eight explicit model context files")
    if step["source"].startswith(INFERENCE_PREFIX):
        parameters = step.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("Workflow model parameters must be an object")
        request = parameters.get("inference", {})
        offer = parameters.get("offer", {})
        if not isinstance(request, dict) or not isinstance(offer, dict):
            raise ValueError("Workflow model request and offer must be objects")
        messages = request.get("messages", [])
        if (set(request) != {"provider_id", "messages", "max_tokens"}
                or not isinstance(request.get("provider_id"), str) or request['provider_id'] != offer.get('id')
                or type(request.get('max_tokens')) is not int or type(offer.get('max_output_tokens')) is not int
                or not 1 <= request['max_tokens'] <= offer['max_output_tokens'] <= 4096
                or not isinstance(messages, list) or not 1 <= len(messages) <= 32
                or any(not isinstance(item, dict) or set(item) != {"role", "content"}
                       or item["role"] not in {"user", "assistant", "system"}
                       or not isinstance(item["content"], str) or not 1 <= len(item["content"]) <= 16000
                       for item in messages)):
            raise ValueError("Invalid workflow model messages")
    elif bindings:
        raise ValueError("Only inference steps accept message_inputs")
    seen = set()
    for binding in bindings:
        if (not isinstance(binding, dict) or set(binding) != {"from_step", "artifact", "message_index"}
                or not isinstance(binding["from_step"], str)
                or not isinstance(binding["artifact"], str) or not NAME.fullmatch(binding["artifact"])
                or type(binding["message_index"]) is not int
                or not 0 <= binding["message_index"] < len(messages)
                or messages[binding["message_index"]]["role"] != "user"):
            raise ValueError("Model context must name a result file and a user message")
        key = (binding["from_step"], binding["artifact"], binding["message_index"])
        if key in seen:
            raise ValueError("Duplicate model context file")
        seen.add(key)
        dependencies.add(binding["from_step"])
    if bindings:
        extras["message_inputs"] = json.loads(json.dumps(bindings))
    return extras


def resolve_messages(step, read_artifact):
    parameters = json.loads(json.dumps(step["parameters"]))
    for binding in step.get("message_inputs", []):
        data = read_artifact(binding)
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_CONTEXT_BYTES:
            raise ValueError("Explicit model context must contain 1–16,000 UTF-8 bytes per file")
        text = data.decode("utf-8", errors="strict")
        message = parameters["inference"]["messages"][binding["message_index"]]
        message["content"] += context_suffix(binding, text)
        if len(message["content"]) > 16000:
            raise ValueError("Resolved model message exceeds 16,000 characters")
    return parameters


def context_suffix(binding, text):
    return "\n\n[Aperture input " + binding["from_step"] + "/" + binding["artifact"] + "]\n" + text


def resolved_source(step, parameters):
    return inference_source(parameters) if step["source"].startswith(INFERENCE_PREFIX) else step["source"]
