"""Meaningful offline regressions for signed delegation, budgets and recovery."""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey
import base58
from nacl.signing import VerifyKey

from agent_identity import canonical_json, receipt_message, sha256_text
from gateway import Gateway
from state_store import StateStore
from worker_identity import receipt_bytes

TOKEN = 'test-worker-secret'

class FakeSolana:
    def __init__(self):
        self.ai_signer = Keypair()
        self.program_id = Pubkey.new_unique()
        self.treasury = Pubkey.new_unique()
        self.get_protocol_config = AsyncMock(return_value={'treasury': self.treasury})
        self.get_channel_state = AsyncMock(return_value={'balance_lamports': 1_000_000_000, 'effective_balance_lamports': 1_000_000_000, 'burn_rate_lamports': 0})
        self.get_agent_passport = AsyncMock(return_value=None)
        self.get_task_receipt = AsyncMock(return_value=None)
        self.prepare_start_task = AsyncMock(return_value={'signature': str(Keypair().sign_message(b'prepare')), 'transaction': 'signed-public-bytes', 'last_valid_block_height': 100})
        self.send_prepared_start = AsyncMock(return_value='start-confirmed')
        self.stop_task = AsyncMock(return_value={'signature': 'stop-confirmed', 'charged_lamports': 1000, 'evidence': 'confirmed_task_receipt'})
        self.agent_instruction = lambda action, policy: {'kind': action, 'program_id': str(self.program_id), 'data': [], 'data_base64': '', 'accounts': []}

class GatewayApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.store = StateStore(':memory:')
        self.chain = FakeSolana()
        self.core = Gateway(self.chain, True, TOKEN, self.store)
        self.app = FastAPI()
        self.app.include_router(self.core.router)
        self.client = TestClient(self.app)
        self.owner = Keypair()
        self.agent = Keypair()
        self.worker = Keypair()
        self.headers = {'X-Aperture-Worker-Token': TOKEN, 'X-Aperture-Worker-Id': 'test-worker'}
        self.store.put('workers', 'test-worker', {'worker_pubkey': str(self.worker.pubkey())})
        self.price_patch = patch('ai_engine.get_sol_price_from_pyth', return_value=185.0)
        self.price_patch.start()

    def tearDown(self):
        self.price_patch.stop()
        self.client.close()
        self.store.close()

    def quote(self, owner=None, agent=None, code="print(6 * 7)", budget=100_000, runtime=10):
        return self.client.post('/quotes', json={'wallet': str((owner or self.owner).pubkey()), 'agent_pubkey': str((agent or owner or self.owner).pubkey()), 'code': code, 'max_cost_lamports': budget, 'max_runtime_seconds': runtime})

    def signed_run(self, quote, signer=None, code="print(6 * 7)"):
        return {'quote_id': quote['quote_id'], 'wallet': quote['wallet'], 'agent_pubkey': quote['agent_pubkey'], 'code': code, 'message': quote['message'], 'signature': list(bytes((signer or self.owner).sign_message(quote['message'].encode())))}

    def admit(self, **kwargs):
        quote = self.quote(**kwargs)
        self.assertEqual(quote.status_code, 200, quote.text)
        signer = kwargs.get('agent') or kwargs.get('owner') or self.owner
        response = self.client.post('/execute', json=self.signed_run(quote.json(), signer, kwargs.get('code', "print(6 * 7)")))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def claim(self):
        response = self.client.get('/get_task', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def result(self, task, output='42\n', duration=0.1, exit_code=0):
        payload = {'task_id': task['task_id'], 'lease_id': task['lease_id'], 'source_hash': task['source_hash'], 'output_hash': sha256_text(output), 'output': output, 'full_log': output, 'execution_time': duration, 'exit_code': exit_code, 'execution_mode': 'docker', 'worker_pubkey': str(self.worker.pubkey())}
        receipt = {'domain': 'aperture.worker.result.v1', 'task_id': task['task_id'], 'lease_id': task['lease_id'], 'source_hash': task['source_hash'], 'output_hash': sha256_text(output), 'execution_mode': 'docker', 'execution_time_ms': round(duration * 1000), 'exit_code': exit_code, 'worker_id': 'test-worker', 'worker_pubkey': str(self.worker.pubkey()), 'agent_pubkey': task['agent_pubkey'], 'quote_id': task['quote_id']}
        payload.update(worker_receipt=receipt, worker_signature=base58.b58encode(bytes(self.worker.sign_message(receipt_bytes(receipt)))).decode())
        return payload

    def passport(self, action='register', **kwargs):
        request = {'action': action, 'owner': str(self.owner.pubkey()), 'agent_pubkey': str(self.agent.pubkey()), 'name': 'Budgeted research agent', 'max_cost_lamports': 100_000, 'max_runtime_seconds': 10, 'total_budget_lamports': 200_000, 'expires_at': int(time.time()) + 3600, 'capabilities': ['python.execute'], **kwargs}
        challenge = self.client.post('/agents/challenge', json=request)
        self.assertEqual(challenge.status_code, 200, challenge.text)
        body = challenge.json()
        auth = {'nonce': body['nonce'], 'message': body['message'], 'signature': list(bytes(self.owner.sign_message(body['message'].encode())))}
        response = self.client.post('/agents', json=auth)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), auth

    def test_quote_signature_binds_all_budget_and_domain_fields(self):
        quote = self.quote().json()
        bound = json.loads(quote['message'].split('\n')[-1])
        for field in ('wallet', 'agent_pubkey', 'code_sha256', 'rate_lamports', 'max_cost_lamports', 'max_runtime_seconds', 'expires_at', 'program_id', 'network', 'gateway_pubkey', 'treasury'):
            self.assertEqual(bound[field], quote[field])

    def test_exact_replay_returns_original_job_without_second_dispatch(self):
        quote = self.quote().json()
        payload = self.signed_run(quote)
        first = self.client.post('/execute', json=payload).json()
        second = self.client.post('/execute', json=payload).json()
        self.assertEqual(first['task_id'], second['task_id'])
        self.assertEqual(first['task_access_token'], second['task_access_token'])
        self.assertEqual(len(self.store.list('jobs')), 1)

    def test_source_tamper_and_unrelated_wallet_signature_rejected(self):
        quote = self.quote().json()
        payload = self.signed_run(quote, self.agent)
        self.assertEqual(self.client.post('/execute', json=payload).status_code, 401)
        payload = self.signed_run(quote)
        payload['code'] = 'print(1)'
        self.assertEqual(self.client.post('/execute', json=payload).status_code, 401)

    def test_quote_bound_budget_tamper_rejected(self):
        quote = self.quote().json()
        payload = self.signed_run(quote)
        payload['message'] = quote['message'].replace('100000', '200000')
        self.assertEqual(self.client.post('/execute', json=payload).status_code, 401)

    def test_expired_quote_rejects_new_execution(self):
        quote = self.quote().json()
        self.store.put('quotes', quote['quote_id'], {**quote, 'expires_at': int(time.time()) - 1})
        self.assertEqual(self.client.post('/execute', json=self.signed_run(quote)).status_code, 401)

    def test_legacy_unbounded_execution_body_is_rejected(self):
        self.assertEqual(self.client.post('/execute', json={'wallet': str(self.owner.pubkey()), 'code': 'print(1)', 'signature': [0] * 64, 'message': 'execute'}).status_code, 422)

    def test_source_policy_blocks_host_access_before_quote(self):
        self.assertEqual(self.quote(code="import os\nos.system('id')").status_code, 403)

    def test_budget_covers_minimum_and_runtime_is_effectively_capped(self):
        self.assertEqual(self.quote(budget=1).status_code, 422)
        quote = self.quote(budget=1000, runtime=180).json()
        self.assertLessEqual(quote['effective_runtime_seconds'] * quote['rate_lamports'], quote['max_cost_lamports'])

    def test_worker_result_cannot_exceed_budgeted_runtime(self):
        reference = self.quote(runtime=10).json()
        quote = self.quote(budget=reference['rate_lamports'], runtime=10).json()
        self.assertEqual(quote['effective_runtime_seconds'], 1)
        admitted = self.client.post('/execute', json=self.signed_run(quote))
        self.assertEqual(admitted.status_code, 200, admitted.text)
        task = self.claim()
        response = self.client.post('/submit_result', headers=self.headers,
                                    json=self.result(task, duration=1.01))
        self.assertEqual(response.status_code, 422)

    def test_payment_channel_cannot_admit_parallel_tasks(self):
        self.admit()
        second = self.quote().json()
        self.assertEqual(self.client.post('/execute', json=self.signed_run(second)).status_code, 409)

    def test_owner_passport_authorization_cannot_be_replayed(self):
        passport, auth = self.passport()
        self.assertEqual(passport['attestation'], 'OWNER_SIGNED_OFF_CHAIN')
        self.assertEqual(self.client.post('/agents', json=auth).status_code, 409)

    def test_owner_cannot_overwrite_another_owners_passport(self):
        self.passport()
        request = {'action': 'register', 'owner': str(Keypair().pubkey()), 'agent_pubkey': str(self.agent.pubkey()), 'expires_at': int(time.time()) + 100}
        self.assertEqual(self.client.post('/agents/challenge', json=request).status_code, 403)

    def test_delegated_agent_requires_passport_and_signs_own_job(self):
        self.assertEqual(self.quote(agent=self.agent).status_code, 403)
        self.passport()
        self.admit(agent=self.agent)

    def test_capability_and_spend_limits_are_enforced(self):
        self.passport()
        self.assertEqual(self.quote(agent=self.agent, budget=100001).status_code, 403)
        self.assertEqual(self.quote(agent=self.agent, runtime=11).status_code, 403)
        request = {'action': 'register', 'owner': str(self.owner.pubkey()), 'agent_pubkey': str(Keypair().pubkey()), 'expires_at': int(time.time()) + 100, 'capabilities': ['network.execute']}
        self.assertEqual(self.client.post('/agents/challenge', json=request).status_code, 422)

    def test_agent_expiry_is_checked_after_quote_before_admission(self):
        self.passport()
        quote = self.quote(agent=self.agent).json()
        passport = self.store.get('agents', str(self.agent.pubkey()))
        self.store.put('agents', str(self.agent.pubkey()), {**passport, 'expires_at': int(time.time()) - 1})
        self.assertEqual(self.client.post('/execute', json=self.signed_run(quote, self.agent)).status_code, 403)

    def test_revocation_cancels_active_job_with_elapsed_duration(self):
        self.passport()
        admitted = self.admit(agent=self.agent)
        self.claim()
        job = self.store.get('jobs', admitted['task_id'])
        job['started_at'] = time.time() - 2
        self.store.save_job(job)
        self.passport(action='revoke')
        job = self.store.get('jobs', admitted['task_id'])
        self.assertTrue(job['cancelled'])
        self.assertEqual(job['state'], 'completed')
        self.assertEqual(job['receipt']['execution_status'], 'cancelled')
        self.assertGreater(job['receipt']['execution_time'], 0.5)
        self.assertLessEqual(job['receipt']['execution_time'], job['effective_runtime_seconds'])
        self.assertEqual(self.quote(agent=self.agent).status_code, 403)

    def test_policy_changes_invalidate_outstanding_quotes(self):
        self.passport()
        quote = self.quote(agent=self.agent).json()
        self.passport(action='update', max_cost_lamports=90000)
        self.assertEqual(self.client.post('/execute', json=self.signed_run(quote, self.agent)).status_code, 403)

    def test_agent_lifetime_budget_checks_actual_spend(self):
        self.passport(total_budget_lamports=100000)
        passport = self.store.get('agents', str(self.agent.pubkey()))
        quote = self.quote(agent=self.agent).json()
        run = self.client.post('/execute', json=self.signed_run(quote, self.agent)).json()
        task = self.claim()
        self.core.demo_mode = False
        self.assertEqual(self.client.post('/submit_result', headers=self.headers, json=self.result(task)).status_code, 200)
        self.core.demo_mode = True
        self.assertEqual(self.quote(agent=self.agent, budget=100000).status_code, 403)
        self.assertEqual(self.quote(agent=self.agent, budget=99000).status_code, 200)

    def test_live_channel_effective_balance_must_cover_maximum(self):
        self.core.demo_mode = False
        quote = self.quote().json()
        self.chain.get_channel_state.return_value = {'balance_lamports': 1000000, 'effective_balance_lamports': 1, 'burn_rate_lamports': 0}
        self.assertEqual(self.client.post('/execute', json=self.signed_run(quote)).status_code, 409)

    def test_live_delegation_requires_matching_onchain_policy(self):
        passport, _ = self.passport()
        self.core.demo_mode = False
        self.assertEqual(self.quote(agent=self.agent).status_code, 403)
        self.chain.get_agent_passport.return_value = {'owner': passport['owner'], 'revoked': False, 'valid_until': passport['expires_at'], 'metadata_hash': passport['metadata_hash'], 'max_cost_lamports': passport['max_cost_lamports'], 'max_runtime_seconds': passport['max_runtime_seconds'], 'spent_lamports': 0, 'reserved_lamports': 0, 'total_budget_lamports': passport['total_budget_lamports']}
        self.assertEqual(self.quote(agent=self.agent).status_code, 200)

    def test_worker_requires_auth_and_stable_registration_before_claim(self):
        self.assertEqual(self.client.get('/get_task').status_code, 401)
        headers = {**self.headers, 'X-Aperture-Worker-Id': 'unregistered'}
        self.assertEqual(self.client.get('/get_task', headers=headers).status_code, 409)

    def test_only_leasing_worker_can_send_results(self):
        self.admit()
        task = self.claim()
        headers = {**self.headers, 'X-Aperture-Worker-Id': 'worker-other'}
        self.assertEqual(self.client.post('/submit_result', headers=headers, json=self.result(task)).status_code, 404)

    def test_result_checks_hash_signature_and_lease(self):
        self.admit()
        task = self.claim()
        payload = self.result(task)
        payload['lease_id'] = 'stale'
        self.assertEqual(self.client.post('/submit_result', headers=self.headers, json=payload).status_code, 409)
        payload = self.result(task)
        payload['output_hash'] = '00' * 32
        self.assertEqual(self.client.post('/submit_result', headers=self.headers, json=payload).status_code, 422)
        payload = self.result(task)
        payload['worker_signature'] = base58.b58encode(bytes(64)).decode()
        self.assertEqual(self.client.post('/submit_result', headers=self.headers, json=payload).status_code, 401)

    def test_result_is_durable_before_settlement_and_reconciles_without_worker(self):
        self.core.demo_mode = False
        admitted = self.admit()
        job = self.store.get('jobs', admitted['task_id'])
        started_at = int(time.time())
        self.chain.get_task_receipt.return_value = {
            'settled': False,
            'owner': job['wallet'],
            'agent_pubkey': job['agent_pubkey'],
            'source_hash': job['code_sha256'],
            'rate_lamports': job['rate_lamports'],
            'max_cost_lamports': job['max_cost_lamports'],
            'started_at': started_at,
            'deadline': started_at + job['effective_runtime_seconds'],
        }
        task = self.claim()
        self.chain.stop_task.return_value = None
        response = self.client.post('/submit_result', headers=self.headers, json=self.result(task))
        self.assertEqual(response.status_code, 202)
        job = self.store.get('jobs', task['task_id'])
        self.assertEqual(job['result']['output'], '42\n')
        self.assertEqual(job['state'], 'settlement_pending')
        job['next_settlement_attempt'] = 0
        self.store.save_job(job)
        self.chain.stop_task.return_value = {'signature': 'retry-confirmed', 'charged_lamports': 1000, 'evidence': 'confirmed_task_receipt'}
        asyncio.run(self.core.recover_once())
        self.assertEqual(self.store.get('jobs', task['task_id'])['state'], 'completed')

    def test_canonical_receipt_is_signed_and_worker_attestation_retained(self):
        admitted = self.admit()
        task = self.claim()
        response = self.client.post('/submit_result', headers=self.headers, json=self.result(task))
        receipt = response.json()
        self.assertEqual(receipt['source_hash'], sha256_text(task['code']))
        self.assertEqual(receipt['output_hash'], sha256_text('42\n'))
        VerifyKey(base58.b58decode(receipt['gateway_pubkey'])).verify(receipt['signed_message'].encode(), bytes(receipt['gateway_signature']))
        signed_fields = json.loads(receipt['signed_message'].split('\n', 1)[1])
        for key, value in signed_fields.items():
            self.assertEqual(receipt[key], value)
        self.assertEqual(receipt['settlement_type'], 'OFF_CHAIN')
        self.assertIsNone(receipt['charged_lamports'])
        self.assertIn('worker_signature', receipt)

    def test_result_duplicates_are_idempotent_and_different_result_rejected(self):
        self.admit()
        task = self.claim()
        payload = self.result(task)
        first = self.client.post('/submit_result', headers=self.headers, json=payload).json()
        second = self.client.post('/submit_result', headers=self.headers, json=payload).json()
        self.assertEqual(first['receipt_sha256'], second['receipt_sha256'])
        self.assertEqual(self.client.post('/submit_result', headers=self.headers, json=self.result(task, output='other')).status_code, 409)

    def test_private_results_require_capability(self):
        admitted = self.admit()
        for route in ('result', 'stream_log', 'download', 'receipt'):
            self.assertEqual(self.client.get(f"/{route}/{admitted['task_id']}").status_code, 404)
            self.assertEqual(self.client.get(f"/{route}/{admitted['task_id']}?access_token=wrong").status_code, 404)
        self.assertEqual(self.client.get(f"/result/{admitted['task_id']}?access_token={admitted['task_access_token']}").status_code, 404)
        self.assertEqual(self.client.get(f"/result/{admitted['task_id']}", headers={'X-Aperture-Task-Token': 'wrong'}).status_code, 404)
        self.assertEqual(self.client.get(f"/result/{admitted['task_id']}", headers={'X-Aperture-Task-Token': admitted['task_access_token']}).status_code, 200)

    def test_independent_deadline_recovery_does_not_reexecute(self):
        self.admit()
        task = self.claim()
        job = self.store.get('jobs', task['task_id'])
        job['deadline_unix'] = time.time() - 1
        self.store.save_job(job)
        asyncio.run(self.core.recover_once())
        self.assertEqual(self.store.get('jobs', task['task_id'])['receipt']['execution_status'], 'failed')
        self.assertIsNone(self.claim()['task_id'])

    def test_cancelled_worker_outbox_receives_terminal_ack(self):
        admitted = self.admit()
        task = self.claim()
        job = self.store.get('jobs', task['task_id'])
        job['started_at'] = time.time() - 2
        self.store.save_job(job)
        self.client.post(f"/stop/{task['task_id']}", headers={'X-Aperture-Task-Token': admitted['task_access_token']})
        result = self.client.post('/submit_result', headers=self.headers, json=self.result(task))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['execution_status'], 'cancelled')
        self.assertGreater(result.json()['execution_time'], 0.5)
        self.assertLessEqual(result.json()['execution_time'], job['effective_runtime_seconds'])

    def test_start_intent_is_persisted_before_broadcast(self):
        self.core.demo_mode = False
        self.admit()
        async def send(prepared):
            job = self.store.list('jobs')[0]
            self.assertEqual(job['state'], 'starting')
            self.assertEqual(job['prepared_start'], prepared)
            return 'start-confirmed'
        self.chain.send_prepared_start.side_effect = send
        self.claim()

    def test_restart_fails_closed_without_duplicate_execution(self):
        self.admit()
        task = self.claim()
        asyncio.run(self.core.recover_once(restart=True))
        self.assertEqual(self.store.get('jobs', task['task_id'])['state'], 'completed')
        self.assertTrue(self.store.get('jobs', task['task_id'])['cancelled'])
        self.assertIsNone(self.claim()['task_id'])

    def test_restart_recovers_starting_job_without_started_at(self):
        admitted = self.admit()
        job = self.store.get('jobs', admitted['task_id'])
        job.update(state='starting', started_at=None, deadline_unix=None,
                   start_intent=True, prepared_start={'transaction': 'prepared'})
        self.store.save_job(job)

        asyncio.run(self.core.recover_once(restart=True))

        recovered = self.store.get('jobs', admitted['task_id'])
        self.assertEqual(recovered['state'], 'completed')
        self.assertEqual(recovered['receipt']['execution_status'], 'failed')
        self.assertEqual(recovered['receipt']['execution_time'], 0)

class DurableStoreTests(unittest.TestCase):
    def test_reopen_preserves_receipt_nonce_and_wallet_reservation(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'gateway.sqlite3'
            store = StateStore(path)
            store.put('quotes', 'quote', {'quote_id': 'quote'})
            store.admit('quote', {'task_id': 'task', 'wallet': 'owner', 'state': 'running', 'receipt': {'source_hash': 'source'}}, 10)
            store.close()
            restored = StateStore(path)
            self.assertEqual(restored.get('jobs', 'task')['receipt']['source_hash'], 'source')
            with self.assertRaises(ValueError):
                restored.admit('quote', {'task_id': 'other', 'wallet': 'owner', 'state': 'queued'}, 10)
            restored.close()

if __name__ == '__main__':
    unittest.main()
