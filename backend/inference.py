"""Operator-configured inference offers and immutable, owner-authorized requests.

The tariff is elapsed-time billing through Aperture's existing payment channel,
not an estimate of a model vendor's token bill. No provider is enabled by default.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


CAPABILITY = "inference.chat"
PREFIX = "# Aperture inference request v1\n# sha256:"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=16000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    messages: list[ChatMessage] = Field(min_length=1, max_length=32)
    max_tokens: StrictInt = Field(default=256, ge=1, le=4096)


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=80)
    protocol: Literal["openai_chat_completions", "gemini_generate_content"] = "openai_chat_completions"
    model: str = Field(min_length=1, max_length=128)
    base_url: str = Field(max_length=2048)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    # Accepted temporarily for older provider config files. It is intentionally
    # excluded from the public offer and never determines a worker's task price.
    rate_lamports_sec: StrictInt | None = Field(default=None, ge=1, le=25000)
    max_output_tokens: StrictInt = Field(default=512, ge=1, le=4096)
    development_only: bool = False

    @property
    def is_development_only(self):
        return (self.development_only or self.id in {"local-model", "aperture-local-fixture"}
                or "smollm" in self.model.lower())

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value, info):
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if (not host or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.scheme not in ({"http", "https"} if loopback else {"https"})
                or any(ord(char) < 33 for char in value)):
            raise ValueError("Provider URL requires HTTPS, or loopback HTTP, without credentials/query/fragment.")
        if info.data.get("protocol") == "gemini_generate_content":
            if parsed.path.rstrip("/") != "/v1beta":
                raise ValueError("Gemini provider URL must use the Gemini API v1beta base path.")
            if not loopback and host != "generativelanguage.googleapis.com":
                raise ValueError("Gemini API keys may only be sent to Google's Generative Language API.")
        if host == "api.deepseek.com" and (info.data.get("id") != "aperture-deepseek"
                or info.data.get("protocol") != "openai_chat_completions"
                or parsed.path.rstrip("/") not in ("", "/v1")):
            raise ValueError("DeepSeek's API endpoint is reserved for the fixed Aperture Sentinel provider.")
        if info.data.get("id") == "aperture-deepseek" and host != "api.deepseek.com":
            raise ValueError("Aperture DeepSeek credentials may only be sent to api.deepseek.com.")
        return value.rstrip("/")

    @field_validator("model")
    @classmethod
    def valid_model(cls, value, info):
        if info.data.get("protocol") == "gemini_generate_content" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
            raise ValueError("Gemini model IDs may contain only letters, digits, dot, underscore and hyphen.")
        if info.data.get("id") == "aperture-deepseek" and value not in {"deepseek-flash", "deepseek-v4-pro"}:
            raise ValueError("Use a currently supported DeepSeek API model ID.")
        return value

    @field_validator("api_key_env")
    @classmethod
    def provider_requires_key(cls, value, info):
        if (info.data.get("protocol") == "gemini_generate_content" or info.data.get("id") == "aperture-deepseek") and not value:
            raise ValueError("This provider requires an API key environment variable.")
        if info.data.get("id") == "aperture-deepseek" and value != "DEEPSEEK_API_KEY":
            raise ValueError("Aperture DeepSeek must use the DEEPSEEK_API_KEY environment variable.")
        parsed = urlsplit(info.data.get("base_url", ""))
        if value == "DEEPSEEK_API_KEY" and (info.data.get("id") != "aperture-deepseek"
                or info.data.get("protocol") != "openai_chat_completions" or parsed.hostname != "api.deepseek.com"):
            raise ValueError("DEEPSEEK_API_KEY may only be used by the pinned DeepSeek provider.")
        if value == "GEMINI_API_KEY" and info.data.get("protocol") != "gemini_generate_content":
            raise ValueError("GEMINI_API_KEY may only be used by the native Gemini provider.")
        return value

    def offer(self):
        # Endpoint identity is signed without publishing internal URLs or credentials.
        offer = {"id": self.id, "name": self.name, "model": self.model, "protocol": self.protocol,
                "endpoint_sha256": hashlib.sha256(self.base_url.encode()).hexdigest(),
                "max_output_tokens": self.max_output_tokens,
                "runtime": CAPABILITY, "pricing": "worker_published_time_rate_v1",
                "billing": "Worker execution time; upstream model API charges are paid separately",
                "settlement_destination": "authenticated_task_worker_on_confirmed_devnet",
                "worker_settlement_share_pct": 100,
                "upstream_provider_payouts": False}
        if self.is_development_only:
            offer["development_only"] = True
        return offer


def is_development_offer(offer):
    if not isinstance(offer, dict):
        return False
    return (offer.get("development_only") is True
            or offer.get("id") in {"local-model", "aperture-local-fixture"}
            or "smollm" in str(offer.get("model", "")).lower())


def offers_match(expected, advertised):
    """Match current offers while tolerating the retired provider-rate field."""
    if not isinstance(expected, dict) or not isinstance(advertised, dict):
        return False
    clean_expected = {key: value for key, value in expected.items() if key != "rate_lamports_sec"}
    clean_advertised = {key: value for key, value in advertised.items() if key != "rate_lamports_sec"}
    return clean_expected == clean_advertised


def load_providers():
    config = os.getenv("APERTURE_INFERENCE_CONFIG", "").strip()
    if not config:
        return {}
    path = Path(config)
    if path.stat().st_size > 128000:
        raise ValueError("Inference configuration exceeds 128,000 bytes.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) > 32:
        raise ValueError("Inference configuration must contain at most 32 providers.")
    providers = [Provider.model_validate(item) for item in data]
    if len({item.id for item in providers}) != len(providers):
        raise ValueError("Inference provider IDs must be unique.")
    return {item.id: item for item in providers}


def request_parameters(request, provider):
    if request.max_tokens > provider.max_output_tokens:
        raise ValueError("Requested output tokens exceed the provider limit.")
    if provider.protocol == "gemini_generate_content" and not any(message.role != "system" for message in request.messages):
        raise ValueError("Gemini requests require at least one user or assistant message.")
    parameters = {"inference": request.model_dump(), "offer": provider.offer()}
    if len(canonical(parameters).encode("utf-8")) > 32000:
        raise ValueError("Inference request exceeds 32,000 UTF-8 bytes.")
    return parameters


def request_code(parameters):
    digest = hashlib.sha256(canonical(parameters).encode("utf-8")).hexdigest()
    return PREFIX + digest + "\npass\n"


def validate_request(code, parameters, providers=None):
    if set(parameters) != {"inference", "offer"} or code != request_code(parameters):
        raise ValueError("Inference source and parameters must match their exact authorization.")
    request = ChatRequest.model_validate(parameters["inference"])
    offer = parameters["offer"]
    if (not isinstance(offer, dict) or offer.get("id") != request.provider_id
            or offer.get("runtime") != CAPABILITY
            or type(offer.get("max_output_tokens")) is not int
            or not 1 <= request.max_tokens <= offer["max_output_tokens"] <= 4096):
        raise ValueError("Invalid inference offer.")
    if request.provider_id == "aperture-deepseek":
        from sentinel_review import PROMPT_PREFIX
        messages = request.messages
        if len(messages) != 1 or messages[0].role != "user" or not messages[0].content.startswith(PROMPT_PREFIX):
            raise ValueError("DeepSeek is available only for the fixed AI Sentinel source review.")
        try:
            source = json.loads(messages[0].content[len(PROMPT_PREFIX):])
        except (ValueError, TypeError):
            source = None
        try:
            source_size = len(source.encode("utf-8")) if isinstance(source, str) else 0
        except UnicodeEncodeError:
            source_size = 32001
        if (not isinstance(source, str) or not source.strip() or source_size > 32000
                or messages[0].content != PROMPT_PREFIX + json.dumps(source, ensure_ascii=False)):
            raise ValueError("DeepSeek accepts only an exact AI Sentinel review prompt bound to one source string.")
    if providers is not None:
        provider = providers.get(request.provider_id)
        if provider is None:
            raise ValueError("Provider offer changed or is no longer configured. Request a fresh quote.")
        expected = request_parameters(request, provider)
        supplied = dict(parameters)
        supplied_offer = supplied.get("offer", {})
        legacy_rate = supplied_offer.get("rate_lamports_sec") if isinstance(supplied_offer, dict) else None
        if "rate_lamports_sec" in supplied_offer and (
                provider.rate_lamports_sec is None or type(legacy_rate) is not int
                or legacy_rate != provider.rate_lamports_sec):
            raise ValueError("Legacy model rates must match the configured provider record and cannot set task price.")
        supplied["offer"] = {key: value for key, value in supplied_offer.items() if key != "rate_lamports_sec"}
        if expected != supplied:
            raise ValueError("Provider offer changed or is no longer configured. Request a fresh quote.")
    return request
