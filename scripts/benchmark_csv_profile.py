"""Benchmark the exact CSV sources on local Python, without gateway or payments.

Run this before choosing batch size on your worker. Results describe this host,
not the Docker resource envelope or the performance of a provider network.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LocalInputs:
    def __init__(self):
        self.blobs = {}

    def upload_input(self, data, *, name):
        digest = hashlib.sha256(data).hexdigest()
        identifier = "obj-" + digest[:32]
        self.blobs[identifier] = data
        return {"object_id": identifier, "name": name, "sha256": digest, "size_bytes": len(data)}


# Sampling the process's own peak working set avoids tracing allocations and
# changing the performance of the template. No instrumentation enters its source.
RUNNER = '''import runpy, sys, pathlib, json
root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root / "runtime"))
runpy.run_path(str(root / "payload.py"), run_name="__main__")
peak = None
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        peak = counters.PeakWorkingSetSize
else:
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
print("APERTURE_BENCHMARK_V1:" + json.dumps({"peak_process_memory_bytes": peak}))
'''


def run_local_plan(plan, blobs, directory):
    """Run each identical source/manifest in a fresh isolated-mode Python process."""
    outputs, steps = {}, []
    started = time.perf_counter()
    for step in plan:
        target = Path(directory) / step["id"]
        (target / "inputs").mkdir(parents=True)
        (target / "runtime").mkdir()
        inputs = []
        for item in step["inputs"]:
            if "from_step" in item:
                name, data = item["artifact"], outputs[item["from_step"]][item["artifact"]]
            else:
                name, data = item["name"], blobs[item["object_id"]]
                if len(data) != item["size_bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise ValueError("Baseline input differs from the uploaded batch.")
            (target / "inputs" / name).write_bytes(data)
            inputs.append({"name": name})
        (target / "job.json").write_text(json.dumps({"inputs": inputs, "parameters": step["parameters"]}), encoding="utf-8")
        (target / "payload.py").write_text(step["source"], encoding="utf-8", newline="")
        (target / "runtime" / "aperture.py").write_bytes((ROOT / "backend" / "aperture_runtime.py").read_bytes())
        (target / "runner.py").write_text(RUNNER, encoding="utf-8", newline="")
        tick = time.perf_counter()
        process = subprocess.run([sys.executable, "-I", "-u", str(target / "runner.py")],
            cwd=target, capture_output=True, timeout=step["max_runtime_seconds"],
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
        duration = time.perf_counter() - tick
        if process.returncode:
            raise RuntimeError("Direct Python failed: " + process.stderr.decode("utf-8", errors="replace")[-2000:])
        files, peak = {}, None
        for line in process.stdout.splitlines():
            if line.startswith(b"APERTURE_ARTIFACT_V1:"):
                artifact = json.loads(line[len(b"APERTURE_ARTIFACT_V1:"):])
                files[artifact["name"]] = base64.b64decode(artifact["content"], validate=True)
            elif line.startswith(b"APERTURE_BENCHMARK_V1:"):
                peak = json.loads(line[len(b"APERTURE_BENCHMARK_V1:"):])["peak_process_memory_bytes"]
        if step["parameters"]["output_name"] not in files:
            raise ValueError("Direct Python did not produce the expected result.")
        outputs[step["id"]] = files
        steps.append({"id": step["id"], "seconds": round(duration, 6), "peak_process_memory_bytes": peak,
                      "source_sha256": hashlib.sha256(step["source"].encode()).hexdigest()})
    return {"seconds": round(time.perf_counter() - started, 6), "steps": steps,
            "python": platform.python_version(), "platform": platform.platform(),
            "execution": "Direct local Python; no Docker resource limits, gateway, journal or payment"}, outputs[plan[-1]["id"]]


def main():
    import csv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=50000)
    parser.add_argument("--groups", type=int, default=4)
    parser.add_argument("--batch-rows", type=int, default=5000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rows <= 500000 or not 1 <= args.groups <= 10000 or not 1 <= args.batch_rows <= 100000:
        parser.error("Use 1–500000 rows, 1–10000 groups and 1–100000 rows per batch.")
    spec = importlib.util.spec_from_file_location("batch_pipeline", ROOT / "examples" / "batch_data_workflow.py")
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)
    with tempfile.TemporaryDirectory(prefix="aperture-cpu-benchmark-") as temporary:
        directory = Path(temporary)
        dataset = directory / "records.csv"
        with dataset.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(["category", "amount"])
            for row in range(args.rows):
                writer.writerow(["group-" + str(row % args.groups), "0.10"])
        collector = LocalInputs()
        inputs, _ = pipeline.upload_csv_batches(collector, dataset, batch_rows=args.batch_rows)
        measurement, files = run_local_plan(pipeline.build_plan(inputs), collector.blobs, directory / "jobs")
        report = json.loads(files["report.json"])
        from decimal import Decimal
        if report["valid_rows"] != args.rows or report["invalid_rows"] != 0 or sum(Decimal(item["total_decimal"]) for item in report["groups"].values()) != Decimal(args.rows) / 10:
            raise ValueError("Benchmark report differs from the generated dataset.")
        measurement.update(rows=args.rows, groups=args.groups, batch_rows=args.batch_rows,
            input_bytes=sum(item["size_bytes"] for item in inputs), total_decimal=str(Decimal(args.rows) / 10),
            max_observed_peak_process_memory_bytes=max(item["peak_process_memory_bytes"] or 0 for item in measurement["steps"]))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(measurement, indent=2), encoding="utf-8")
        print(json.dumps(measurement, indent=2))


if __name__ == "__main__":
    main()
