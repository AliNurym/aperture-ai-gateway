"""Model context, worker identity and bounded workflow regression checks."""
import copy
import unittest
from solders.keypair import Keypair
from aperture_client.jobs import inference_source
from aperture_client.workflows import validate_workflow
from aperture_client.workflow_steps import resolve_messages, resolved_source


def plan():
    parameters = {'inference': {'provider_id': 'fixture', 'messages': [{'role': 'user', 'content': 'Explain the result.'}], 'max_tokens': 64},
                  'offer': {'id': 'fixture', 'max_output_tokens': 128}}
    return [{'id': 'compute', 'source': 'print(42)', 'max_cost_lamports': 10000},
            {'id': 'explain', 'source': inference_source(parameters), 'parameters': parameters,
             'message_inputs': [{'from_step': 'compute', 'artifact': 'result.txt', 'message_index': 0}],
             'worker_target': {'node_id': 'model-worker', 'worker_pubkey': str(Keypair().pubkey())}, 'max_cost_lamports': 10000}]


class MixedWorkflowTests(unittest.TestCase):
    def test_context_creates_a_dependency_and_preserves_the_exact_executor(self):
        steps = plan()
        validated = validate_workflow(steps, 20000)['steps']
        self.assertEqual(validated[1]['depends_on'], ['compute'])
        self.assertEqual(validated[1]['worker_target'], steps[1]['worker_target'])
        self.assertNotIn('worker_target', validated[0])

    def test_utf8_context_changes_only_the_resolved_request_and_source(self):
        step = validate_workflow(plan(), 20000)['steps'][1]
        original = copy.deepcopy(step)
        parameters = resolve_messages(step, lambda _: 'Қазақстан · 42'.encode('utf-8'))
        self.assertIn('[Aperture input compute/result.txt]\nҚазақстан · 42', parameters['inference']['messages'][0]['content'])
        self.assertEqual(step, original)
        self.assertNotEqual(resolved_source(step, parameters), step['source'])

    def test_oversized_or_invalid_utf8_files_are_rejected_without_truncation(self):
        step = validate_workflow(plan(), 20000)['steps'][1]
        for data in (b'x' * 16001, b'\xff', b''):
            with self.subTest(data_size=len(data)), self.assertRaises(ValueError):
                resolve_messages(step, lambda _: data)

    def test_context_cannot_target_system_messages_or_create_cycles(self):
        steps = plan(); steps[1]['message_inputs'][0]['from_step'] = 'explain'
        with self.assertRaises(ValueError):
            validate_workflow(steps, 20000)
        steps = plan(); parameters = steps[1]['parameters']; parameters['inference']['messages'][0]['role'] = 'system'
        steps[1]['source'] = inference_source(parameters)
        with self.assertRaises(ValueError):
            validate_workflow(steps, 20000)

    def test_context_does_not_expand_python_or_token_permissions(self):
        steps = plan(); steps[0]['message_inputs'] = steps[1]['message_inputs']
        with self.assertRaises(ValueError):
            validate_workflow(steps, 20000)
        steps = plan(); parameters = steps[1]['parameters']; parameters['inference']['max_tokens'] = 129
        steps[1]['source'] = inference_source(parameters)
        with self.assertRaises(ValueError):
            validate_workflow(steps, 20000)
