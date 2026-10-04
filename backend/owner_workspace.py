"""Owner-to-agent data handoff and a read-only window into delegated work."""
import base64
import json
import time

import base58
from fastapi import Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictInt

from agent_identity import canonical_json, sha256_text, verify_ed25519
from artifact_store import MAX_INPUT_BYTES, validate_descriptor


class OwnerControl(BaseModel):
    model_config = {"extra": "forbid"}
    owner: str = Field(min_length=32, max_length=44)
    agent_pubkey: str = Field(min_length=32, max_length=44)
    issued_at: StrictInt = Field(gt=0)
    nonce: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    signature: list[StrictInt] = Field(min_length=64, max_length=64)


class AssignObject(OwnerControl):
    object_id: str = Field(pattern=r"^obj-[0-9a-f]{32}$")
    name: str = Field(min_length=1, max_length=80)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=MAX_INPUT_BYTES)


class AssignInputs(OwnerControl):
    inputs: list[dict] = Field(min_length=1, max_length=200)


def owner_authorization(core, req, action, **bindings):
    core.authorize_agent_task_read(**req.model_dump(include={
        "owner", "agent_pubkey", "issued_at", "nonce", "signature"}),
        action=action, owner_control=True, **bindings)


def view_payload(core, token, agent):
    """A 15-minute bearer permits observation, never admission or cancellation."""
    try:
        if not isinstance(token, str) or len(token) > 2048:
            raise ValueError()
        encoded, signature = token.split(".")
        message = base64.urlsafe_b64decode(encoded).decode("utf-8")
        payload = json.loads(message.removeprefix("Aperture owner view v1\n"))
        if (not message.startswith("Aperture owner view v1\n")
                or not verify_ed25519(str(core.solana.ai_signer.pubkey()), list(base58.b58decode(signature)), message)
                or payload["agent_pubkey"] != agent
                or payload["expires_at"] <= int(time.time())
                or payload["gateway_pubkey"] != str(core.solana.ai_signer.pubkey())
                or payload["program_id"] != str(core.solana.program_id)
                or payload["network"] != ("off_chain" if core.demo_mode else "devnet")):
            raise ValueError()
        return payload
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(401, "Owner view expired or changed; open the agent workspace again.") from None


def public_task(core, job):
    fields = ("quote_id", "wallet", "agent_pubkey", "code_sha256", "rate_lamports",
        "max_cost_lamports", "max_runtime_seconds", "expires_at", "passport_version",
        "program_id", "network", "gateway_pubkey", "treasury", "effective_runtime_seconds",
        "analysis", "message", "workload", "workload_sha256", "workload_canonical", "workflow")
    return {**core.recovery_task_summary(job),
        "quote": {key: job[key] for key in fields if key in job},
        "receipt": job.get("receipt"), "full_log": (job.get("result") or {}).get("full_log", "")}


def mount_owner_workspace(core):
    @core.router.post("/owners/objects/assign-batch")
    async def assign_batch(req: AssignInputs):
        try:
            inputs = [validate_descriptor(item) for item in req.inputs]
            size = sum(item["size_bytes"] for item in inputs)
            if len({item["object_id"] for item in inputs}) != len(inputs) or size > 256 * 1024 * 1024:
                raise ValueError("Assign unique inputs totaling at most 256 MiB.")
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        owner_authorization(core, req, "assign-inputs", task_id=sha256_text(canonical_json(inputs)), limit=size)
        async with core.lock:
            await core.passport(req.owner, req.agent_pubkey, 1, 1)
            try:
                # Validate the complete selection before creating any references.
                for item in inputs:
                    core.objects.resolve(item, owner=req.owner, agent=req.owner)
                references = [core.objects.assign(item, owner=req.owner, agent=req.agent_pubkey) for item in inputs]
            except PermissionError as error:
                raise HTTPException(403, str(error)) from None
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
        return {"owner": req.owner, "agent_pubkey": req.agent_pubkey, "inputs": references}

    @core.router.post("/owners/objects/assign")
    async def assign(req: AssignObject):
        try:
            item = validate_descriptor(req.model_dump(include={"object_id", "name", "sha256", "size_bytes"}))
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        owner_authorization(core, req, "assign-object", task_id=item["object_id"],
            limit=item["size_bytes"], cursor=item["name"] + ":" + item["sha256"])
        async with core.lock:
            await core.passport(req.owner, req.agent_pubkey, 1, 1)
            try:
                reference = core.objects.assign(item, owner=req.owner, agent=req.agent_pubkey)
            except PermissionError as error:
                raise HTTPException(403, str(error)) from None
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
        return {"owner": req.owner, "agent_pubkey": req.agent_pubkey, "reference": reference}

    @core.router.post("/owners/agents/observe")
    async def observe(req: OwnerControl):
        owner_authorization(core, req, "observe-agent")
        policy = core.store.get("agents", req.agent_pubkey)
        if req.agent_pubkey != req.owner and (not policy or policy["owner"] != req.owner):
            raise HTTPException(404, "This wallet does not own the selected agent.")
        payload = {"owner": req.owner, "agent_pubkey": req.agent_pubkey,
            "expires_at": int(time.time()) + 900, "gateway_pubkey": str(core.solana.ai_signer.pubkey()),
            "program_id": str(core.solana.program_id), "network": "off_chain" if core.demo_mode else "devnet"}
        message = "Aperture owner view v1\n" + canonical_json(payload)
        token = base64.urlsafe_b64encode(message.encode()).decode() + "." + base58.b58encode(
            bytes(core.solana.ai_signer.sign_message(message.encode()))).decode()
        return {**payload, "view_token": token}

    @core.router.get("/owners/agents/{agent}/overview")
    async def overview(agent: str, cursor: str | None = None,
                       view: str | None = Header(default=None, alias="X-Aperture-Owner-View")):
        payload = view_payload(core, view, agent)
        if cursor is not None and (len(cursor) != 37 or not cursor.startswith("task-")
                                  or any(c not in "0123456789abcdef" for c in cursor[5:])):
            raise HTTPException(422, "Invalid task page cursor.")
        jobs = core.store.list_agent_jobs(payload["owner"], agent, 21, cursor=cursor)
        return {"owner": payload["owner"], "agent_pubkey": agent,
            "storage": core.objects.usage(owner=payload["owner"], agent=agent),
            "tasks": [public_task(core, job) for job in jobs[:20]],
            "next_cursor": jobs[19]["task_id"] if len(jobs) > 20 else None}

    @core.router.get("/owners/agents/{agent}/tasks/{task_id}/artifacts/{object_id}")
    async def artifact(agent: str, task_id: str, object_id: str,
                       view: str | None = Header(default=None, alias="X-Aperture-Owner-View")):
        payload = view_payload(core, view, agent)
        job = core.store.get("jobs", task_id)
        if not job or (job.get("wallet"), job.get("agent_pubkey")) != (payload["owner"], agent):
            raise HTTPException(404, "Owner's agent task not found.")
        if job.get("state") != "completed" or not job.get("receipt"):
            raise HTTPException(409, "Wait for the settled result before downloading.")
        item = next((item for item in job["receipt"].get("artifacts", []) if item["object_id"] == object_id), None)
        if item is None:
            raise HTTPException(404, "File is absent from the task receipt.")
        try:
            path = core.objects.resolve(item, owner=payload["owner"], agent=agent, task_id=task_id)
        except (ValueError, PermissionError, OSError):
            raise HTTPException(404, "Result file is no longer retained.") from None
        return FileResponse(path, filename=item["name"], media_type="application/octet-stream")
