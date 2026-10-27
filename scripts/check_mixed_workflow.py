"""Real local mixed-workflow transport check with a synthetic HTTP model fixture.

No model provider is contacted, no API key is used, and no SOL payment is made.
"""
import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import requests
from solders.keypair import Keypair
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from demo_workflow import available_port, stop_demo_services
from check_mcp_stdio import call
from aperture_client import ApertureClient
from aperture_client.jobs import inference_source
from aperture_client.workflows import WorkflowRunner
from aperture_client.client import canonical, sha256
from aperture_client.sentinel import PROMPT_PREFIX
import secrets

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'aperture-workflow-fixture'
TEXT = 'Compute budgets keep agents accountable. Қазақстан.'


class ProviderHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
        self.wfile.write(json.dumps({'requests': len(self.server.requests)}).encode())

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append(request)
        prompt = request['messages'][0]['content']
        if prompt.startswith(PROMPT_PREFIX):
            text = json.dumps({'security': 'REVIEW', 'reason': 'Local HTTP fixture: signed source-review transport test, not an AI assessment.',
                'findings': [{'severity': 'info', 'line': 1, 'issue': 'Inspect the exact reviewed source.', 'evidence': 'print(6 * 7)'}]})
        else:
            text = 'The attached statistics describe the exact generated text.' if '[Aperture input analyze/analysis.json]' in json.dumps(request) else TEXT
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
        self.wfile.write(('data: ' + json.dumps({'model': MODEL, 'choices': [{'index': 0, 'delta': {'content': text}}]}) + '\n\ndata: [DONE]\n\n').encode())
        self.wfile.flush()


def build_plan(offer, workers):
    targets = {runtime: {key: next(worker for worker in workers if runtime in worker['runtimes'])[key]
                        for key in ('node_id', 'worker_pubkey')} for runtime in ('python', 'inference.chat')}
    common = {'max_cost_lamports': 1000000, 'max_runtime_seconds': 60}
    def model(identifier, prompt, **extra):
        parameters = {'inference': {'provider_id': offer['id'], 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 128},
                      'offer': {key: value for key, value in offer.items()
                                if key not in {'available_workers', 'lowest_worker_rate_lamports_sec', 'rate_lamports_sec'}}}
        return {'id': identifier, 'source': inference_source(parameters), 'inputs': [], 'parameters': parameters,
                **common, 'worker_target': targets['inference.chat'], **extra}
    return {'version': 1, 'max_cost_lamports': 3000000, 'steps': [
        model('generate', 'Explain a compute budget.'),
        {'id': 'analyze', 'source': json.loads((ROOT / 'backend/workloads/model_workflow.json').read_text())['analysis_source'],
         'inputs': [{'from_step': 'generate', 'artifact': 'response.txt'}], 'parameters': {},
         **common, 'worker_target': targets['python']},
        model('interpret', 'Interpret the attached text statistics.',
              message_inputs=[{'from_step': 'analyze', 'artifact': 'analysis.json', 'message_index': 0}]),
    ]}


