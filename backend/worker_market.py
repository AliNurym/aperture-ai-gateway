"""Real worker capacity, pinned dispatch and authenticated operator controls."""
import time

from fastapi import Depends, HTTPException
from pydantic import BaseModel, StrictBool

from agent_identity import valid_public_key
from state_store import ACTIVE_STATES

HEARTBEAT_TTL = 45


def require_worker_target(gateway, target, manifest):
    """A chosen executor is an authorization constraint, never a routing hint."""
    node = gateway.store.get("workers", target["node_id"])
    if not node or node.get("worker_pubkey") != target["worker_pubkey"]:
        raise HTTPException(409, "The selected worker identity is no longer registered. Select capacity again.")
    if time.time() - node.get("last_seen", 0) >= HEARTBEAT_TTL:
        raise HTTPException(409, "The selected worker is offline. Select another worker or wait for it to reconnect.")
    if not node.get("accepting_tasks", True):
        raise HTTPException(409, "The selected worker is draining and does not accept new tasks.")
    runtime = (manifest or {}).get("runtime", "python")
    if runtime not in node.get("runtimes", ["python"]):
        raise HTTPException(409, "The selected worker cannot serve this runtime.")
    if runtime == "inference.chat" and manifest["parameters"]["offer"] not in node.get("inference_offers", []):
        raise HTTPException(409, "The selected worker does not serve the quoted model offer.")
    if not valid_public_key(target["worker_pubkey"]):
        raise HTTPException(422, "The selected worker has an invalid signing identity.")
    return node


def worker_snapshot(gateway, node, active_jobs=None):
    # Only explicitly public metadata leaves the gateway. Credentials, source,
    # owner identities and task access capabilities never enter the directory.
    fields = ("node_id", "worker_pubkey", "gpu_name", "execution_mode", "source_policy",
              "approved_source_count", "runtimes", "last_seen")
    result = {key: node[key] for key in fields if key in node}
    active_jobs = gateway.store.list_active_jobs() if active_jobs is None else active_jobs
    assigned = [job for job in active_jobs if job.get("worker_id") == node["node_id"]]
    result.update(online=time.time() - node.get("last_seen", 0) < HEARTBEAT_TTL,
                  accepting_tasks=node.get("accepting_tasks", True), active_tasks=len(assigned),
                  totals=gateway.store.worker_totals(node["node_id"]))
    result["status"] = ("offline" if not result["online"] else
                        "draining" if not result["accepting_tasks"] else
                        "busy" if assigned else "available")
    return result


class WorkerMode(BaseModel):
    model_config = {"extra": "forbid"}
    accepting_tasks: StrictBool


def mount_worker_market(gateway):
    router = gateway.router

    @router.get("/workers")
    async def directory():
        jobs = gateway.store.list_active_jobs()
        return {"workers": [worker_snapshot(gateway, node, jobs)
                            for node in gateway.store.list("workers") if node.get("node_id")],
                "history_scope": "durable_totals_from_retained_baseline", "heartbeat_ttl_seconds": HEARTBEAT_TTL}

    def operator_view(worker_id):
        node = gateway.store.get("workers", worker_id)
        if not node or not node.get("node_id"):
            raise HTTPException(409, "Start and register this worker before opening its operator workspace.")
        result = worker_snapshot(gateway, node)
        jobs = gateway.store.worker_jobs(worker_id)
        result["recent_tasks"] = [{
            "task_id": job["task_id"], "state": job["state"],
            "runtime": job.get("workload", {}).get("runtime", "python"),
            "created_at": job.get("created_at"), "completed_at": job.get("completed_at"),
            "execution_seconds": (job.get("receipt") or {}).get("execution_time"),
            "settlement_type": (job.get("receipt") or {}).get("settlement_type"),
            "paid_lamports": (job.get("receipt") or {}).get("worker_paid_lamports"),
        } for job in jobs]
        result["inference_offers"] = node.get("inference_offers", [])
        return result

    @router.get("/workers/me")
    async def operator(worker_id: str = Depends(gateway.require_worker)):
        return operator_view(worker_id)

    @router.post("/workers/me/mode")
    async def mode(payload: WorkerMode, worker_id: str = Depends(gateway.require_worker)):
        async with gateway.lock:
            node = gateway.store.get("workers", worker_id)
            if not node or not node.get("node_id"):
                raise HTTPException(409, "Register this worker before changing its admission mode.")
            node["accepting_tasks"] = payload.accepting_tasks
            gateway.store.put("workers", worker_id, node)
            return operator_view(worker_id)
