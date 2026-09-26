"""Offline end-to-end flow with real Ed25519 keys and real CPU execution.

No server request or chain transaction is made when this module is imported.
Docker isolation is separately verified by the opt-in worker tests and CI.
"""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import base58
from nacl.signing import VerifyKey

import test_api_security as security
import worker
from worker_identity import WorkerIdentity
from worker_sandbox import TrustedLocalExecutor

class OfflineExecutionIntegrationTests(unittest.TestCase):
    def test_delegated_budgeted_task_runs_and_receipt_verifies(self):
        harness = security.GatewayApiSecurityTests()
        harness.setUp()
        try:
            harness.passport()
            admitted = harness.admit(agent=harness.agent)
            task = harness.claim()
            http = Mock()
            http.get.return_value = Mock(status_code=200, json=lambda: {'cancelled': False})
            http.post.return_value = Mock(status_code=200)
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                identity = WorkerIdentity(root)
                harness.store.put('workers', 'test-worker', {'worker_pubkey': identity.pubkey})
                result = worker.execute_task(task, TrustedLocalExecutor(), root, http)
                signed = identity.attest(task, result, 'test-worker')
                submitted = harness.client.post('/submit_result', headers=harness.headers, json=signed)
            self.assertEqual(submitted.status_code, 200, submitted.text)
            receipt = submitted.json()
            self.assertEqual(result['output'].strip(), '42')
            self.assertEqual(receipt['agent_pubkey'], str(harness.agent.pubkey()))
            self.assertEqual(receipt['execution_mode'], 'trusted_local')
            self.assertEqual(receipt['source_hash'], hashlib.sha256(task['code'].encode()).hexdigest())
            self.assertEqual(receipt['output_hash'], hashlib.sha256(result['full_log'].encode()).hexdigest())
            VerifyKey(base58.b58decode(receipt['gateway_pubkey'])).verify(receipt['signed_message'].encode(), bytes(receipt['gateway_signature']))
            replay = harness.client.post('/submit_result', headers=harness.headers, json=signed)
            self.assertEqual(replay.json()['receipt_sha256'], receipt['receipt_sha256'])
            capability = {'access_token': admitted['task_access_token']}
            self.assertEqual(harness.client.get(f"/result/{task['task_id']}", params=capability).json()['status'], 'completed')
        finally:
            harness.tearDown()

if __name__ == '__main__':
    unittest.main()
