"""Collect the exact reviewed Python sources shipped by Aperture demos."""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def approved_sources(project_root: Path, node_executable: str) -> dict[str, str]:
    """Return current Studio/workflow samples and retained v1 sources."""
    root = Path(project_root).resolve()
    frontend_source = (
        "import {WORKLOADS} from './src/utils/workloads.js'; "
        "import {MERGE_SOURCE} from './src/utils/workflowSources.js'; "
        "console.log(JSON.stringify([...WORKLOADS.map(item=>({id:item.id,code:item.code})),"
        "{id:'workflow-report',code:MERGE_SOURCE}]));"
    )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    exported = subprocess.check_output(
        [node_executable, "--input-type=module", "-e", frontend_source],
        cwd=root / "frontend", text=True, encoding="utf-8", creationflags=creationflags,
    )
    items = json.loads(exported)
    if not isinstance(items, list):
        raise ValueError("Frontend workload catalog is invalid.")
    sources = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Frontend workload entry is invalid.")
        sources[item["id"]] = item.get("code")

    sdk_path = str(root / "sdk" / "python")
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)
    pipeline_path = root / "examples" / "batch_data_workflow.py"
    spec = importlib.util.spec_from_file_location("aperture_preview_batch_pipeline", pipeline_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the reviewed batch workflow sources.")
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)
    sources["batch"] = pipeline.BATCH_SOURCE
    sources["merge"] = pipeline.MERGE_SOURCE

    legacy_path = root / "backend" / "workloads" / "csv_legacy_sources.json"
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    if not isinstance(legacy, dict):
        raise ValueError("Legacy workload catalog is invalid.")
    sources.update({"legacy-" + name: code for name, code in legacy.items()})
    model_workflow = json.loads((root / "backend" / "workloads" / "model_workflow.json").read_text(encoding="utf-8"))
    sources['model-text-analysis'] = model_workflow['analysis_source']

    for name, code in sources.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", name)
                or not isinstance(code, str) or not code.strip()
                or len(code.encode("utf-8")) > 65_536):
            raise ValueError("A reviewed workload source has an invalid ID or size.")
    return sources
