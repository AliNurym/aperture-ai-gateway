"""Durable owner-approved CSV work delivered to a dedicated agent host."""
import json
import math
import re
import secrets
import time
from pathlib import Path

from fastapi import Header, HTTPException
from pydantic import Field

from agent_identity import canonical_json, sha256_text
from artifact_store import SAFE_NAME, validate_descriptor
from owner_workspace import OwnerControl, owner_authorization, view_payload

SOURCES = json.loads((Path(__file__).with_name("workloads") / "csv_sources.json").read_text(encoding="utf-8"))
TERMINAL = {"completed", "failed", "stopped", "archived"}
FLOW_ID = r"^flow-[0-9a-f]{64}$"


class SubmitWorkflow(OwnerControl):
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    plan: dict


class FlowControl(OwnerControl):
    workflow_id: str = Field(pattern=FLOW_ID)


class ClaimWorkflow(FlowControl):
    host_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class PublishWorkflow(FlowControl):
    lease_token: str = Field(min_length=32, max_length=128)
    progress: dict


def validate_plan(core, plan, owner, agent):
    """Inbox v1 accepts the reviewed report profile; generic jobs remain separate."""
    if (set(plan) != {"version", "max_cost_lamports", "steps"} or plan.get("version") != 1
            or type(plan.get("max_cost_lamports")) is not int or not 0 < plan["max_cost_lamports"] <= 100_000_000_000
            or not isinstance(plan.get("steps"), list) or not 1 <= len(plan["steps"]) <= 256
            or len(canonical_json(plan).encode()) > 2_000_000):
        raise ValueError("Choose a bounded version-1 CSV report plan, up to 2 MB.")
    by_id, dependencies = {}, {}
    cost = 0
    from gateway import QuoteRequest
    for step in plan["steps"]:
        if (not isinstance(step, dict) or set(step) - {"id", "source", "inputs", "parameters", "depends_on", "max_cost_lamports", "max_runtime_seconds"}
                or not isinstance(step.get("id"), str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", step["id"])
                or step["id"] in by_id or step.get("source") not in (SOURCES["batch"], SOURCES["merge"])
                or type(step.get("max_cost_lamports")) is not int or not 0 < step["max_cost_lamports"] <= 1_000_000_000
                or type(step.get("max_runtime_seconds")) is not int or not 1 <= step["max_runtime_seconds"] <= 180
                or not isinstance(step.get("inputs"), list) or not 1 <= len(step["inputs"]) <= 16
                or not isinstance(step.get("parameters"), dict)):
            raise ValueError("Inbox steps must use the reviewed CSV summary/merge sources and explicit bounds.")
        parameters = step["parameters"]
        if not isinstance(parameters.get("output_name"), str) or not SAFE_NAME.fullmatch(parameters["output_name"]):
            raise ValueError("Every step needs a portable output filename.")
        if not isinstance(step.get("depends_on", []), list) or any(not isinstance(item, str) for item in step.get("depends_on", [])):
            raise ValueError("Step dependencies must be a list of step identifiers.")
        absolute, deps, names = [], set(step.get("depends_on", [])), []
        for item in step["inputs"]:
            if isinstance(item, dict) and set(item) == {"from_step", "artifact"}:
                if not isinstance(item["from_step"], str) or not isinstance(item["artifact"], str) or not SAFE_NAME.fullmatch(item["artifact"]):
                    raise ValueError("Invalid report dependency.")
                deps.add(item["from_step"]); names.append(item["artifact"])
            else:
                item = validate_descriptor(item)
                core.objects.resolve(item, owner=owner, agent=agent)
                absolute.append(item); names.append(item["name"])
        if len(set(name.casefold() for name in names)) != len(names):
            raise ValueError("Step input filenames must be unique.")
        if step["source"] == SOURCES["batch"]:
            if len(absolute) != 1 or len(step["inputs"]) != 1 or parameters.get("input_name") != names[0] or parameters.get("csv_output") is not False:
                raise ValueError("Each report batch needs exactly one CSV input and a JSON summary.")
        elif absolute or parameters.get("input_names") != names or type(parameters.get("final")) is not bool:
            raise ValueError("Merge inputs must match the summaries named in its parameters.")
        core.job_manifest(QuoteRequest(wallet=owner, agent_pubkey=agent, code=step["source"], job_version=1,
            inputs=absolute, parameters=parameters, max_cost_lamports=step["max_cost_lamports"], max_runtime_seconds=step["max_runtime_seconds"]), resolve=False)
        by_id[step["id"]] = step; dependencies[step["id"]] = deps; cost += step["max_cost_lamports"]
    if cost > plan["max_cost_lamports"]:
        raise ValueError("The sum of step caps exceeds the approved total budget.")
    for step in plan["steps"]:
        if not dependencies[step["id"]] <= set(by_id) or step["id"] in dependencies[step["id"]]:
            raise ValueError("Unknown or self-dependent step.")
        for item in step["inputs"]:
            if "from_step" in item and item["artifact"] != by_id[item["from_step"]]["parameters"]["output_name"]:
                raise ValueError("Dependency file differs from the producer's approved output.")
    pending, done = set(by_id), set()
    while pending:
        ready = {identifier for identifier in pending if dependencies[identifier] <= done}
        if not ready:
            raise ValueError("The workflow contains a dependency cycle.")
        pending -= ready; done |= ready
    if sum(step["source"] == SOURCES["merge"] and step["parameters"].get("final") is True for step in plan["steps"]) != 1:
        raise ValueError("The report profile requires exactly one final report.")
    final = next(step["id"] for step in plan["steps"] if step["source"] == SOURCES["merge"] and step["parameters"].get("final") is True)
    ancestors, pending = set(), {final}
    while pending:
        identifier = pending.pop()
        if identifier not in ancestors:
            ancestors.add(identifier)
            pending.update(dependencies[identifier])
    if ancestors != set(by_id):
        raise ValueError("Every approved step must contribute to the final report.")


def workflow_summary(core, value):
    status = value["status"]
    if value.get("stop_requested") and status not in TERMINAL and all(
        (core.store.get("jobs", task_id) or {}).get("state") == "completed" for task_id in value.get("tasks", {}).values()):
        status = "stopped"
    if status == "running" and value.get("heartbeat_at", 0) < time.time() - 30:
        status = "attention"
    return {key: value.get(key) for key in ("workflow_id", "owner", "agent_pubkey", "request_id", "plan_sha256", "created_at",
        "completed_steps", "charged_lamports", "estimated_charge_lamports", "stop_requested", "detail", "updated_at")} | {
        "status": status, "total_steps": len(value["plan"]["steps"]), "max_cost_lamports": value["plan"]["max_cost_lamports"],
        "tasks": value.get("tasks", {}), "resume_available": status == "attention" and not value.get("stop_requested")}


async def cancel_tracked(core, value):
    for task_id in value.get("tasks", {}).values():
        job = core.store.get("jobs", task_id)
        if job and job["state"] != "completed":
            job.update(state="settlement_pending", cancelled=True)
            job.setdefault("result", core.cancelled_result(job, "WORKFLOW_STOP_REQUESTED_BY_OWNER"))
            core.store.save_job(job)
            await core.settle(job)


def validate_bound_step(core, quote, source):
    binding = quote["workflow"]
    flow = core.store.assigned_workflow(binding["workflow_id"])
    if (not flow or (flow["owner"], flow["agent_pubkey"]) != (quote["wallet"], quote["agent_pubkey"])
            or flow.get("stop_requested") or flow["status"] in TERMINAL
            or not flow.get("host_id") or flow.get("lease_expires_at", 0) <= time.time()):
        raise HTTPException(409, "Workflow is stopped, unclaimed or needs its original host to resume.")
    step = next((item for item in flow["plan"]["steps"] if item["id"] == binding["step_id"]), None)
    manifest = quote.get("workload") or {}
    if (not step or step["source"] != source or step["parameters"] != manifest.get("parameters")
            or step["max_cost_lamports"] != quote["max_cost_lamports"] or step["max_runtime_seconds"] != quote["max_runtime_seconds"]):
        raise HTTPException(403, "This task differs from the owner's approved workflow step.")
    inputs = []
    for reference in step["inputs"]:
        if "from_step" in reference:
            parent = core.store.get("jobs", flow["tasks"].get(reference["from_step"], ""))
            item = next((item for item in ((parent or {}).get("receipt") or {}).get("artifacts", []) if item["name"] == reference["artifact"]), None)
            if item is None or (parent.get("receipt") or {}).get("execution_status") != "completed":
                raise HTTPException(409, "The approved dependency is not successfully settled yet.")
            inputs.append(item)
        else:
            inputs.append(reference)
    if sorted(inputs, key=lambda item: item["name"]) != manifest.get("inputs"):
        raise HTTPException(403, "Task inputs differ from the owner's approved workflow.")
    for dependency in step.get("depends_on", []):
        job = core.store.get("jobs", flow["tasks"].get(dependency, ""))
        if not job or (job.get("receipt") or {}).get("execution_status") != "completed":
            raise HTTPException(409, "Wait for each approved step dependency.")


def mount_workflow_inbox(core):
    @core.router.post("/owners/workflows/submit")
    async def submit(req: SubmitWorkflow):
        try:
            digest = sha256_text(canonical_json(req.plan))
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Plan must be finite UTF-8 JSON.") from None
        owner_authorization(core, req, "submit-workflow", task_id=digest,
            limit=req.plan.get("max_cost_lamports"), cursor=req.request_id)
        async with core.lock:
            identifier = "flow-" + sha256_text(canonical_json({"owner": req.owner, "agent_pubkey": req.agent_pubkey, "request_id": req.request_id}))
            existing = core.store.assigned_workflow(identifier)
            if existing:
                if existing["plan_sha256"] != digest:
                    raise HTTPException(409, "This request already approved a different plan. Use a new request ID.")
                return workflow_summary(core, existing)
            if req.owner == req.agent_pubkey:
                raise HTTPException(422, "Choose a delegated agent for autonomous execution.")
            try:
                validate_plan(core, req.plan, req.owner, req.agent_pubkey)
            except (ValueError, TypeError, KeyError, PermissionError) as error:
                raise HTTPException(422, str(error)) from None
            policy = await core.passport(req.owner, req.agent_pubkey,
                max(step["max_cost_lamports"] for step in req.plan["steps"]),
                max(step["max_runtime_seconds"] for step in req.plan["steps"]))
            allowance = await core.passport_allowance_summary(policy)
            if allowance.get("remaining_lamports") is None or allowance["remaining_lamports"] < req.plan["max_cost_lamports"]:
                raise HTTPException(403, "The approved total cap exceeds this agent's available lifetime allowance. Update its passport or lower the plan cap.")
            fields = {"action": "submit-workflow", "owner": req.owner, "agent_pubkey": req.agent_pubkey,
                "issued_at": req.issued_at, "nonce": req.nonce, "task_id": digest, "limit": req.plan["max_cost_lamports"],
                "cursor": req.request_id, "program_id": str(core.solana.program_id), "gateway_pubkey": str(core.solana.ai_signer.pubkey()),
                "network": "off_chain" if core.demo_mode else "devnet"}
            value = {"workflow_id": identifier, "owner": req.owner, "agent_pubkey": req.agent_pubkey,
                "request_id": req.request_id, "plan": req.plan, "plan_sha256": digest,
                "owner_signed_message": "Aperture owner control v1\naudience:aperture-gateway\n" + canonical_json(fields),
                "owner_signature": req.signature, "status": "queued", "tasks": {}, "stop_requested": False,
                "completed_steps": 0, "charged_lamports": 0, "estimated_charge_lamports": 0, "created_at": time.time(), "updated_at": time.time()}
            try:
                core.store.save_assigned_workflow(value)
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
            return workflow_summary(core, value)

    @core.router.post("/agents/workflows/list")
    async def list_workflows(req: OwnerControl):
        core.authorize_agent_task_read(**req.model_dump(), action="list-assigned-workflows", limit=20)
        values = core.store.assigned_workflows(req.owner, req.agent_pubkey)
        active = sorted((value for value in values if workflow_summary(core, value)["status"] not in TERMINAL), key=lambda value: value["created_at"])
        return {"workflows": [{**workflow_summary(core, value), "plan": value["plan"],
            "owner_signed_message": value["owner_signed_message"], "owner_signature": value["owner_signature"]} for value in active[:20]]}

    @core.router.post("/agents/workflows/claim")
    async def claim(req: ClaimWorkflow):
        core.authorize_agent_task_read(**req.model_dump(include={"owner", "agent_pubkey", "issued_at", "nonce", "signature"}),
            action="claim-assigned-workflow", task_id=req.workflow_id, cursor=req.host_id)
        async with core.lock:
            value = core.store.assigned_workflow(req.workflow_id)
            if not value or (value["owner"], value["agent_pubkey"]) != (req.owner, req.agent_pubkey):
                raise HTTPException(404, "Assigned workflow not found.")
            if value["stop_requested"] or value["status"] in TERMINAL:
                raise HTTPException(409, "This workflow is stopped or already terminal.")
            if value.get("host_id") and value["host_id"] != req.host_id:
                raise HTTPException(409, "Recover this workflow on its original host and journal; another host cannot repeat its admissions.")
            value.update(host_id=req.host_id, lease_token=secrets.token_urlsafe(32), lease_expires_at=time.time() + 30,
                         heartbeat_at=time.time(), updated_at=time.time(), status="running")
            core.store.save_assigned_workflow(value)
            return {**workflow_summary(core, value), "plan": value["plan"], "lease_token": value["lease_token"],
                "owner_signed_message": value["owner_signed_message"], "owner_signature": value["owner_signature"]}

    @core.router.post("/agents/workflows/read")
    async def read(req: FlowControl):
        core.authorize_agent_task_read(**req.model_dump(include={"owner", "agent_pubkey", "issued_at", "nonce", "signature"}),
            action="read-assigned-workflow", task_id=req.workflow_id)
        value = core.store.assigned_workflow(req.workflow_id)
        if not value or (value["owner"], value["agent_pubkey"]) != (req.owner, req.agent_pubkey):
            raise HTTPException(404, "Assigned workflow not found.")
        return {**workflow_summary(core, value), "plan": value["plan"],
            "owner_signed_message": value["owner_signed_message"], "owner_signature": value["owner_signature"]}

    @core.router.post("/agents/workflows/publish")
    async def publish(req: PublishWorkflow):
        encoded = canonical_json(req.progress)
        if len(encoded.encode()) > 64000:
            raise HTTPException(422, "Progress is limited to 64 KB.")
        core.authorize_agent_task_read(**req.model_dump(include={"owner", "agent_pubkey", "issued_at", "nonce", "signature"}),
            action="publish-assigned-workflow", task_id=req.workflow_id, cursor=sha256_text(req.lease_token + "\n" + encoded))
        async with core.lock:
            value = core.store.assigned_workflow(req.workflow_id)
            if not value or (value["owner"], value["agent_pubkey"]) != (req.owner, req.agent_pubkey) or value.get("lease_token") != req.lease_token:
                raise HTTPException(409, "Workflow lease changed; recover the retained journal before publishing.")
            steps = req.progress.get("steps", [])
            if not isinstance(steps, list) or len(steps) > 256:
                raise HTTPException(422, "Invalid step progress.")
            by_id = {step["id"]: step for step in value["plan"]["steps"]}
            tasks = dict(value.get("tasks", {}))
            for item in steps:
                if not isinstance(item, dict) or item.get("id") not in by_id or not isinstance(item.get("task_id"), str):
                    raise HTTPException(422, "Progress contains an unknown step.")
                previous = tasks.get(item["id"])
                if previous and previous != item["task_id"]:
                    raise HTTPException(409, "A retained workflow step cannot acquire a second task.")
                tasks[item["id"]] = item["task_id"]
            if len(set(tasks.values())) != len(tasks):
                raise HTTPException(422, "Each step must retain its own admission.")
            jobs = {}
            for identifier, task_id in tasks.items():
                job, step = core.store.get("jobs", task_id), by_id[identifier]
                if (not job or (job.get("wallet"), job.get("agent_pubkey")) != (req.owner, req.agent_pubkey)
                        or job["code_sha256"] != sha256_text(step["source"])
                        or job["max_cost_lamports"] != step["max_cost_lamports"]
                        or job["max_runtime_seconds"] != step["max_runtime_seconds"]
                        or (job.get("workload") or {}).get("parameters") != step["parameters"]):
                    raise HTTPException(422, "A reported task differs from the owner-approved step.")
                inputs = []
                for reference in step["inputs"]:
                    if "from_step" in reference:
                        parent = core.store.get("jobs", tasks.get(reference["from_step"], ""))
                        artifact = next((item for item in ((parent or {}).get("receipt") or {}).get("artifacts", []) if item["name"] == reference["artifact"]), None)
                        if artifact is None:
                            raise HTTPException(422, "Reported task is missing its retained dependency result.")
                        inputs.append(artifact)
                    else:
                        inputs.append(reference)
                if sorted(inputs, key=lambda item: item["name"]) != (job.get("workload") or {}).get("inputs"):
                    raise HTTPException(422, "Reported task changed the approved input references.")
                jobs[identifier] = job
            completed = sum((job.get("receipt") or {}).get("execution_status") == "completed" for job in jobs.values())
            charged = sum((job.get("receipt") or {}).get("charged_lamports") or 0 for job in jobs.values())
            estimated = sum(min(job["max_cost_lamports"], math.ceil((job.get("receipt") or {}).get("execution_time", 0) * job["rate_lamports"])) for job in jobs.values())
            state = req.progress.get("status", "running")
            if state not in {"running", "completed", "attention", "failed", "stopped"}:
                raise HTTPException(422, "Invalid workflow host state.")
            if state == "completed" and completed != len(by_id):
                raise HTTPException(409, "Completion requires a settled successful receipt for every approved step.")
            if value["stop_requested"]:
                await cancel_tracked(core, value)
                # Settlement may have changed counters while the host was stopping.
                retained = core.store.assigned_workflow(req.workflow_id)
                completed = retained["completed_steps"]
                charged = retained["charged_lamports"]
                estimated = retained["estimated_charge_lamports"]
                state = "stopped" if all((core.store.get("jobs", task_id) or {}).get("state") == "completed" for task_id in tasks.values()) else "stopping"
            value.update(tasks=tasks, completed_steps=completed, charged_lamports=charged, estimated_charge_lamports=estimated,
                status=state, detail=str(req.progress.get("detail", ""))[:1500], heartbeat_at=time.time(), lease_expires_at=time.time() + 30, updated_at=time.time())
            core.store.save_assigned_workflow(value)
            return workflow_summary(core, value)

    @core.router.post("/owners/workflows/stop")
    async def stop(req: FlowControl):
        owner_authorization(core, req, "stop-assigned-workflow", task_id=req.workflow_id)
        async with core.lock:
            value = core.store.assigned_workflow(req.workflow_id)
            if not value or (value["owner"], value["agent_pubkey"]) != (req.owner, req.agent_pubkey):
                raise HTTPException(404, "Owner's workflow not found.")
            if value["status"] not in TERMINAL:
                value.update(stop_requested=True, updated_at=time.time())
                if value["status"] == "queued":
                    value["status"] = "stopped"
                core.store.save_assigned_workflow(value)
                await cancel_tracked(core, value)
                value = core.store.assigned_workflow(req.workflow_id)
                value.update(status="stopped" if all((core.store.get("jobs", task_id) or {}).get("state") == "completed" for task_id in value["tasks"].values()) else "stopping")
                core.store.save_assigned_workflow(value)
            return workflow_summary(core, value)

    @core.router.get("/owners/agents/{agent}/workflows")
    async def overview(agent: str, view: str | None = Header(default=None, alias="X-Aperture-Owner-View")):
        identity = view_payload(core, view, agent)
        return {"workflows": [workflow_summary(core, value) for value in core.store.assigned_workflows(identity["owner"], agent)]}

    @core.router.post("/owners/workflows/archive")
    async def archive(req: FlowControl):
        owner_authorization(core, req, "archive-assigned-workflow", task_id=req.workflow_id)
        async with core.lock:
            value = core.store.assigned_workflow(req.workflow_id)
            if not value or (value["owner"], value["agent_pubkey"]) != (req.owner, req.agent_pubkey):
                raise HTTPException(404, "Owner's workflow not found.")
            if workflow_summary(core, value)["status"] not in TERMINAL:
                raise HTTPException(409, "Only finished or stopped workflows can be archived.")
            value.update(status="archived", updated_at=time.time())
            core.store.save_assigned_workflow(value)
            return workflow_summary(core, value)
