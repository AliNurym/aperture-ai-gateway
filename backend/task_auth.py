"""Pure helpers for binding wallet signatures to a single workload."""

import hashlib


def execution_message(wallet: str, code: str, nonce: str = "", expires_at: int = 0) -> str:
    """Canonical, audience-bound authorization for one short-lived workload."""
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    return (
        "Aperture execution authorization v1\n"
        "audience:aperture-gateway\n"
        "action:execute\n"
        f"wallet:{wallet}\ncode_sha256:{code_hash}\nnonce:{nonce}\nexpires_at:{expires_at}"
    )
