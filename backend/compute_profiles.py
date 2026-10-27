"""Published CPU capability metadata; worker owners supply task prices."""
import hashlib
import json
from pathlib import Path

PROFILE_ID = "cpu-csv-v2"
SOURCES = json.loads((Path(__file__).parent / "workloads" / "csv_sources.json").read_text(encoding="utf-8"))
SOURCE_HASHES = {hashlib.sha256(SOURCES[name].encode()).hexdigest(): name for name in ("batch", "merge")}


def csv_profile():
    return {
        "id": PROFILE_ID, "runtime": "python", "templates": {name: digest for digest, name in SOURCE_HASHES.items()},
        "workload": "CSV grouped decimal totals, counts, min/max, averages and invalid-row accounting",
        "libraries": ["Python standard library"], "streaming_input": True,
        "docker_limits": {"cpus": 1, "memory_bytes": 512 * 1024 * 1024, "network": "none"},
        "max_input_bytes_per_step": 64 * 1024 * 1024, "max_runtime_seconds": 180,
        "max_result_bytes": 8 * 1024 * 1024, "max_total_result_bytes": 16 * 1024 * 1024,
        "max_groups": 10000, "amount_max_absolute": "1000000000000000", "amount_max_decimal_places": 6,
        "starting_batch_rows": 5000, "sizing": "Starting point only; benchmark actual columns and group cardinality on your worker.",
        "execution": "Serial steps on one agent payment channel; no GPU or distributed parallelism",
        "pricing": {"kind": "provider_published_worker_rate_v1", "rate_lamports_sec": None,
                    "basis": "The selected worker owner publishes the rate; source analysis and gateway settings do not calculate it",
                    "time_basis": "Worker-reported elapsed execution time; excludes gateway and client waiting",
                    "off_chain": "No payment; an equivalent tariff estimate is reported separately"},
    }


def source_profile(source):
    return PROFILE_ID if hashlib.sha256(source.encode()).hexdigest() in SOURCE_HASHES else None
