"""Canonical owner-issued Know Your Agent passports (not legal KYC)."""
import hashlib
import json
import base58
from nacl.signing import VerifyKey

CAPABILITIES = ["python.execute"]

def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def valid_public_key(value):
    try:
        return len(base58.b58decode(value)) == 32
    except (ValueError, TypeError):
        return False

def verify_ed25519(public_key, signature, message):
    try:
        VerifyKey(base58.b58decode(public_key)).verify(message.encode("utf-8"), bytes(signature))
        return True
    except Exception:
        return False

def passport_message(action, passport, nonce, challenge_expires_at):
    return "Aperture agent delegation v1\naudience:aperture-gateway\n" + canonical_json({
        "action": action, "passport": passport, "nonce": nonce,
        "challenge_expires_at": challenge_expires_at,
    })

def quote_message(quote):
    bound = {key: quote[key] for key in (
        "quote_id", "wallet", "agent_pubkey", "code_sha256", "rate_lamports",
        "max_cost_lamports", "max_runtime_seconds", "expires_at", "passport_version",
        "program_id", "network", "gateway_pubkey", "treasury",
    )}
    version = 2
    if "workload" in quote:
        version = 3
        bound["workload_sha256"] = quote["workload_sha256"]
    if "workflow" in quote:
        version = 4
        bound["workflow"] = quote["workflow"]
    return f"Aperture execution authorization v{version}\naudience:aperture-gateway\naction:execute\n" + canonical_json(bound)

def receipt_message(receipt):
    return "Aperture compute receipt v1\n" + canonical_json(receipt)
