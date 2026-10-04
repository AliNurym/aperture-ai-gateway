"""Execute console-approved work on the agent host, without moving private keys."""
import json
import re
import secrets
import threading
import time

from .client import agent_task_access_message, canonical, require, sha256, verify_signature
from .retries import retry_throttled
from .workflows import WorkflowRunner, validate_workflow
from .workflow_tools import WorkflowTools


def request(client, path, action, *, body=None, task_id=None, limit=None, cursor=None):
    def send():
        fields = {"owner": client.owner, "agent_pubkey": client.agent, "issued_at": int(time.time()), "nonce": secrets.token_urlsafe(24)}
        message = agent_task_access_message(action=action, owner=client.owner, agent=client.agent,
            issued_at=fields["issued_at"], nonce=fields["nonce"], task_id=task_id, limit=limit, cursor=cursor,
            program_id=client.program_id, gateway_pubkey=client.gateway_pubkey, network=client.network)
        return client.request("POST", path, json={**fields, **(body or {}), "signature": list(bytes(client.key.sign_message(message.encode())))}).json()
    return retry_throttled(send)


def verify_assigned_plan(client, value):
    plan = value.get("plan")
    require(isinstance(plan, dict) and plan.get("version") == 1, "Assigned workflow has no bounded plan")
    require(value.get("owner") == client.owner and value.get("agent_pubkey") == client.agent,
            "Assigned workflow changed execution identity")
    require(value.get("plan_sha256") == sha256(canonical(plan)), "Assigned plan digest changed")
    identifier = value.get("request_id")
    require(isinstance(identifier, str) and re.fullmatch(r"[0-9a-f]{32}", identifier), "Invalid owner request ID")
    require(value.get("workflow_id") == "flow-" + sha256(canonical({"owner": client.owner, "agent_pubkey": client.agent, "request_id": identifier})),
            "Assigned workflow identity changed")
    message = value.get("owner_signed_message")
    prefix = "Aperture owner control v1\naudience:aperture-gateway\n"
    require(isinstance(message, str) and message.startswith(prefix), "Missing owner workflow approval")
    approval = json.loads(message[len(prefix):])
    require(type(approval.get("issued_at")) is int and approval["issued_at"] > 0
            and isinstance(approval.get("nonce"), str) and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", approval["nonce"]),
            "Invalid retained owner approval")
    expected = {"action": "submit-workflow", "owner": client.owner, "agent_pubkey": client.agent,
        "issued_at": approval["issued_at"], "nonce": approval["nonce"], "task_id": value["plan_sha256"],
        "limit": plan["max_cost_lamports"], "cursor": identifier, "program_id": client.program_id,
        "gateway_pubkey": client.gateway_pubkey, "network": client.network}
    require(message == prefix + canonical(expected), "Owner approved a different plan, budget or deployment")
    verify_signature(client.owner, value.get("owner_signature"), message)
    validate_workflow(plan["steps"], plan["max_cost_lamports"])
    return value


