"""Shared validation for secrets used by the gateway and worker."""

import json


_WORKER_TOKEN_PLACEHOLDERS = {
    "replace-with-a-long-random-secret",
    "change-me",
    "example-token",
}


def worker_id_is_valid(worker_id: str | None) -> bool:
    return (
        isinstance(worker_id, str)
        and 1 <= len(worker_id) <= 64
        and worker_id == worker_id.strip()
        and all(33 <= ord(character) <= 126 for character in worker_id)
    )


def worker_token_is_configured(token: str | None, minimum_length: int = 16) -> bool:
    value = (token or "").strip()
    return (
        len(value) >= minimum_length
        and all(33 <= ord(character) <= 126 for character in value)
        and value.lower() not in _WORKER_TOKEN_PLACEHOLDERS
    )


def load_worker_credentials(raw: str | None) -> dict[str, str]:
    """Parse an optional JSON allowlist of unique per-worker bearer tokens."""
    value = (raw or "").strip()
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("APERTURE_WORKER_CREDENTIALS must be a JSON object.") from exc
    if not isinstance(parsed, dict) or not parsed or len(parsed) > 1_000:
        raise ValueError("APERTURE_WORKER_CREDENTIALS must contain 1 to 1000 worker entries.")

    credentials = {}
    seen_tokens = set()
    for worker_id, token in parsed.items():
        if not worker_id_is_valid(worker_id):
            raise ValueError("APERTURE_WORKER_CREDENTIALS contains an invalid worker ID.")
        if not isinstance(token, str) or not worker_token_is_configured(token, minimum_length=32):
            raise ValueError("Each worker credential must be a unique, non-placeholder secret of at least 32 characters.")
        token = token.strip()
        if token in seen_tokens:
            raise ValueError("Each worker must have a distinct credential.")
        seen_tokens.add(token)
        credentials[worker_id] = token
    return credentials


def worker_auth_is_configured(credentials: dict[str, str], fallback_token: str | None = None) -> bool:
    """Report whether mapped credentials or a development fallback is usable."""
    return bool(credentials) or worker_token_is_configured(fallback_token)