async def mcp_check(client, plan, state, key_path, owner):
    environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'sdk/python'), 'PYTHONIOENCODING': 'utf-8',
        'APERTURE_GATEWAY_URL': client.url, 'APERTURE_OWNER_PUBKEY': client.owner, 'APERTURE_AGENT_KEYPAIR': str(key_path),
        'APERTURE_PROGRAM_ID': client.program_id, 'APERTURE_GATEWAY_PUBKEY': client.gateway_pubkey,
        'APERTURE_NETWORK': 'off_chain', 'APERTURE_TREASURY_PUBKEY': '', 'SOLANA_RPC_URL': '',
        'APERTURE_MCP_EXECUTION_ENABLED': 'true', 'APERTURE_MCP_MAX_COST_LAMPORTS': '1000000',
        'APERTURE_MCP_MAX_RUNTIME_SECONDS': '60', 'APERTURE_MCP_MAX_WORKFLOW_COST_LAMPORTS': '3000000',
        'APERTURE_MCP_WORKFLOW_DIRECTORY': str(state / 'mcp-workflows')}
    parameters = StdioServerParameters(command=sys.executable, args=['-X', 'utf8', '-m', 'aperture_client.mcp_server'], cwd=ROOT, env=environment)
    async with Client(parameters, read_timeout_seconds=30) as host:
        prepared = await call(host, 'prepare_compute_workflow', {'steps': plan['steps'], 'max_cost_lamports': plan['max_cost_lamports']})
        identifier = prepared['workflow_id']
        await call(host, 'start_compute_workflow', {'workflow_id': identifier})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            result = await call(host, 'get_compute_workflow', {'workflow_id': identifier})
            if result['status'] in {'completed', 'failed'}:
                break
            await asyncio.sleep(.4)
        if result['status'] != 'completed' or result['completed_steps'] != 3:
            raise RuntimeError('Mixed MCP workflow failed: ' + str(result))
        await call(host, 'start_compute_workflow', {'workflow_id': identifier})
        request_id = secrets.token_hex(16)
        digest = sha256(canonical(plan))
        fields = {'owner': client.owner, 'agent_pubkey': client.agent, 'issued_at': int(time.time()), 'nonce': secrets.token_hex(16)}
        approval = {'action': 'submit-workflow', **fields, 'task_id': digest, 'limit': plan['max_cost_lamports'],
                    'cursor': request_id, 'program_id': client.program_id, 'gateway_pubkey': client.gateway_pubkey, 'network': 'off_chain'}
        message = 'Aperture owner control v1\naudience:aperture-gateway\n' + canonical(approval)
        response = requests.post(client.url + '/owners/workflows/submit', json={**fields, 'request_id': request_id,
            'plan': plan, 'signature': list(bytes(owner.sign_message(message.encode())))}, timeout=15)
        if response.status_code != 200:
            raise RuntimeError('Mixed owner approval failed: ' + response.text)
        identifier = response.json()['workflow_id']
        await call(host, 'start_assigned_workflow', {'workflow_id': identifier})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            assigned = await call(host, 'get_assigned_workflow_progress')
            if assigned.get('status') in {'completed', 'failed', 'attention', 'stopped'}:
                break
            await asyncio.sleep(.4)
        if assigned.get('status') != 'completed' or assigned.get('completed_steps') != 3:
            raise RuntimeError('Mixed owner-assigned workflow failed: ' + str(assigned))
        source = 'print(6 * 7)\n'
        review_quote = await call(host, 'quote_source_review', {'provider_id': 'operator-model', 'source': source, 'max_tokens': 512})
        review_task = await call(host, 'start_inference_task', {'quote_id': review_quote['quote_id']})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            review = await call(host, 'get_source_review', {'task_id': review_task['task_id'], 'source': source})
            if review.get('ready'):
                break
            await asyncio.sleep(.4)
        assert review.get('verified') and review['report']['security'] == 'REVIEW'
        compute_quote = await call(host, 'quote_reviewed_job', {'source': source, 'review_task_id': review_task['task_id']})
        assert compute_quote['source_review'] == review['review_reference']
        compute_task = await call(host, 'start_compute_job', {'quote_id': compute_quote['quote_id']})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            computed = await call(host, 'get_python_task', {'task_id': compute_task['task_id']})
            if computed.get('ready'):
                break
            await asyncio.sleep(.4)
        assert computed.get('verified') and computed['output'].strip() == '42'
        assert computed['receipt']['workload_sha256'] == compute_quote['workload_sha256']
        return result, assigned, review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help='Keep only this isolated fixture stack running for browser QA')
    parser.add_argument('--api-port', type=int)
    parser.add_argument('--ui-port', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    state = (args.output or ROOT / '.aperture' / ('mixed-check-' + str(time.time_ns()))).resolve()
    state.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), ProviderHandler)
    server.requests = []; server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api_port, ui_port = args.api_port or available_port(), args.ui_port or available_port()
    node = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
    env = {**os.environ, 'GEMINI_API_KEY': '', 'DEEPSEEK_API_KEY': '',
           'APERTURE_NODE_EXECUTABLE': node, 'PYTHONIOENCODING': 'utf-8'}
    log = (state / 'launcher.log').open('w', encoding='utf-8')
    process = None
    client = None
    summary = {'status': 'failed', 'model': 'synthetic_http_fixture', 'settlement': 'OFF_CHAIN'}
    try:
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/inference_preview.py'),
            '--base-url', f'http://127.0.0.1:{server.server_port}/v1', '--model', MODEL,
            '--api-port', str(api_port), '--ui-port', str(ui_port), '--state', str(state),
            *([] if args.serve else ['--no-ui'])], cwd=ROOT, env=env,
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        url = f'http://127.0.0.1:{api_port}'
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Isolated preview stopped; inspect its launcher log.')
            try:
                health = requests.get(url + '/health', timeout=2).json()
                workers = requests.get(url + '/workers', timeout=2).json()['workers']
                if len(workers) == 2 and all(worker['online'] for worker in workers):
                    break
            except requests.RequestException:
                pass
            time.sleep(.3)
        else:
            raise TimeoutError('Isolated mixed-workflow stack did not become ready.')
        owner, agent = Keypair(), Keypair()
        key_path = state / 'agent.keypair.json'; key_path.write_text(json.dumps(list(bytes(agent))))
        client = ApertureClient(url, owner=str(owner.pubkey()), agent_keypair=agent,
            program_id=health['program_id'], gateway_pubkey=health['gateway_pubkey'], network='off_chain')
        client.passport(owner, name='Mixed workflow integration fixture', max_cost_lamports=1000000,
            max_runtime_seconds=60, total_budget_lamports=30000000, capabilities=['python.execute', 'inference.chat'])
        plan = build_plan(client.inference_providers()[0], workers)
        (state / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        def interrupt(event):
            if event['state'] == 'admitted':
                raise InterruptedError('Intentional recovery checkpoint')
        try:
            WorkflowRunner(client, state / 'workflow.sqlite3').run(plan['steps'], max_cost_lamports=plan['max_cost_lamports'], on_progress=interrupt)
        except InterruptedError:
            pass
        result = WorkflowRunner(client, state / 'workflow.sqlite3').run(plan['steps'], max_cost_lamports=plan['max_cost_lamports'])
        replay = WorkflowRunner(client, state / 'workflow.sqlite3').run(plan['steps'], max_cost_lamports=plan['max_cost_lamports'])
        analysis = result['steps']['analyze']
        from aperture_client.client import Task
        content = client.download_artifact(Task(**analysis['task']), analysis['result']['receipt'], 'analysis.json')
        measured = json.loads(content)
        assert measured == {'characters': len(TEXT), 'words': len(TEXT.split()), 'lines': 1, 'sha256': hashlib.sha256(TEXT.encode()).hexdigest()}
        assert result['steps']['generate']['task']['task_id'] == replay['steps']['generate']['task']['task_id']
        assert len(server.requests) == 2
        assert json.dumps(measured, separators=(',', ':')) in server.requests[1]['messages'][0]['content']
        mcp_result, assigned, mcp_review = asyncio.run(mcp_check(client, plan, state, key_path, owner))
        assert len(server.requests) == 7
        source = 'print(6 * 7)\n'
        review_quote = client.quote_source_review('operator-model', source, max_tokens=512, max_runtime_seconds=60)
        review_task = client.execute_inference(review_quote)
        client.wait(review_task, timeout_seconds=60)
        review = client.source_review(review_task.task_id, source)
        bundle_path = state / 'source-review.json'
        bundle_path.write_text(json.dumps(review['bundle'], ensure_ascii=False, indent=2), encoding='utf-8')
        compute_quote = client.quote_reviewed_job(source, review_task.task_id, max_runtime_seconds=60)
        assert compute_quote['workload']['parameters']['aperture_review'] == review['review_reference']
        computed = client.wait(client.execute_job(compute_quote, source, parameters=compute_quote['workload']['parameters']), timeout_seconds=60)
        assert computed['output'].strip() == '42'
        try:
            client.quote_reviewed_job(source + '# changed', review_task.task_id)
        except ValueError:
            pass
        else:
            raise AssertionError('A changed source reused a completed Sentinel review')
        assert len(server.requests) == 8
        summary.update(status='completed', sdk_steps=3, mcp_steps=mcp_result['completed_steps'],
            owner_assigned_steps=assigned['completed_steps'],
            checkpoint_recovered=True, replay_without_duplicate_model_requests=True,
            exact_unicode_response_statistics=True, explicit_worker_targets=True, model_requests=8,
            sdk_source_review_and_compute=True, mcp_source_review_and_compute=mcp_review['verified'],
            changed_review_source_rejected=True, review_bundle=str(bundle_path),
            gateway_url=url, fixture_url=f'http://127.0.0.1:{server.server_port}')
        if args.serve:
            summary['browser_url'] = f'http://127.0.0.1:{ui_port}/#workflows'
        (state / 'summary.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2), flush=True)
        if args.serve:
            while process.poll() is None:
                time.sleep(.5)
    finally:
        try:
            if client:
                client.http.close()
        finally:
            try:
                if process:
                    stop_demo_services([process])
            finally:
                log.close(); server.shutdown(); server.server_close()


if __name__ == '__main__':
    main()