class AssignedWorkflowTools:
    def __init__(self, tools):
        self.tools = tools
        self.lock = threading.RLock()
        self.active = None
        self.last = None
        self.current_workflow = None

    @property
    def busy(self):
        return self.active is not None and self.active.is_alive()

    def list(self):
        response = request(self.tools.client, "/agents/workflows/list", "list-assigned-workflows", limit=20)
        values = response.get("workflows")
        require(isinstance(values, list) and len(values) <= 20, "Invalid workflow inbox response")
        for value in values:
            verify_assigned_plan(self.tools.client, value)
        return values

    @staticmethod
    def summary(value):
        return {key: value.get(key) for key in ("workflow_id", "status", "completed_steps", "total_steps",
            "max_cost_lamports", "charged_lamports", "stop_requested", "detail", "resume_available")}

    def start(self, identifier):
        require(self.tools.execution_enabled, "Assigned execution requires APERTURE_MCP_EXECUTION_ENABLED=true")
        require(self.tools.workflows is not None, "Configure a durable MCP workflow directory")
        require(isinstance(identifier, str) and re.fullmatch(r"flow-[0-9a-f]{64}", identifier), "Invalid assigned workflow ID")
        with self.lock:
            if self.busy:
                require(self.last and self.last["workflow_id"] == identifier, "This host already has an active assigned workflow")
                return dict(self.last)
            require(not any(thread.is_alive() for thread in self.tools.workflows.active.values()),
                    "Finish the host's current workflow before receiving assigned work")
            value = request(self.tools.client, "/agents/workflows/read", "read-assigned-workflow",
                body={"workflow_id": identifier}, task_id=identifier)
            verify_assigned_plan(self.tools.client, value)
            if value["status"] in {"completed", "failed", "stopped", "archived"}:
                return self.summary(value)
            require(not value.get("stop_requested"), "The owner stopped this workflow")
            root = self.tools.workflows.root
            handle = WorkflowRunner(self.tools.client, root / "assigned-channel.sqlite3")._lock()
            try:
                host_path = root / "receiver-host.id"
                if not host_path.exists():
                    host_path.write_text(secrets.token_hex(16), encoding="utf-8")
                host = host_path.read_text(encoding="utf-8")
                require(re.fullmatch(r"[0-9a-f]{32}", host), "Retained receiver host identity changed")
                workflow = WorkflowTools(self.tools, root / "assigned" / identifier[5:37], self.tools.workflows.maximum_cost)
                workflow.assigned_workflow_id = identifier
                prepared = workflow.prepare(value["plan"]["steps"], value["plan"]["max_cost_lamports"])
                claimed = request(self.tools.client, "/agents/workflows/claim", "claim-assigned-workflow",
                    body={"workflow_id": identifier, "host_id": host}, task_id=identifier, cursor=host)
                verify_assigned_plan(self.tools.client, claimed)
                require(claimed["plan"] == value["plan"], "Claim changed the reviewed owner plan")
                self.last = self.summary(claimed)
                self.current_workflow = (workflow, prepared["workflow_id"])
                self.active = threading.Thread(target=self._bridge, args=(claimed, workflow, prepared["workflow_id"], handle), daemon=True)
                self.active.start()
                return dict(self.last)
            except BaseException:
                handle.close()
                raise

    def _bridge(self, claimed, workflow, local_id, handle):
        client = None
        try:
            client = workflow._client()
            def publish(progress):
                return request(client, "/agents/workflows/publish", "publish-assigned-workflow",
                    body={"workflow_id": claimed["workflow_id"], "lease_token": claimed["lease_token"], "progress": progress},
                    task_id=claimed["workflow_id"], cursor=sha256(claimed["lease_token"] + "\n" + canonical(progress)))
            initial = publish({"status": "running", "steps": workflow.journal_tasks(local_id)})
            if initial.get("stop_requested"):
                workflow.cancel(local_id)
                self.last = publish({"status": "stopped", "steps": workflow.journal_tasks(local_id)})
                return
            workflow.start(local_id)
            while True:
                status = workflow.get(local_id)
                progress = {"status": status["status"], "steps": workflow.journal_tasks(local_id), "detail": status.get("detail", "")}
                require(progress["status"] in {"running", "completed", "failed", "attention", "stopped"}, "Unexpected assigned runner state")
                response = publish(progress)
                with self.lock:
                    self.last = self.summary(response)
                if response.get("stop_requested") and status["status"] == "running":
                    workflow.cancel(local_id)
                if status["status"] != "running":
                    break
                threading.Event().wait(1)
        except Exception as error:
            # The stop file also fences future admissions if publication fails.
            workflow._path(local_id, ".stop").touch()
            try:
                workflow.cancel(local_id)
            except Exception:
                pass
            with self.lock:
                self.last = {**(self.last or {}), "status": "attention", "detail": str(error)[:1500], "resume_available": True}
        finally:
            if client is not None:
                client.http.close()
            handle.close()

    def get(self):
        with self.lock:
            return dict(self.last) if self.last else {"status": "idle"}

    def stop(self):
        with self.lock:
            if self.current_workflow and self.busy:
                workflow, identifier = self.current_workflow
                workflow.cancel(identifier)
            return self.get()
