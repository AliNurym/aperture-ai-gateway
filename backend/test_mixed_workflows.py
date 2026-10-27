"""Mixed-plan owner approval, exact context files and rejection regressions."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_api_security as fixtures
from artifact_store import ArtifactStore
from inference import ChatRequest, Provider, request_code, request_parameters
from test_owner_workspace import BytesRequest
from workflow_inbox import validate_plan
from workflow_steps import resolve_step


class MixedPlanTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GatewayApiSecurityTests(); self.fixture.setUp()
        self.core = self.fixture.core
        self.temp = tempfile.TemporaryDirectory()
        self.core._objects = ArtifactStore(self.temp.name)
        self.owner = str(self.fixture.owner.pubkey())
        self.provider = Provider(id='fixture', name='Fixture', model='fixture', base_url='http://127.0.0.1:1/v1', rate_lamports_sec=1000)
        self.core.inference_providers = {'fixture': self.provider}
        self.parameters = request_parameters(ChatRequest(provider_id='fixture', messages=[{'role': 'user', 'content': 'Explain the result.'}]), self.provider)
        self.plan = {'version': 1, 'max_cost_lamports': 200000, 'steps': [
            {'id': 'compute', 'source': 'print(42)', 'inputs': [], 'parameters': {}, 'max_cost_lamports': 100000, 'max_runtime_seconds': 30},
            {'id': 'explain', 'source': request_code(self.parameters), 'inputs': [], 'parameters': self.parameters,
             'message_inputs': [{'from_step': 'compute', 'artifact': 'result.txt', 'message_index': 0}],
             'max_cost_lamports': 100000, 'max_runtime_seconds': 30},
        ]}

    def tearDown(self):
        self.core._objects.close(); self.fixture.tearDown(); self.temp.cleanup()

    def validate(self, plan=None):
        return validate_plan(self.core, plan or self.plan, self.owner, self.owner)

    def test_mixed_plan_accepts_explicit_bounds_and_rejects_budget_or_source_changes(self):
        self.validate()
        plan = copy.deepcopy(self.plan); plan['max_cost_lamports'] = 100000
        with self.assertRaises(ValueError): self.validate(plan)
        plan = copy.deepcopy(self.plan); plan['steps'][1]['parameters']['inference']['messages'][0]['content'] = 'Changed'
        with self.assertRaises(ValueError): self.validate(plan)

    def test_missing_provider_unknown_context_and_cycles_are_rejected(self):
        for parent in ('missing', 'explain'):
            plan = copy.deepcopy(self.plan); plan['steps'][1]['message_inputs'][0]['from_step'] = parent
            with self.subTest(parent=parent), self.assertRaises(ValueError): self.validate(plan)
        self.core.inference_providers = {}
        with self.assertRaises(ValueError): self.validate()

    def test_context_cannot_write_system_messages_or_be_attached_to_python(self):
        plan = copy.deepcopy(self.plan); plan['steps'][1]['parameters']['inference']['messages'][0]['role'] = 'system'
        plan['steps'][1]['source'] = request_code(plan['steps'][1]['parameters'])
        with self.assertRaises(ValueError): self.validate(plan)
        plan = copy.deepcopy(self.plan); plan['steps'][0]['message_inputs'] = plan['steps'][1]['message_inputs']
        with self.assertRaises(ValueError): self.validate(plan)

    def test_context_is_resolved_from_exact_owned_result_bytes(self):
        data = 'Қазақстан · 42'.encode()
        auth = self.core.objects.authorize(owner=self.owner, agent=self.owner, name='result.txt', digest=hashlib.sha256(data).hexdigest(), size=len(data), task_id='parent')
        item = asyncio.run(self.core.objects.upload(auth['object_id'], auth['upload_token'], BytesRequest(data)))
        self.core.store.save_job({'task_id': 'parent', 'wallet': self.owner, 'state': 'completed',
                                 'receipt': {'execution_status': 'completed', 'artifacts': [item]}})
        flow = {'owner': self.owner, 'agent_pubkey': self.owner, 'tasks': {'compute': 'parent'}}
        source, parameters = resolve_step(self.core, flow, self.plan['steps'][1])
        self.assertIn('[Aperture input compute/result.txt]\nҚазақстан · 42', parameters['inference']['messages'][0]['content'])
        self.assertEqual(source, request_code(parameters))
        self.assertEqual(self.parameters['inference']['messages'][0]['content'], 'Explain the result.')
        self.core.objects.resolve(item, owner=self.owner, agent=self.owner).write_bytes(b'x' * len(data))
        with self.assertRaises(ValueError): resolve_step(self.core, flow, self.plan['steps'][1])
