"""Consumer/executor integration: pinned work, drain, durable earnings and privacy."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import base58
from fastapi import FastAPI
from fastapi.testclient import TestClient
from solders.keypair import Keypair

from agent_identity import sha256_text, quote_message
from gateway import Gateway
from state_store import StateStore
from test_api_security import FakeSolana
from worker_identity import receipt_bytes


class WorkerMarketTests(unittest.TestCase):
    def setUp(self):
        self.store = StateStore(':memory:')
        self.keys = {name: Keypair() for name in ('worker-a', 'worker-b')}
        self.tokens = {name: 'operator-' + name + '-credential-12345678901234567890' for name in self.keys}
        self.core = Gateway(FakeSolana(), True, '', self.store, worker_credentials=self.tokens)
        app = FastAPI()
        app.include_router(self.core.router)
        self.client = TestClient(app)
        self.owner = Keypair()
        self.source = 'print(6 * 7)'
        for name, key in self.keys.items():
            self.store.put('workers', name, {'node_id': name, 'worker_pubkey': str(key.pubkey()),
                'runtimes': ['python'], 'last_seen': time.time(), 'gpu_name': 'CPU worker',
                'source_policy': 'gateway_ast', 'execution_mode': 'docker'})

    def tearDown(self):
        self.client.close()
        self.store.close()

    def headers(self, name='worker-a'):
        return {'X-Aperture-Worker-Id': name, 'X-Aperture-Worker-Token': self.tokens[name]}

    def target(self, name='worker-a'):
        return {'node_id': name, 'worker_pubkey': str(self.keys[name].pubkey())}

    def quote(self, target=True):
        return self.client.post('/quotes', json={'wallet': str(self.owner.pubkey()),
            'code': self.source, 'max_cost_lamports': 100_000, 'max_runtime_seconds': 10,
            **({'worker_target': self.target()} if target else {})})

    def admission(self, quote):
        return {'wallet': str(self.owner.pubkey()), 'code': self.source, 'quote_id': quote['quote_id'],
                'message': quote['message'], 'signature': list(bytes(self.owner.sign_message(quote['message'].encode())))}

    def mode(self, accepting):
        return self.client.post('/workers/me/mode', json={'accepting_tasks': accepting}, headers=self.headers())

    def complete(self, task):
        attestation = {'domain': 'aperture.worker.result.v1', 'task_id': task['task_id'],
            'lease_id': task['lease_id'], 'source_hash': task['source_hash'], 'output_hash': sha256_text('42\n'),
            'execution_mode': 'docker', 'execution_time_ms': 100, 'exit_code': 0, 'worker_id': 'worker-a',
            'worker_pubkey': str(self.keys['worker-a'].pubkey()), 'agent_pubkey': task['agent_pubkey'], 'quote_id': task['quote_id']}
        response = self.client.post('/submit_result', headers=self.headers(), json={
            'task_id': task['task_id'], 'lease_id': task['lease_id'], 'source_hash': task['source_hash'],
            'output_hash': sha256_text('42\n'), 'output': '42\n', 'full_log': '42\n',
            'execution_time': .1, 'exit_code': 0, 'execution_mode': 'docker',
            'worker_pubkey': str(self.keys['worker-a'].pubkey()), 'worker_receipt': attestation,
            'worker_signature': base58.b58encode(bytes(self.keys['worker-a'].sign_message(receipt_bytes(attestation)))).decode()})
        self.assertEqual(response.status_code, 200, response.text)

    def test_selected_worker_end_to_end_and_operator_history(self):
        response = self.quote()
        self.assertEqual(response.status_code, 200, response.text)
        quote = response.json()
        self.assertTrue(quote['message'].startswith('Aperture execution authorization v5\n'))
        self.assertEqual(json.loads(quote['message'].split('\n')[-1])['worker_target'], self.target())
        response = self.client.post('/execute', json=self.admission(quote))
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        self.assertIsNone(self.client.get('/get_task', headers=self.headers('worker-b')).json()['task_id'])
        claimed = self.client.get('/get_task', headers=self.headers()).json()
        self.assertEqual(claimed['task_id'], task['task_id'])
        self.complete(claimed)
        receipt = self.store.get('jobs', task['task_id'])['receipt']
        self.assertEqual(receipt['worker_target'], self.target())
        self.assertEqual(receipt['worker_id'], 'worker-a')
        view = self.client.get('/workers/me', headers=self.headers()).json()
        self.assertEqual(view['totals']['tasks_completed'], 1)
        self.assertEqual(view['totals']['paid_lamports'], 0)
        self.assertEqual(view['totals']['off_chain_tasks'], 1)
        self.assertEqual(view['recent_tasks'][0]['task_id'], task['task_id'])
        self.assertNotIn(self.source, json.dumps(view))
        public = json.dumps(self.client.get('/workers').json())
        for private in (self.source, task['task_access_token'], str(self.owner.pubkey()), self.tokens['worker-a'], task['task_id']):
            self.assertNotIn(private, public)

    def test_worker_pin_cannot_be_changed_and_offline_or_incompatible_nodes_fail_closed(self):
        quote = self.quote().json()
        altered = {**quote, 'worker_target': self.target('worker-b')}
        altered['message'] = quote_message(altered)
        self.assertEqual(self.client.post('/execute', json=self.admission(altered)).status_code, 401)
        node = self.store.get('workers', 'worker-a')
        for change in ({'last_seen': time.time() - 60}, {'runtimes': ['inference.chat']},
                       {'worker_pubkey': str(Keypair().pubkey())}):
            with self.subTest(change=change):
                self.store.put('workers', 'worker-a', {**node, **change})
                self.assertEqual(self.quote().status_code, 409)
                self.assertEqual(self.client.post('/execute', json=self.admission(quote)).status_code, 409)
        self.store.put('workers', 'worker-a', node)

    def test_drain_finishes_existing_lease_blocks_new_claims_and_resume_restores_them(self):
        quote = self.quote().json()
        admission = self.client.post('/execute', json=self.admission(quote))
        self.assertEqual(admission.status_code, 200, admission.text)
        task = self.client.get('/get_task', headers=self.headers()).json()
        self.assertEqual(self.mode(False).status_code, 200)
        # Ambiguous admission/claim retries recover the same work even while draining.
        self.assertEqual(self.client.post('/execute', json=self.admission(quote)).json()['task_id'], task['task_id'])
        self.assertEqual(self.client.get('/get_task', headers=self.headers()).json()['lease_id'], task['lease_id'])
        self.complete(task)
        self.assertEqual(self.quote().status_code, 409)
        auto_quote = self.quote(target=False).json()
        self.assertEqual(self.client.post('/execute', json=self.admission(auto_quote)).status_code, 200)
        self.assertIsNone(self.client.get('/get_task', headers=self.headers()).json()['task_id'])
        self.assertEqual(self.mode(True).status_code, 200)
        self.assertIsNotNone(self.client.get('/get_task', headers=self.headers()).json()['task_id'])

    def test_drain_between_quote_and_admission_rejects_without_creating_work(self):
        quote = self.quote().json()
        self.mode(False)
        response = self.client.post('/execute', json=self.admission(quote))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.store.list_active_jobs(), [])

    def test_operator_credentials_are_scoped_and_mode_is_strict(self):
        self.assertEqual(self.client.get('/workers/me').status_code, 401)
        self.assertEqual(self.client.get('/workers/me', headers={**self.headers(), 'X-Aperture-Worker-Id': 'worker-b'}).status_code, 401)
        self.assertEqual(self.client.post('/workers/me/mode', headers=self.headers(), json={'accepting_tasks': 'false'}).status_code, 422)
        self.assertTrue(self.store.get('workers', 'worker-a').get('accepting_tasks', True))

    def test_worker_totals_are_exactly_once_survive_pruning_and_database_restart(self):
        root = Path(__file__).parents[1] / '.aperture' / 'test-temp'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            path = Path(folder) / 'state.db'
            store = StateStore(path)
            owner = str(self.owner.pubkey())
            worker = str(self.keys['worker-a'].pubkey())
            with patch.dict(os.environ, {'APERTURE_MAX_COMPLETED_TASKS': '1'}):
                for index in range(3):
                    job = {'task_id': f'task-{index}', 'quote_id': f'quote-{index}', 'wallet': owner,
                        'agent_pubkey': owner, 'worker_id': 'worker-a', 'worker_pubkey': worker,
                        'state': 'completed', 'max_cost_lamports': 1000, 'rate_lamports': 100,
                        'receipt': {'execution_status': 'completed', 'execution_time': 1.5,
                            'settlement_type': 'DEVNET', 'charged_lamports': 150,
                            'worker_paid_lamports': 150, 'payout_destination': worker}}
                    store.save_job(job)
                    store.save_job(job)
                self.assertEqual(store.count_completed_jobs(), 1)
                self.assertEqual(store.worker_totals('worker-a')['paid_lamports'], 450)
                store.close()
                store = StateStore(path)
                self.assertEqual(store.worker_totals('worker-a')['tasks_completed'], 3)
                self.assertEqual(store.worker_totals('worker-a')['paid_lamports'], 450)
                store.close()


if __name__ == '__main__':
    unittest.main()
