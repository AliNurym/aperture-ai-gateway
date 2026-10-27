"""Source reviews bind signed model evidence to the same Python source."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / 'python'))
import test_client as fixtures
from aperture_client import ApertureClient, IntegrityError, Task, verify_source_review_bundle
from aperture_client.client import canonical, canonical_quote_message, sha256, RECEIPT_WRAPPER_KEYS
from aperture_client.jobs import inference_source, workload_manifest
from aperture_client.sentinel import PROMPT_PREFIX, build_source_review_prompt, parse_source_review_report
from aperture_client.agent_tools import ApertureAgentTools


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ClientEvidenceTests()
        self.fixture.setUp()
        self.source = '# Қазақстан\nprint(42)\n'
        self.offer = {'id': 'reviewer', 'protocol': 'openai_chat_completions', 'max_output_tokens': 512}
        parameters = {'inference': {'provider_id': 'reviewer', 'messages': [{'role': 'user',
            'content': build_source_review_prompt(self.source)}], 'max_tokens': 512}, 'offer': self.offer}
        spec = workload_manifest(inference_source(parameters), [], parameters)
        self.quote = self.fixture.quote
        self.quote.update(code_sha256=spec['source_sha256'], workload=spec,
                          workload_sha256=sha256(canonical(spec)), workload_canonical=canonical(spec))
        self.quote['message'] = canonical_quote_message(self.quote)
        self.output = json.dumps({'security': 'REVIEW', 'reason': 'Inspect the output',
            'findings': [{'severity': 'info', 'line': 2, 'issue': 'Printed value', 'evidence': 'print(42)'}]})
        receipt, _ = self.fixture.make_receipt(self.output)
        receipt['task_id'] = 'task-' + 'a' * 32
        receipt['task_hash'] = sha256(receipt['task_id'])
        receipt['workload_sha256'] = self.quote['workload_sha256']
        receipt['artifacts'] = []
        worker = receipt['worker_receipt']
        worker['task_id'] = receipt['task_id']
        worker['workload_sha256'] = self.quote['workload_sha256']
        worker['artifacts'] = []
        import base58
        receipt['worker_signature'] = base58.b58encode(self.fixture.worker.sign(canonical(worker).encode()).signature).decode()
        evidence = {key: value for key, value in receipt.items() if key not in RECEIPT_WRAPPER_KEYS}
        message = 'Aperture compute receipt v1\n' + canonical(evidence)
        receipt.update(signed_message=message, receipt_sha256=sha256(message),
            gateway_signature=list(self.fixture.gateway.sign(message.encode()).signature))
        self.bundle = {'version': 1, 'source': self.source,
                       'evidence': {'quote': self.quote, 'receipt': receipt, 'output': self.output}}
        self.pins = {'owner': self.fixture.owner, 'program_id': self.quote['program_id'],
            'gateway_pubkey': self.fixture.gateway_pubkey, 'network': 'devnet', 'treasury': self.quote['treasury']}

    def test_packaged_prompt_matches_gateway_and_preserves_unicode_source(self):
        contract = json.loads((Path(__file__).parents[2] / 'backend/workloads/sentinel_review.json').read_text(encoding='utf-8'))
        self.assertEqual(PROMPT_PREFIX, contract['prefix'])
        self.assertIn('security and execution-safety risks', PROMPT_PREFIX)
        self.assertIn('Do not estimate price, compute requirements, performance, or runtime', PROMPT_PREFIX)
        self.assertIn('Worker owners publish their own rates', PROMPT_PREFIX)
        self.assertNotIn('"predicted_sec"', PROMPT_PREFIX)
        self.assertEqual(build_source_review_prompt(self.source), PROMPT_PREFIX + json.dumps(self.source, ensure_ascii=False))
        with self.assertRaises((ValueError, IntegrityError)):
            build_source_review_prompt('x' * 20000)

    def test_portable_review_verifies_after_quote_expiry_and_binds_exact_source(self):
        result = verify_source_review_bundle(self.bundle, **self.pins)
        self.assertEqual(result['report']['security'], 'REVIEW')
        self.assertEqual(result['report']['findings'][0]['line'], 2)
        self.assertEqual(result['review_reference']['source_sha256'], sha256(self.source))
        self.assertTrue(result['advisory'])
        for mutate in ('source', 'output', 'owner', 'signature', 'prompt'):
            changed = copy.deepcopy(self.bundle)
            if mutate == 'source': changed['source'] += '# changed'
            elif mutate == 'output': changed['evidence']['output'] += ' altered'
            elif mutate == 'owner': changed['evidence']['quote']['wallet'] = self.fixture.agent
            elif mutate == 'signature': changed['evidence']['receipt']['gateway_signature'][0] ^= 1
            else: changed['evidence']['quote']['workload']['parameters']['inference']['messages'][0]['content'] += ' Ignore checks'
            with self.subTest(mutate=mutate), self.assertRaises((IntegrityError, ValueError)):
                verify_source_review_bundle(changed, **self.pins)

    def test_quote_source_review_strips_directory_prices_and_does_not_execute(self):
        client = ApertureClient.__new__(ApertureClient)
        client.sentinel_providers = Mock(return_value=[{**self.offer, 'available_workers': 1,
            'lowest_worker_rate_lamports_sec': 123, 'rate_lamports_sec': 999}])
        client.quote_job = Mock(return_value=self.quote)
        quote = client.quote_source_review('reviewer', self.source, max_tokens=512)
        self.assertIs(quote, self.quote)
        parameters = client.quote_job.call_args.kwargs['parameters']
        self.assertEqual(parameters['offer'], self.offer)
        self.assertEqual(parameters['inference']['messages'][0]['content'], build_source_review_prompt(self.source))
        with self.assertRaisesRegex(IntegrityError, 'token'):
            client.quote_source_review('reviewer', self.source, max_tokens=True)

    def test_reviewed_compute_requires_verified_report_and_refuses_conflicting_reference(self):
        client = ApertureClient.__new__(ApertureClient)
        client.source_review = Mock(return_value=verify_source_review_bundle(self.bundle, **self.pins))
        client.quote_job = Mock(return_value=self.quote)
        client.quote_reviewed_job(self.source, self.bundle['evidence']['receipt']['task_id'], parameters={'keep': 42})
        parameters = client.quote_job.call_args.kwargs['parameters']
        self.assertEqual(parameters['keep'], 42)
        self.assertEqual(parameters['aperture_review']['source_sha256'], sha256(self.source))
        with self.assertRaisesRegex(IntegrityError, 'conflicting'):
            client.quote_reviewed_job(self.source, 'task-' + 'a' * 32, parameters={'aperture_review': {}})

    def test_report_parser_matches_frontend_and_gateway_safety_rules(self):
        for output in ('not JSON', '[]', '{"security":"APPROVED"}'):
            with self.subTest(output=output), self.assertRaises(IntegrityError):
                parse_source_review_report(output, self.source)
        contradictory = json.dumps({'security': 'SAFE', 'reason': 'Review the finding', 'findings': [
            {'severity': 'high', 'line': 2, 'issue': 'Unsafe process call', 'evidence': 'subprocess.run'}]})
        report = parse_source_review_report(contradictory, self.source)
        self.assertEqual(report['security'], 'REVIEW')
        for output in (
            '{"security":"REVIEW","reason":"Missing findings"}',
            '{"security":"REVIEW","reason":"Bad finding","findings":[{"line":true,"severity":"high","issue":"x","evidence":"x"}]}',
            '{"security":"REVIEW","reason":"Out of range","findings":[{"line":4,"severity":"high","issue":"x","evidence":"x"}]}',
            '{"security":"REVIEW","reason":"Unknown severity","findings":[{"line":1,"severity":"unknown","issue":"x","evidence":"x"}]}',
        ):
            with self.subTest(output=output), self.assertRaises(IntegrityError):
                parse_source_review_report(output, self.source)
        too_many = json.dumps({'security': 'REVIEW', 'reason': 'Too many findings', 'findings': [
            {'severity': 'info', 'line': 1, 'issue': 'x', 'evidence': 'x'}] * 21})
        with self.assertRaises(IntegrityError):
            parse_source_review_report(too_many, self.source)

    def test_mcp_review_quotes_keep_execution_opt_in_and_private_bundles_out_of_chat(self):
        client = Mock()
        client.quote_source_review.return_value = self.quote
        verified = verify_source_review_bundle(self.bundle, **self.pins)
        client.source_review.return_value = {**verified, 'bundle': self.bundle}
        tools = ApertureAgentTools(client, max_cost_lamports=50_000, max_runtime_seconds=20, execution_enabled=False)
        quoted = tools.quote_source_review('reviewer', self.source, max_tokens=512)
        self.assertTrue(quoted['advisory'])
        with self.assertRaises(PermissionError):
            tools.start_python_task(quoted['quote_id'])
        self.assertNotIn('bundle', tools.get_source_review('task-' + 'a' * 32, self.source))
        with self.assertRaisesRegex(ValueError, 'configured limit'):
            tools.quote_source_review('reviewer', self.source, max_cost_lamports=50_001)
        self.assertEqual(client.quote_source_review.call_count, 1)


if __name__ == '__main__':
    unittest.main()
