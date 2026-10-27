"""Port selection for the isolated local preview launcher."""

import socket


def _port_available(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def resolve_preview_port(requested, default, label, fallback, *, excluded=()):
    """Use a requested/default loopback port, falling back only for defaults."""
    preferred = default if requested is None else requested
    if type(preferred) is not int or not 1 <= preferred <= 65535:
        raise ValueError(f"The {label} port must be an integer from 1 to 65535.")
    if preferred not in excluded and _port_available(preferred):
        return preferred, False
    if requested is not None:
        raise RuntimeError(
            f"Requested --{label} port {preferred} is unavailable. Choose a free port or omit --{label}."
        )
    for _ in range(16):
        alternative = fallback()
        if (type(alternative) is int and 1 <= alternative <= 65535
                and alternative not in excluded and _port_available(alternative)):
            return alternative, True
    raise RuntimeError(f"Could not find a free loopback port for {label}.")
