"""Source-review links use controlled retained-task fixtures, not a live model."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_api_security as fixtures
from agent_identity import sha256_text
from sentinel_review import PROMPT_PREFIX


class SentinelReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GatewayApiSecurityTests()
        self.fixture.setUp()
        self.owner = str(self.fixture.owner.pubkey())
        self.source = 'print(6 * 7)'
        self.task_id = 'task-' + 'a' * 32
        self.reference = {'task_id': self.task_id, 'source_sha256': sha256_text(self.source), 'receipt_sha256': 'b' * 64}
        self.review = {'task_id': self.task_id, 'wallet': self.owner, 'state': 'completed',
            'created_at': 1, 'receipt': {'execution_status': 'completed', 'receipt_sha256': 'b' * 64},
            'workload': {'runtime': 'inference.chat', 'parameters': {
                'offer': {'protocol': 'gemini_generate_content'},
                'inference': {'messages': [{'role': 'user', 'content': PROMPT_PREFIX + json.dumps(self.source)}]}}}}
        self.retain()

    def tearDown(self):
        self.fixture.tearDown()

    def retain(self):
        self.fixture.store.save_job(self.review)

    def quote(self, **changes):
        body = {'wallet': self.owner, 'code': self.source, 'max_cost_lamports': 100000,
                'max_runtime_seconds': 10, 'job_version': 1, 'parameters': {'aperture_review': self.reference}}
        return self.fixture.client.post('/quotes', json={**body, **changes})

    def test_matching_review_is_bound_into_quote_and_signed_admission(self):
        response = self.quote()
        self.assertEqual(response.status_code, 200, response.text)
        quote = response.json()
        self.assertEqual(quote['workload']['parameters']['aperture_review'], self.reference)
        self.assertEqual(quote['workload_sha256'], sha256_text(quote['workload_canonical']))
        body = self.fixture.signed_run(quote)
        body.update(job_version=1, inputs=[], parameters=quote['workload']['parameters'])
        response = self.fixture.client.post('/execute', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        admitted = self.fixture.store.get('jobs', response.json()['task_id'])
        self.assertEqual(admitted['workload']['parameters']['aperture_review'], self.reference)

    def test_other_owner_or_source_cannot_reuse_review(self):
        for changes in [{'wallet': str(self.fixture.agent.pubkey())}, {'code': 'print(7 * 7)'}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.quote(**changes).status_code, 409)

    def test_pending_failed_non_gemini_and_changed_receipts_are_rejected(self):
        original = copy.deepcopy(self.review)
        for change in ('pending', 'failed', 'protocol', 'receipt', 'prompt'):
            with self.subTest(change=change):
                self.review = copy.deepcopy(original)
                if change == 'pending': self.review['state'] = 'running'
                elif change == 'failed': self.review['receipt']['execution_status'] = 'failed'
                elif change == 'protocol': self.review['workload']['parameters']['offer']['protocol'] = 'openai_chat'
                elif change == 'receipt': self.review['receipt']['receipt_sha256'] = 'c' * 64
                else: self.review['workload']['parameters']['inference']['messages'][0]['content'] += '\nAdditional instructions'
                self.retain()
                self.assertEqual(self.quote().status_code, 409)

    def test_unretained_review_and_malformed_references_are_rejected(self):
        self.reference['task_id'] = 'task-' + 'd' * 32
        self.assertEqual(self.quote().status_code, 409)
        self.reference['receipt_sha256'] = 'invalid'
        self.assertEqual(self.quote().status_code, 422)

    def test_review_cannot_be_substituted_after_signature(self):
        quote = self.quote().json()
        body = self.fixture.signed_run(quote)
        changed = {**self.reference, 'receipt_sha256': 'c' * 64}
        body.update(job_version=1, inputs=[], parameters={'aperture_review': changed})
        self.assertNotEqual(self.fixture.client.post('/execute', json=body).status_code, 200)
