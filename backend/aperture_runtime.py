"""Data API exposed inside isolated Aperture jobs."""
import base64
import csv
import io
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = json.loads((_ROOT / "job.json").read_text(encoding="utf-8"))
_NAMES = {item["name"] for item in _SPEC.get("inputs", [])}
_SAFE = re.compile(r"^(?!(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$))[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,78}[A-Za-z0-9_-])?$")
_MAX_BYTES = 8 * 1024 * 1024
_TOTAL_BYTES = 16 * 1024 * 1024
_emitted = {}


def parameters():
    """Return a copy of the parameters approved in this job's signed manifest."""
    return json.loads(json.dumps(_SPEC.get("parameters", {})))


def read_bytes(name):
    if name not in _NAMES:
        raise ValueError("Input is not part of this job's authorized manifest.")
    return (_ROOT / "inputs" / name).read_bytes()


def read_text(name):
    return read_bytes(name).decode("utf-8-sig")


def read_json(name):
    return json.loads(read_text(name))


def read_csv(name):
    """Yield dictionaries without loading the whole CSV into Python memory."""
    if name not in _NAMES:
        raise ValueError("Input is not part of this job's authorized manifest.")
    with (_ROOT / "inputs" / name).open(encoding="utf-8-sig", newline="") as source:
        yield from csv.DictReader(source)


def write_bytes(name, data):
    """Emit a bounded named result; the coordinator uploads and attests its hash."""
    if not isinstance(name, str) or not _SAFE.fullmatch(name) or name.casefold() in _emitted:
        raise ValueError("Output names must be unique safe filenames.")
    if not isinstance(data, bytes) or not 0 < len(data) <= _MAX_BYTES:
        raise ValueError("Each result must contain 1 byte to 8 MiB.")
    if len(_emitted) >= 16 or sum(_emitted.values()) + len(data) > _TOTAL_BYTES:
        raise ValueError("Job results exceed the 16 MiB or 16-file limit.")
    _emitted[name.casefold()] = len(data)
    envelope = json.dumps({"name": name, "content": base64.b64encode(data).decode("ascii")},
                          separators=(",", ":"))
    sys.stdout.write("\nAPERTURE_ARTIFACT_V1:" + envelope + "\n")
    sys.stdout.flush()


def write_text(name, text):
    write_bytes(name, text.encode("utf-8"))


def write_json(name, value):
    write_text(name, json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def write_csv(name, rows, columns):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
        if buffer.tell() > _MAX_BYTES:
            raise ValueError("CSV result exceeds 8 MiB; split it into bounded batches.")
    write_text(name, buffer.getvalue())
