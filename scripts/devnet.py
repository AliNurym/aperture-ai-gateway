"""Explicit Devnet configuration and a real paid workload; never uses mainnet."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer

PROJECT = Path(__file__).resolve().parents[1]
LOCAL = PROJECT / '.aperture' / 'demo'
STATE = LOCAL / 'devnet'
RPC = 'https://api.devnet.solana.com'
sys.path.insert(0, str(PROJECT / 'sdk' / 'python'))
from aperture_client import ApertureClient, Task, load_keypair


def prepare():
    public = json.loads((LOCAL / 'public.json').read_text(encoding='utf-8'))
    owner = load_keypair(LOCAL / 'owner.keypair.json')
    agent = load_keypair(LOCAL / 'agent.keypair.json')
    gateway = load_keypair(LOCAL / 'gateway.keypair.json')
    if (str(owner.pubkey()), str(agent.pubkey()), str(gateway.pubkey())) != (
            public['owner_pubkey'], public['agent_pubkey'], public['gateway_pubkey']):
        raise SystemExit('Local keys differ from the public configuration. Existing settings were preserved.')
    STATE.mkdir(parents=True, exist_ok=True)
    if (STATE / 'public.json').exists() or (STATE / 'gateway.env').exists():
        raise SystemExit('Devnet settings already exist. Reuse them; no keys were replaced.')
    treasury_path = STATE / 'treasury.keypair.json'
    if treasury_path.exists():
        treasury = load_keypair(treasury_path)
    else:
        treasury = Keypair()
        with treasury_path.open('x', encoding='utf-8') as output:
            json.dump(list(bytes(treasury)), output)
    public.update(network='devnet', rpc_url=RPC, treasury=str(treasury.pubkey()))
    values = dict(dotenv_values(LOCAL / 'gateway.env'))
    values.update(APERTURE_DEMO_MODE='false', SOLANA_RPC_URL=RPC,
                  APERTURE_CONFIG_AUTHORITY=public['gateway_pubkey'],
                  APERTURE_TREASURY_PUBKEY=public['treasury'],
                  APERTURE_STATE_DB=str(STATE / 'gateway.sqlite3'),
                  APERTURE_WORKER_STATE_DIR=str(STATE / 'worker'))
    with (STATE / 'gateway.env').open('x', encoding='utf-8', newline='\n') as output:
        for name, value in values.items():
            output.write(f'{name}={json.dumps(value)}\n')
    (STATE / 'public.json').write_text(json.dumps(public, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(public, indent=2))
    print('Prepared separate Devnet settings. No transaction or airdrop was submitted.')


def context():
    public = json.loads((STATE / 'public.json').read_text(encoding='utf-8'))
    if public['network'] != 'devnet' or public['rpc_url'] != RPC:
        raise SystemExit('This helper is restricted to the official Solana Devnet endpoint.')
    owner = load_keypair(LOCAL / 'owner.keypair.json')
    agent = load_keypair(LOCAL / 'agent.keypair.json')
    gateway = load_keypair(LOCAL / 'gateway.keypair.json')
    if (str(owner.pubkey()), str(agent.pubkey()), str(gateway.pubkey())) != (
            public['owner_pubkey'], public['agent_pubkey'], public['gateway_pubkey']):
        raise SystemExit('Pinned development identities differ from the available keys.')
    client = ApertureClient(public['gateway_url'], owner=public['owner_pubkey'],
        agent_keypair=agent, program_id=public['program_id'], gateway_pubkey=public['gateway_pubkey'],
        treasury=public['treasury'], rpc_url=RPC, network='devnet')
    return public, owner, gateway, client


def initialize():
    public, _, gateway, client = context()
    manifest = json.loads((PROJECT / 'target/deploy/build-manifest.json').read_text(encoding='utf-8-sig'))
    binary = PROJECT / 'target/deploy/aperture_gateway.so'
    with binary.open('rb') as binary_file:
        digest = hashlib.file_digest(binary_file, 'sha256').hexdigest()
    if (manifest['program_id'] != public['program_id'] or manifest['config_authority'] != public['gateway_pubkey']
            or digest != manifest['binary_sha256']):
        raise SystemExit('Build manifest differs from the intended Devnet deployment.')
    program = Pubkey.from_string(public['program_id'])
    deployed = client.rpc('getAccountInfo', [str(program), {'encoding': 'base64', 'commitment': 'confirmed'}])['value']
    if not deployed or not deployed['executable']:
        raise SystemExit('Deploy the reviewed binary to Devnet before initializing its configuration.')
    solana = PROJECT / '.aperture/tools/agave-4.3.0/solana-release/bin/solana.exe'
    dumped = STATE / 'deployed-program.bin'
    result = subprocess.run([str(solana), '--url', RPC, '--keypair', str(LOCAL / 'gateway.keypair.json'),
                             'program', 'dump', str(program), str(dumped)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('The deployed program could not be read back. No initialization was submitted.')
    actual = dumped.read_bytes()
    if len(actual) < manifest['binary_bytes'] or any(actual[manifest['binary_bytes']:]) or hashlib.sha256(
            actual[:manifest['binary_bytes']]).hexdigest() != manifest['binary_sha256']:
        raise SystemExit('The deployed bytes differ from the reviewed build. No initialization was submitted.')
    config, _ = Pubkey.find_program_address([b'config'], program)
    if client.account(config) is not None:
        print(json.dumps(client.verify_protocol_config(), indent=2))
        print('Compatible configuration already exists; it was preserved.')
        return
    treasury = Pubkey.from_string(public['treasury'])
    balance = client.rpc('getBalance', [str(treasury), {'commitment': 'confirmed'}])['value']
    minimum = client.rpc('getMinimumBalanceForRentExemption', [0])
    if balance < minimum:
        funding = transfer(TransferParams(from_pubkey=gateway.pubkey(), to_pubkey=treasury, lamports=minimum - balance))
        print('Treasury rent funding:', client.send_instruction(funding, gateway), flush=True)
    data = hashlib.sha256(b'global:initialize_config').digest()[:8] + bytes(treasury)
    accounts = [AccountMeta(config, False, True), AccountMeta(gateway.pubkey(), True, True),
                AccountMeta(Pubkey.from_string('11111111111111111111111111111111'), False, False)]
    signature = client.send_instruction(Instruction(program, data, accounts), gateway)
    proof = {'config_address': str(config), 'initialization_signature': signature, **client.verify_protocol_config()}
    (STATE / 'configuration-proof.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, indent=2))


def status():
    public, _, _, client = context()
    balances = {name: client.rpc('getBalance', [public[field], {'commitment': 'confirmed'}])['value']
                for name, field in [('gateway', 'gateway_pubkey'), ('owner', 'owner_pubkey'), ('treasury', 'treasury')]}
    program = client.rpc('getAccountInfo', [public['program_id'], {'encoding': 'base64', 'commitment': 'confirmed'}])['value']
    print(json.dumps({'network': 'devnet', 'rpc_url': RPC, 'program_id': public['program_id'],
                      'program_deployed': bool(program and program['executable']),
                      'balances_lamports': balances}, indent=2))


def fund_owner():
    public, owner, gateway, client = context()
    client.verify_protocol_config()
    target = 50_000_000  # 0.05 Devnet SOL covers the 0.01 deposit and account rent.
    balance = client.rpc('getBalance', [str(owner.pubkey()), {'commitment': 'confirmed'}])['value']
    amount = max(0, target - balance)
    if not amount:
        print('Development owner already has the requested reserve; no transfer was submitted.')
        return
    instruction = transfer(TransferParams(from_pubkey=gateway.pubkey(), to_pubkey=owner.pubkey(), lamports=amount))
    signature = client.send_instruction(instruction, gateway)
    proof = {'network': 'devnet', 'source': public['gateway_pubkey'],
             'destination': public['owner_pubkey'], 'lamports': amount, 'signature': signature}
    (STATE / 'owner-funding-proof.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, indent=2))


def execute(workload, deposit_lamports):
    public, owner, _, client = context()
    health = client.request('GET', '/health').json()
    if health.get('status') != 'ready' or health.get('network') != 'devnet' or health.get('gateway_pubkey') != public['gateway_pubkey']:
        raise SystemExit('The pinned Devnet gateway and an authenticated worker must be ready.')
    client.verify_protocol_config()
    if deposit_lamports:
        print('Payment channel funding:', client.fund_channel(owner, deposit_lamports), flush=True)
    policy = client.list_agent_passports(owner)
    if not any(item.get('agent_pubkey') == client.agent and not item.get('revoked')
               and item.get('expires_at', 0) > time.time() for item in policy):
        client.passport(owner, name='Devnet risk analysis agent', max_cost_lamports=1_000_000,
            max_runtime_seconds=30, total_budget_lamports=10_000_000)
    code = (LOCAL / 'approved' / f'{workload}.py').read_bytes().decode('utf-8')
    quote = client.quote(code, max_cost_lamports=1_000_000, max_runtime_seconds=30, max_rate_lamports=1_000_000)
    task = client.execute(quote, code, max_rate_lamports=1_000_000)
    pending = STATE / 'pending'
    pending.mkdir(exist_ok=True)
    (pending / f'{task.task_id}.capability.json').write_text(json.dumps({
        'task_id': task.task_id, 'access_token': task.access_token, 'quote': task.quote}, indent=2) + '\n', encoding='utf-8')
    print('Accepted Devnet task:', task.task_id, flush=True)
    finish_task(client, task)


def finish_task(client, task):
    result = client.wait(task, timeout_seconds=150)
    receipt = result['receipt']
    folder = STATE / 'evidence'
    folder.mkdir(exist_ok=True)
    (folder / f'{task.task_id}.receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    (folder / f'{task.task_id}.output.txt').write_text(result['full_log'], encoding='utf-8', newline='')
    print(result['full_log'])
    if receipt['execution_status'] != 'completed' or receipt['settlement_type'] != 'DEVNET':
        print(json.dumps({'task_id': task.task_id, 'execution_status': receipt['execution_status'],
                          'settlement_type': receipt['settlement_type']}, indent=2))
        raise SystemExit('Paid execution did not complete. Inspect the retained real outcome.')
    chain_proof = client.verify_devnet_task_receipt(task, receipt)
    proof = {'task_id': task.task_id, 'execution_status': receipt['execution_status'],
        'settlement_type': receipt['settlement_type'], 'charged_lamports': receipt['charged_lamports'],
        'settlement_signature': receipt['settlement_signature'],
        'gateway_and_worker_signatures': 'verified', 'chain_receipt_and_confirmation': 'verified',
        'chain_receipt': chain_proof}
    (folder / f'{task.task_id}.verification.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, indent=2))


def resume(task_id):
    if not re.fullmatch(r'task-[a-f0-9]{32}', task_id or ''):
        raise SystemExit('Provide the exact accepted --task-id.')
    _, _, _, client = context()
    record = json.loads((STATE / 'pending' / f'{task_id}.capability.json').read_text(encoding='utf-8'))
    finish_task(client, Task(**record))


def serve(service):
    public, _, _, _ = context()
    load_dotenv(STATE / 'gateway.env', override=True)
    expected = {'SOLANA_RPC_URL': RPC, 'SOLANA_PROGRAM_ID': public['program_id'],
                'APERTURE_CONFIG_AUTHORITY': public['gateway_pubkey'],
                'APERTURE_TREASURY_PUBKEY': public['treasury'], 'APERTURE_DEMO_MODE': 'false'}
    for name, value in expected.items():
        if os.getenv(name) != value:
            raise SystemExit(f'{name} must match the pinned Devnet settings before starting a service.')
    os.chdir(PROJECT / 'backend')
    sys.path.insert(0, str(PROJECT / 'backend'))
    if service == 'gateway':
        import uvicorn
        uvicorn.run('main:app', host='127.0.0.1', port=8000, access_log=False)
    else:
        import worker
        if not worker.ALLOW_UNSAFE_LOCAL_EXECUTION:
            raise SystemExit('Pass --allow-unsafe-local-execution for reviewed local sources, or use the Docker launcher.')
        worker.main()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'status', 'initialize', 'fund-owner', 'run', 'resume', 'gateway', 'worker'))
    parser.add_argument('--workload', choices=('risk', 'math', 'statistics'), default='risk')
    parser.add_argument('--deposit-lamports', type=int, default=0)
    parser.add_argument('--task-id')
    parser.add_argument('--allow-unsafe-local-execution', action='store_true')
    arguments = parser.parse_args()
    if not 0 <= arguments.deposit_lamports <= 100_000_000:
        parser.error('Development deposits are capped at 0.1 Devnet SOL per call.')
    if arguments.action == 'prepare':
        prepare()
    elif arguments.action == 'status':
        status()
    elif arguments.action == 'initialize':
        initialize()
    elif arguments.action == 'fund-owner':
        fund_owner()
    elif arguments.action == 'run':
        execute(arguments.workload, arguments.deposit_lamports)
    elif arguments.action == 'resume':
        resume(arguments.task_id)
    else:
        serve(arguments.action)
