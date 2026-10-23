"""Resolve durable local state paths, including long Windows workspaces."""
import os
from pathlib import Path
from urllib.parse import quote


def durable_path(value):
    path = Path(value).resolve()
    if os.name == 'nt':
        raw = str(path)
        if not raw.startswith('\\\\?\\'):
            raw = '\\\\?\\UNC\\' + raw[2:] if raw.startswith('\\\\') else '\\\\?\\' + raw
            path = Path(raw)
    return path


def readonly_sqlite_uri(value):
    path = durable_path(value)
    if os.name == 'nt':
        # Keep the extended path inside the URI path, not its authority.
        # Encoding the backslashes and '?' preserves long-path support when
        # SQLite decodes the filename and still enforces mode=ro.
        return 'file:' + quote(str(path), safe='/:') + '?mode=ro'
    return path.as_uri() + '?mode=ro'
