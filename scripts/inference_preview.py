"""Run the combined CPU/inference workspace, or check a configured model endpoint.

Uses independent local state, ephemeral demo authority, and zero Solana payments.
Configure GEMINI_API_KEY for general model inference and AI Sentinel, or
DEEPSEEK_API_KEY for AI Sentinel source reviews only. An operator-approved
OpenAI-compatible endpoint can be supplied with --base-url.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk" / "python"))
from aperture_client import ApertureClient
from solders.keypair import Keypair
import requests
from demo_workflow import available_port, stop_demo_services
from preview_sources import approved_sources
from preview_env import load_local_inference_environment
sys.path.insert(0, str(ROOT / "backend"))
from preview_ports import resolve_preview_port
from worker_journal import WorkerInstanceLock

PROGRAM = "A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ"


def wait_for(url, processes, *, timeout=40, predicate=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("A preview service stopped. Inspect its log in the preview state directory.")
        try:
            response = requests.get(url, timeout=1)
            if response.status_code == 200 and (predicate is None or predicate(response.json())):
                return response.json()
        except requests.RequestException:
            pass
        time.sleep(.25)
    raise TimeoutError(f"Preview did not become ready: {url}")


def verify_inference(url, oracle, state, provider_id):
    owner, agent = Keypair(), Keypair()
    client = ApertureClient(url, owner=str(owner.pubkey()), agent_keypair=agent,
        program_id=PROGRAM, gateway_pubkey=str(oracle.pubkey()), network="off_chain")
    client.passport(owner, name="Inference demo agent", capabilities=["inference.chat"],
        max_runtime_seconds=60, max_cost_lamports=100000, total_budget_lamports=1000000)
    source = "print(6 * 7)\n"
    source_review_only = provider_id == 'aperture-deepseek'
    def quote_request():
        if source_review_only:
            return client.quote_source_review(provider_id, source, max_tokens=1024, max_runtime_seconds=60)
        return client.quote_inference(provider_id, [{"role": "user", "content": "In one short sentence, what is a computer?"}],
                                      max_tokens=48, max_runtime_seconds=60)
    quote = quote_request()
    task = client.execute_inference(quote)
    duplicate = client.execute_inference(quote)
    if duplicate.task_id != task.task_id:
        raise ValueError("Repeated admission created a second task")
    result = client.wait(task, timeout_seconds=90)
    if result["receipt"]["execution_status"] != "completed" or not result["output"].split("[Aperture inference metadata]")[0].strip():
        raise ValueError("Inference failed; inspect the retained worker log and result")
    # Exercise restart recovery through a fresh client, without another inference.
    resumed = ApertureClient(url, owner=client.owner, agent_keypair=agent, program_id=PROGRAM,
                             gateway_pubkey=client.gateway_pubkey, network="off_chain")
    recovered = resumed.wait(resumed.resume_task(task.task_id), timeout_seconds=10)
    if recovered["output"] != result["output"]:
        raise ValueError("Recovered inference output differs")
    review = client.source_review(task.task_id, source, timeout_seconds=10) if source_review_only else None
    if review:
        (state / 'source-review.json').write_text(json.dumps(review['bundle'], ensure_ascii=False, indent=2), encoding='utf-8')
    client.passport(owner, action="revoke", name="Inference demo agent", capabilities=["inference.chat"],
        max_runtime_seconds=60, max_cost_lamports=100000, total_budget_lamports=1000000)
    try:
        quote_request()
    except requests.HTTPError as error:
        if error.response.status_code != 403:
            raise
    else:
        raise ValueError("Revoked agent was allowed to quote inference")
    owner_client = ApertureClient(url, owner=client.owner, agent_keypair=owner, program_id=PROGRAM,
                                 gateway_pubkey=client.gateway_pubkey, network="off_chain")
    if review:
        parameters = {'aperture_review': review['review_reference']}
        cpu_quote = owner_client.quote_job(source, parameters=parameters)
        cpu_task = owner_client.execute_job(cpu_quote, source, parameters=parameters)
    else:
        cpu_quote = owner_client.quote(source)
        cpu_task = owner_client.execute(cpu_quote, source)
    cpu_result = owner_client.wait(cpu_task, timeout_seconds=20)
    if cpu_result["output"].strip() != "42":
        raise ValueError("The combined preview did not retain CPU computation")
    offer = quote["workload"]["parameters"]["offer"]
    evidence = {"scope": "HTTP inference against a configured provider endpoint plus reviewed local CPU; OFF_CHAIN, zero Solana payment",
                "provider": offer, "task_id": task.task_id,
                "receipt": result["receipt"], "quote": quote, "output": result["output"],
                "duplicate_admission": "same_task", "fresh_client_recovery": "same_output",
                "revoked_agent_quote": "rejected_403", "cpu_output": cpu_result["output"],
                "model_quality": "not_evaluated", "upstream_model_billing": "outside_aperture",
                "worker_settlement_share_pct": offer.get("worker_settlement_share_pct", 100),
                "worker_settlement_evidence": "contract_source_only; Devnet settlement not exercised",
                "devnet_settlement": "not_exercised"}
    (state / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: evidence[key] for key in ("scope", "task_id", "duplicate_admission", "fresh_client_recovery", "revoked_agent_quote", "cpu_output")}, indent=2), flush=True)
    print("Model output: " + result["output"].split("[Aperture inference metadata]")[0].strip(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Run SDK inference, recovery, revocation and CPU checks, then stop")
    parser.add_argument("--no-ui", action="store_true", help="Run gateway and workers without starting Vite")
    parser.add_argument("--base-url", help="Existing operator-approved OpenAI-compatible /v1 endpoint")
    parser.add_argument("--model", help="Required model ID when --base-url is used")
    parser.add_argument("--api-port", type=int, help="Use this API port; an occupied explicit port is an error")
    parser.add_argument("--ui-port", type=int, help="Use this UI port; an occupied explicit port is an error")
    parser.add_argument("--state", type=Path, default=ROOT / ".aperture" / "inference-preview")
    args = parser.parse_args()
    load_local_inference_environment(ROOT / "backend" / ".env", os.environ)
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    preview_lock = WorkerInstanceLock(state)
    processes, logs = [], []
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def start(name, command, cwd=ROOT, environment=None):
        log = (state / (name + ".log")).open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen(command, cwd=cwd, env=environment or env, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=creationflags)
        processes.append(process)
        return process

    try:
        base_url = args.base_url
        gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if base_url and not args.model:
            raise ValueError("--model is required with --base-url.")
        config = state / "providers.json"
        providers = []
        if gemini_api_key:
            gemini_model = os.environ.get("APERTURE_GEMINI_MODEL", "gemini-3.8-flash").strip()
            providers.append({"id": "aperture-gemini", "name": "Aperture · Gemini", "model": gemini_model,
                "base_url": "https://generativelanguage.googleapis.com/v1beta",
                "protocol": "gemini_generate_content", "api_key_env": "GEMINI_API_KEY",
                "max_output_tokens": 2048})
        if deepseek_api_key:
            deepseek_model = os.environ.get("APERTURE_DEEPSEEK_MODEL", "deepseek-flash").strip()
            providers.append({"id": "aperture-deepseek", "name": "Aperture · DeepSeek", "model": deepseek_model,
                "base_url": "https://api.deepseek.com", "protocol": "openai_chat_completions",
                "api_key_env": "DEEPSEEK_API_KEY", "max_output_tokens": 2048})
        if base_url:
            provider = {"id": "operator-model", "name": "Operator-approved model",
                "model": args.model, "base_url": base_url, "protocol": "openai_chat_completions",
                "max_output_tokens": 512}
            providers.append(provider)
        if args.check and not providers:
            raise RuntimeError("The model check requires a configured model key or an operator-approved --base-url and --model. No external model request was made.")
        config.write_text(json.dumps(providers), encoding="utf-8")
        oracle_path = state / "oracle.key"
        if not oracle_path.exists():
            oracle_path.write_bytes(bytes(Keypair()))
        oracle = Keypair.from_bytes(oracle_path.read_bytes())
        if args.check:
            api_port = available_port()
            ui_port = args.ui_port or 3000
        else:
            api_port, api_port_changed = resolve_preview_port(args.api_port, 8000, "api-port", available_port)
            ui_port, ui_port_changed = resolve_preview_port(
                args.ui_port, 3000, "ui-port", available_port, excluded=(api_port,)
            )
            if api_port_changed:
                print(f"Default API port 8000 is busy; using {api_port}.", flush=True)
            if ui_port_changed:
                print(f"Default UI port 3000 is busy; using {ui_port}.", flush=True)
        url = f"http://127.0.0.1:{api_port}"
        token = secrets.token_urlsafe(32)
        # Local operator access is separate from owner/agent signing keys. The
        # ignored preview directory is never served by the frontend or gateway.
        operator_access = state / "worker-access.json"
        operator_access.write_text(json.dumps({"gateway_url": url,
            "worker_id": "NODE-CPU-PREVIEW", "worker_token": token}, indent=2), encoding="utf-8")
        approved = state / "reviewed-python"
        approved.mkdir(exist_ok=True)
        node = os.environ.get("APERTURE_NODE_EXECUTABLE") or "node"
        sources = approved_sources(ROOT, node)
        sources["smoke"] = "print(6 * 7)\n"
        for name, source in sources.items():
            (approved / (name + ".py")).write_text(source, encoding="utf-8", newline="")
        inherited_runtime = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "APPDATA")
        service_env = {key: env[key] for key in inherited_runtime if key in env}
        service_env.update({"PYTHONIOENCODING": "utf-8", "APERTURE_ENV": "development", "APERTURE_DEMO_MODE": "true",
            "APERTURE_STATE_DB": str(state / "gateway.sqlite3"), "BACKEND_PRIVATE_KEY": json.dumps(list(bytes(oracle))),
            "APERTURE_WORKER_CREDENTIALS": "", "APERTURE_WORKER_TOKEN": token,
            "APERTURE_WORKER_RATE_LAMPORTS_SEC": os.environ.get("APERTURE_WORKER_RATE_LAMPORTS_SEC", "1000"),
            "APERTURE_INFERENCE_CONFIG": str(config), "GATEWAY_API_URL": url,
            "APERTURE_OBJECT_STORE": str(state / "objects"), "APERTURE_ALLOW_UNSAFE_LOCAL_EXECUTION": "false",
            "CORS_ORIGINS": f"http://127.0.0.1:{ui_port},http://localhost:{ui_port}"})
        start("gateway", [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(api_port)],
              ROOT / "backend", service_env)
        wait_for(url + "/health", processes)
        if providers:
            inference_env = {**service_env, "APERTURE_NODE_ID": "NODE-INFERENCE-PREVIEW",
                             "APERTURE_WORKER_STATE_DIR": str(state / "inference-worker")}
            if gemini_api_key:
                inference_env["GEMINI_API_KEY"] = gemini_api_key
            if deepseek_api_key:
                inference_env["DEEPSEEK_API_KEY"] = deepseek_api_key
            start("inference-worker", [sys.executable, "worker.py", "--inference-only"], ROOT / "backend",
                  inference_env)
        start("cpu-worker", [sys.executable, "worker.py", "--allow-unsafe-local-execution", "--trusted-source-directory", str(approved)],
              ROOT / "backend", {**service_env, "APERTURE_NODE_ID": "NODE-CPU-PREVIEW", "APERTURE_WORKER_STATE_DIR": str(state / "cpu-worker")})
        # One inference worker advertises all configured offers; the CPU worker is always present.
        expected_nodes = 1 + bool(providers)
        wait_for(url + "/active_nodes", processes, predicate=lambda data: len(data) == expected_nodes)
        if args.check:
            verification_provider = "operator-model" if base_url else providers[0]["id"]
            verify_inference(url, oracle, state, verification_provider)
            print("Evidence: " + str(state / "evidence.json"), flush=True)
        else:
            frontend_env = {key: env[key] for key in inherited_runtime if key in env}
            frontend_env["PYTHONIOENCODING"] = "utf-8"
            if not args.no_ui:
                start("frontend", [node, "scripts/vite.mjs", "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"],
                  ROOT / "frontend", {**frontend_env, "VITE_API_URL": url, "VITE_ENABLE_SESSION_KEY": "true",
                                       "VITE_APERTURE_PROGRAM_ID": PROGRAM,
                                       "VITE_APERTURE_GATEWAY_PUBKEY": str(oracle.pubkey()),
                                       "VITE_APERTURE_TREASURY_PUBKEY": ""})
            print(f"Aperture combined preview: {url if args.no_ui else f'http://127.0.0.1:{ui_port}/#studio'}", flush=True)
            print(f"Gateway API docs: {url}/docs", flush=True)
            print("Local worker operator access: " + str(operator_access), flush=True)
            if providers:
                print("OFF_CHAIN · reviewed host CPU + configured model inference · Ctrl+C stops only these services", flush=True)
            else:
                print("OFF_CHAIN · reviewed host CPU · no model provider configured; set a supported model key in backend/.env and restart to enable inference · Ctrl+C stops only these services", flush=True)
            while all(process.poll() is None for process in processes):
                time.sleep(.5)
            raise RuntimeError("A preview service stopped; inspect the preview logs")
    except KeyboardInterrupt:
        print("Stopping owned preview services.", flush=True)
    finally:
        try:
            stop_demo_services(processes)
        finally:
            for log in logs:
                log.close()
            preview_lock.close()


if __name__ == "__main__":
    main()
