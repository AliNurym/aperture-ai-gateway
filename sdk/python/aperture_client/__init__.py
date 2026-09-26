"""Aperture's small synchronous client. Secrets remain on the caller's machine."""
from .client import ApertureClient, IntegrityError, Task, load_keypair, verify_quote, verify_receipt

__all__ = ["ApertureClient", "IntegrityError", "Task", "load_keypair", "verify_quote", "verify_receipt"]
