"""One streamed request, no retries or automatic failover after dispatch."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import requests
from inference import canonical, load_providers, validate_request
from sentinel_review import source_bound_sentinel_source, valid_sentinel_output


def _sse_data(response):
    total, buffer = 0, bytearray()
    for chunk in response.iter_content(chunk_size=1024):
        total += len(chunk)
        if total > 2_000_000:
            raise ValueError("Provider stream exceeds the response limit")
        buffer.extend(chunk)
        if len(buffer) > 128000:
            raise ValueError("Provider event exceeds the response limit")
        while b"\n" in buffer:
            line, _, rest = buffer.partition(b"\n")
            buffer = bytearray(rest)
            line = line.rstrip(b"\r")
            if line.startswith(b"data:"):
                yield line[5:].strip()
    if buffer:
        line = bytes(buffer).rstrip(b"\r")
        if line.startswith(b"data:"):
            yield line[5:].strip()


def _gemini_body(request):
    system = [item.content for item in request.messages if item.role == "system"]
    contents = [{"role": "model" if item.role == "assistant" else "user",
                 "parts": [{"text": item.content}]}
                for item in request.messages if item.role != "system"]
    if not contents:
        raise ValueError("Gemini requests require at least one user or assistant message")
    body = {"contents": contents, "generationConfig": {"maxOutputTokens": request.max_tokens}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    return body


def _openai_body(request, provider):
    body = {"model": provider.model, "messages": [item.model_dump() for item in request.messages],
            "max_tokens": request.max_tokens, "stream": True}
    if provider.id == "aperture-deepseek":
        body["thinking"] = {"type": "disabled"}
        body["response_format"] = {"type": "json_object"}
    return body


def run(directory):
    spec = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    code = (directory / "payload.py").read_text(encoding="utf-8")
    providers = load_providers()
    request = validate_request(code, spec["parameters"], providers)
    provider = providers[request.provider_id]
    sentinel_source = source_bound_sentinel_source(request)
    if request.provider_id == "aperture-deepseek" and sentinel_source is None:
        raise ValueError("DeepSeek requires the fixed source-bound Sentinel request")
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if provider.protocol == "gemini_generate_content":
        headers["x-goog-api-key"] = os.environ[provider.api_key_env]
        endpoint = f"{provider.base_url}/models/{provider.model}:streamGenerateContent?alt=sse"
        body = _gemini_body(request)
    else:
        if provider.api_key_env:
            headers["Authorization"] = "Bearer " + os.environ[provider.api_key_env]
        endpoint = provider.base_url + "/chat/completions"
        body = _openai_body(request, provider)
    content_hash, done, seen_gemini_response = hashlib.sha256(), False, False
    text_output = io.StringIO()
    # Ignore ambient proxy credentials and never forward auth across redirects.
    with requests.Session() as session:
        session.trust_env = False
        with session.post(endpoint, headers=headers, json=body,
                          stream=True, timeout=(5, 180), allow_redirects=False) as response:
            if response.status_code != 200 or "text/event-stream" not in response.headers.get("Content-Type", ""):
                raise ValueError("Provider did not return a successful event stream")
            for data in _sse_data(response):
                if data == b"[DONE]" and provider.protocol == "openai_chat_completions":
                    done = True
                    break
                event = json.loads(data)
                if "error" in event:
                    raise ValueError("Provider reported an inference error")
                if provider.protocol == "gemini_generate_content":
                    seen_gemini_response = True
                    if event.get("promptFeedback", {}).get("blockReason"):
                        raise ValueError("Provider blocked the Gemini request")
                    candidates = event.get("candidates", [])
                    if not isinstance(candidates, list):
                        raise ValueError("Provider returned invalid Gemini candidates")
                    if candidates:
                        candidate = candidates[0]
                        content = candidate.get("content", {})
                        parts = content.get("parts", [])
                        if not isinstance(parts, list):
                            raise ValueError("Provider returned invalid Gemini content")
                        for part in parts:
                            text = part.get("text")
                            if text is not None:
                                if not isinstance(text, str):
                                    raise ValueError("Provider returned invalid text")
                                content_hash.update(text.encode("utf-8"))
                                text_output.write(text)
                                print(text, end="", flush=True)
                        finish_reason = candidate.get("finishReason")
                        if finish_reason in ("STOP", "MAX_TOKENS"):
                            done = True
                            break
                        if finish_reason not in (None, "FINISH_REASON_UNSPECIFIED"):
                            raise ValueError("Gemini did not complete the response")
                else:
                    if event.get("model") not in (None, provider.model):
                        raise ValueError("Provider returned a different model")
                    for choice in event.get("choices", []):
                        if choice.get("index", 0) != 0:
                            continue
                        text = choice.get("delta", {}).get("content")
                        if text is not None:
                            if not isinstance(text, str):
                                raise ValueError("Provider returned invalid text")
                            content_hash.update(text.encode("utf-8"))
                            text_output.write(text)
                            print(text, end="", flush=True)
    if provider.protocol == "gemini_generate_content" and not (done and seen_gemini_response):
        raise ValueError("Gemini stream ended before completion")
    if not done:
        raise ValueError("Provider stream ended before completion")
    response_text = text_output.getvalue()
    if sentinel_source is not None and not valid_sentinel_output(response_text, sentinel_source):
        raise ValueError("Provider returned an incomplete source-bound Sentinel report")
    # Only the trusted adapter writes this file. Provider text never becomes an
    # artifact control frame in stdout; the coordinator publishes its exact bytes.
    response_bytes = response_text.encode("utf-8")
    if response_bytes:
        (directory / "response.txt").write_bytes(response_bytes)
    print("\n\n[Aperture inference metadata]\n" + canonical({
        "provider_id": provider.id, "model": provider.model, "protocol": provider.protocol,
        "max_tokens": request.max_tokens, "text_sha256": content_hash.hexdigest(), "offer": provider.offer(),
        "verification": "Provider-reported text; not proof of model identity or correct inference"}))


if __name__ == "__main__":
    watchdog = None
    try:
        directory = Path(sys.argv[1])
        deadline = json.loads((directory / "execution.json").read_text(encoding="utf-8"))["deadline"]
        remaining = deadline - time.time()
        if not math.isfinite(remaining) or remaining > 180:
            raise ValueError("Inference lease has no valid execution window")
        if remaining <= 0:
            print("[INFERENCE_DEADLINE_EXPIRED]", flush=True)
            sys.exit(124)
        # Retain the time boundary even if the worker coordinator disappears.
        watchdog = threading.Timer(remaining, lambda: os._exit(124))
        watchdog.daemon = True
        watchdog.start()
        run(directory)
    except Exception as error:
        # Provider bodies, URLs, credentials and exception messages stay off receipts.
        print(f"\n[INFERENCE_FAILED: {type(error).__name__}]", flush=True)
        sys.exit(1)
    finally:
        if watchdog:
            watchdog.cancel()
