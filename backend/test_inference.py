"""Inference admission, routing and streamed HTTP adapter regressions.

HTTP fixtures exercise protocol behavior; they are not model-quality evidence.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_api_security as fixtures
from inference import ChatRequest, Provider, is_development_offer, request_code, request_parameters, validate_request
import inference_runner
from inference_executor import InferenceExecutor
from worker import execute_task
from worker_identity import WorkerIdentity
from worker_sandbox import TrustedLocalExecutor
from sentinel_review import PROMPT_PREFIX


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.provider = Provider(id="local", name="Local test server", model="fixture-model",
                                 base_url="http://127.0.0.1:1/v1", rate_lamports_sec=2000)
        self.fixture = fixtures.GatewayApiSecurityTests()
        self.fixture.setUp()
        self.core, self.client = self.fixture.core, self.fixture.client
        self.core.inference_providers = {"local": self.provider}
        worker = self.core.store.get("workers", "test-worker")
        worker.update(node_id="test-worker", last_seen=time.time(), accepting_tasks=True,
                      runtimes=["inference.chat"], inference_offers=[self.provider.offer()], rate_lamports_sec=2000)
        self.core.store.put("workers", "test-worker", worker)
        self.request = {"wallet": str(self.fixture.owner.pubkey()), "provider_id": "local",
                        "messages": [{"role": "user", "content": "Explain a compute budget"}],
                        "max_tokens": 64, "max_cost_lamports": 100000, "max_runtime_seconds": 10}

    def tearDown(self):
        self.fixture.tearDown()
        self.temp.cleanup()

    def quote(self):
        response = self.client.post("/inference/quotes", json=self.request)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def advertise(self, provider, identity=None):
        worker = self.core.store.get("workers", "test-worker")
        worker.update(node_id="test-worker", last_seen=time.time(), accepting_tasks=True,
                      runtimes=["inference.chat"], inference_offers=[provider.offer()], rate_lamports_sec=2000)
        if identity is not None:
            worker["worker_pubkey"] = identity.pubkey
        self.core.store.put("workers", "test-worker", worker)

    def body(self, quote):
        return {**quote["execution_request"], "quote_id": quote["quote_id"], "wallet": quote["wallet"],
                "message": quote["message"], "signature": list(bytes(self.fixture.owner.sign_message(quote["message"].encode())))}

    def execute_claimed(self, task, executor):
        # Control requests must use this test's gateway, even if a real preview
        # happens to be listening on worker.API_URL. Never rely on a fast exit
        # winning the race against the cancellation monitor.
        client, headers = self.client, self.fixture.headers

        class GatewayHttp:
            def get(self, url, **kwargs):
                return client.get(urlsplit(url).path, headers=headers)

            def post(self, url, **kwargs):
                return client.post(urlsplit(url).path, headers=headers, json=kwargs.get('json'))

        with patch('worker.NODE_ID', 'test-worker'):
            return execute_task(task, executor, state_root=self.root, http=GatewayHttp())

    def test_offer_source_and_quote_bind_every_inference_parameter(self):
        quote = self.quote()
        self.assertEqual(quote["rate_lamports"], 2000)
        self.assertEqual(quote["workload"]["runtime"], "inference.chat")
        self.assertEqual(quote["analysis"]["pricing"], "provider_published_worker_rate_v1")
        self.assertEqual(quote["worker_target"]["node_id"], "test-worker")
        self.assertNotIn("rate_lamports_sec", quote["workload"]["parameters"]["offer"])
        self.assertEqual(self.client.get("/inference/providers").json()["providers"][0]["lowest_worker_rate_lamports_sec"], 2000)
        self.assertNotIn("base_url", self.client.get("/inference/providers").text)
        for key, value in (("messages", [{"role": "user", "content": "Changed"}]), ("max_tokens", 65)):
            changed = self.body(quote)
            changed["parameters"]["inference"][key] = value
            self.assertIn(self.client.post("/execute", json=changed).status_code, (401, 422))
        self.assertFalse(self.core.store.list_active_jobs())

    def test_development_model_fixtures_are_hidden_and_cannot_be_quoted(self):
        fixture = Provider(id="aperture-local-fixture", name="Development-only model",
            model="aperture-smollm2-135m", base_url="http://127.0.0.1:8081/v1",
            rate_lamports_sec=1000, development_only=True)
        self.core.inference_providers = {fixture.id: fixture}
        offer = fixture.offer()
        self.assertTrue(is_development_offer(offer))
        self.assertEqual(self.client.get("/inference/providers").json()["providers"], [])
        response = self.client.post("/inference/quotes", json={**self.request, "provider_id": fixture.id})
        self.assertEqual(response.status_code, 404, response.text)

    def test_deepseek_is_only_in_sentinel_catalog_and_accepts_source_bound_review_quote(self):
        provider = Provider(id="aperture-deepseek", name="Aperture DeepSeek", model="deepseek-flash",
            base_url="https://api.deepseek.com", api_key_env="DEEPSEEK_API_KEY", max_output_tokens=512)
        self.core.inference_providers = {provider.id: provider}
        self.advertise(provider)

        public = self.client.get("/inference/providers").json()["providers"]
        sentinel_response = self.client.get("/sentinel/providers")
        self.assertEqual(public, [])
        self.assertEqual(sentinel_response.status_code, 200, sentinel_response.text)
        sentinel = sentinel_response.json()["providers"]
        self.assertEqual([item["id"] for item in sentinel], [provider.id])
        self.assertEqual(sentinel[0]["available_workers"], 1)
        self.assertNotIn("base_url", sentinel_response.text)

        prompt = PROMPT_PREFIX + json.dumps("print(6 * 7)", ensure_ascii=False)
        request = {**self.request, "provider_id": provider.id,
                   "messages": [{"role": "user", "content": prompt}]}
        quote = self.client.post("/inference/quotes", json=request)
        self.assertEqual(quote.status_code, 200, quote.text)
        self.assertEqual(quote.json()["rate_lamports"], 2000)
        self.assertEqual(quote.json()["worker_target"]["node_id"], "test-worker")

        request["messages"] = [{"role": "user", "content": "Review this arbitrary prompt."}]
        rejected = self.client.post("/inference/quotes", json=request)
        self.assertEqual(rejected.status_code, 422, rejected.text)

    def test_smollm_model_id_is_development_only_even_without_metadata(self):
        fixture = Provider(id="operator-model", name="Unmarked fixture",
            model="aperture-smollm2-135m", base_url="http://127.0.0.1:8081/v1",
            rate_lamports_sec=1000)
        self.core.inference_providers = {fixture.id: fixture}
        self.assertTrue(fixture.is_development_only)
        self.assertEqual(self.client.get("/inference/providers").json()["providers"], [])

    def test_cpu_cannot_claim_inference_and_same_signed_retry_is_idempotent(self):
        quote = self.quote()
        body = self.body(quote)
        admitted = self.client.post("/execute", json=body).json()
        worker = self.core.store.get("workers", "test-worker")
        worker["runtimes"] = ["python"]
        self.core.store.put("workers", "test-worker", worker)
        self.assertEqual(self.fixture.claim(), {"task_id": None})
        worker = self.core.store.get("workers", "test-worker")
        worker.update(inference_offers=[self.provider.offer()], runtimes=["inference.chat"])
        self.core.store.put("workers", "test-worker", worker)
        task = self.fixture.claim()
        self.assertEqual(task["task_id"], admitted["task_id"])
        self.assertEqual(self.client.post("/execute", json=body).json()["task_id"], admitted["task_id"])
        self.assertEqual(len(self.core.store.list_active_jobs()), 1)

    def test_quote_rejects_unknown_provider_excess_tokens_and_budget(self):
        for changes, status in (({"provider_id": "missing"}, 404), ({"max_tokens": 513}, 422),
                                ({"max_tokens": True}, 422), ({"max_cost_lamports": 1999}, 422)):
            self.assertEqual(self.client.post("/inference/quotes", json={**self.request, **changes}).status_code, status)

    def test_chosen_model_worker_is_bound_to_quote_dispatch_and_admission_checks(self):
        worker = self.core.store.get('workers', 'test-worker')
        worker.update(node_id='test-worker', last_seen=time.time(), runtimes=['inference.chat'],
                      execution_mode='inference_proxy', inference_offers=[self.provider.offer()])
        self.core.store.put('workers', 'test-worker', worker)
        other = {**worker, 'node_id': 'other-worker', 'worker_pubkey': str(self.fixture.agent.pubkey())}
        self.core.store.put('workers', 'other-worker', other)
        target = {'node_id': 'test-worker', 'worker_pubkey': worker['worker_pubkey']}
        self.request['worker_target'] = target
        quote = self.quote()
        self.assertEqual(quote['worker_target'], target)
        self.assertTrue(quote['message'].startswith('Aperture execution authorization v5\n'))
        admitted = self.client.post('/execute', json=self.body(quote))
        self.assertEqual(admitted.status_code, 200, admitted.text)
        headers = {**self.fixture.headers, 'X-Aperture-Worker-Id': 'other-worker'}
        self.assertIsNone(self.client.get('/get_task', headers=headers).json()['task_id'])
        self.assertEqual(self.fixture.claim()['task_id'], admitted.json()['task_id'])
        worker['accepting_tasks'] = False
        self.core.store.put('workers', 'test-worker', worker)
        self.assertEqual(self.client.post('/inference/quotes', json=self.request).status_code, 409)

    def test_python_delegation_does_not_authorize_inference(self):
        agent = str(self.fixture.agent.pubkey())
        self.core.store.put("agents", agent, {"owner": self.request["wallet"], "agent_pubkey": agent,
            "revoked": False, "expires_at": int(time.time()) + 60, "capabilities": ["python.execute"],
            "max_cost_lamports": 100000, "max_runtime_seconds": 30, "total_budget_lamports": 1000000,
            "version": 1})
        response = self.client.post("/inference/quotes", json={**self.request, "agent_pubkey": agent})
        self.assertEqual(response.status_code, 403, response.text)

    def test_inference_passport_is_scoped_and_rechecked_before_worker_claim(self):
        self.fixture.passport(capabilities=["inference.chat"])
        self.request["agent_pubkey"] = str(self.fixture.agent.pubkey())
        quote = self.quote()
        body = self.body(quote)
        body["agent_pubkey"] = self.request["agent_pubkey"]
        body["signature"] = list(bytes(self.fixture.agent.sign_message(quote["message"].encode())))
        response = self.client.post("/execute", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.fixture.passport(action="revoke", capabilities=["inference.chat"])
        worker = self.core.store.get("workers", "test-worker")
        worker.update(inference_offers=[self.provider.offer()], runtimes=["inference.chat"])
        self.core.store.put("workers", "test-worker", worker)
        self.assertEqual(self.fixture.claim(), {"task_id": None})
        receipt = self.core.store.get("jobs", response.json()["task_id"])["receipt"]
        self.assertEqual(receipt["execution_status"], "cancelled")
        self.assertEqual(receipt["settlement_type"], "NOT_STARTED")

    def test_inference_worker_never_claims_arbitrary_python(self):
        worker = self.core.store.get("workers", "test-worker")
        worker.update(inference_offers=[], runtimes=["python"])
        self.core.store.put("workers", "test-worker", worker)
        self.fixture.admit()
        worker = self.core.store.get("workers", "test-worker")
        worker.update(inference_offers=[self.provider.offer()], runtimes=["inference.chat"])
        self.core.store.put("workers", "test-worker", worker)
        self.assertEqual(self.fixture.claim(), {"task_id": None})

    def test_endpoint_rules_and_offer_change(self):
        for endpoint in ("http://example.com/v1", "https://user:secret@example.com/v1", "https://example.com/v1?key=secret"):
            with self.assertRaises(ValueError):
                Provider(**{**self.provider.model_dump(), "base_url": endpoint})
        quote = self.quote()
        self.core.inference_providers["local"] = self.provider.model_copy(update={"model": "changed-fixture-model"})
        self.assertEqual(self.client.post("/execute", json=self.body(quote)).status_code, 422)

    def test_gemini_provider_is_pinned_to_google_and_requires_worker_key(self):
        base = {**self.provider.model_dump(), "protocol": "gemini_generate_content",
                "model": "gemini-3.8-flash", "base_url": "https://generativelanguage.googleapis.com/v1beta",
                "api_key_env": "GEMINI_API_KEY"}
        provider = Provider(**base)
        self.assertEqual(provider.offer()["protocol"], "gemini_generate_content")
        with self.assertRaises(ValueError):
            Provider(**{**base, "base_url": "https://attacker.example/v1beta"})
        with self.assertRaises(ValueError):
            Provider(**{**base, "api_key_env": None})

    def test_deepseek_provider_is_pinned_to_vendor_and_requests_json_without_reasoning_tokens(self):
        base = {**self.provider.model_dump(), "id": "aperture-deepseek", "name": "Aperture DeepSeek",
                "model": "deepseek-flash", "base_url": "https://api.deepseek.com",
                "api_key_env": "DEEPSEEK_API_KEY"}
        provider = Provider(**base)
        self.assertEqual(provider.offer()["protocol"], "openai_chat_completions")
        with self.assertRaises(ValueError):
            Provider(**{**base, "base_url": "https://attacker.example"})
        with self.assertRaises(ValueError):
            Provider(**{**base, "api_key_env": "OTHER_API_KEY"})
        with self.assertRaises(ValueError):
            Provider(**{**base, "model": "deepseek-chat"})
        with self.assertRaises(ValueError):
            Provider(**{**base, "id": "operator-model", "base_url": "https://attacker.example"})
        with self.assertRaisesRegex(ValueError, "reserved for the fixed Aperture Sentinel provider"):
            Provider(**{**self.provider.model_dump(), "id": "operator-model", "name": "Operator model",
                         "base_url": "https://api.deepseek.com/v1", "api_key_env": "OPERATOR_API_KEY"})
        request = ChatRequest(provider_id=provider.id, messages=[{"role": "user", "content": "Review safely."}], max_tokens=64)
        self.assertEqual(inference_runner._openai_body(request, provider), {
            "model": "deepseek-flash", "messages": [{"role": "user", "content": "Review safely."}],
            "max_tokens": 64, "stream": True, "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"}})
        generic_request = ChatRequest(provider_id=self.provider.id,
            messages=[{"role": "user", "content": "Write a short answer."}], max_tokens=64)
        self.assertNotIn("response_format", inference_runner._openai_body(generic_request, self.provider))

    def test_deepseek_sentinel_stream_sends_json_mode_and_saves_exact_report(self):
        provider = Provider(id="aperture-deepseek", name="Aperture DeepSeek", model="deepseek-flash",
            base_url="https://api.deepseek.com", api_key_env="DEEPSEEK_API_KEY", max_output_tokens=512)
        source = "print(6 * 7)"
        report = json.dumps({"security": "SAFE", "reason": "No obvious issue found.", "findings": []})
        request = ChatRequest(provider_id=provider.id, messages=[{"role": "user",
            "content": PROMPT_PREFIX + json.dumps(source, ensure_ascii=False)}], max_tokens=128)
        parameters = request_parameters(request, provider)
        directory = self.root / "deepseek-runner"
        directory.mkdir()
        (directory / "payload.py").write_text(request_code(parameters), encoding="utf-8")
        (directory / "job.json").write_text(json.dumps({"parameters": parameters}), encoding="utf-8")
        config = self.root / "providers-deepseek.json"
        config.write_text(json.dumps([provider.model_dump()]), encoding="utf-8")
        captured = {}
        events = [
            {"model": provider.model, "choices": [{"index": 0, "delta": {"content": report}}]},
            {"model": provider.model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]

        class Response:
            status_code = 200
            headers = {"Content-Type": "text/event-stream"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def iter_content(self, chunk_size):
                for event in events:
                    yield ("data: " + json.dumps(event) + "\n\n").encode()
                yield b"data: [DONE]\n\n"

        def fake_post(_session, url, **kwargs):
            captured.update(url=url, **kwargs)
            return Response()

        with patch.dict(os.environ, {"APERTURE_INFERENCE_CONFIG": str(config), "DEEPSEEK_API_KEY": "fixture-secret"}):
            with patch("inference_runner.requests.Session.post", new=fake_post):
                with redirect_stdout(io.StringIO()):
                    inference_runner.run(directory)

        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["json"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["json"]["thinking"], {"type": "disabled"})
        self.assertEqual(captured["headers"]["Authorization"], "Bearer fixture-secret")
        self.assertEqual((directory / "response.txt").read_text(encoding="utf-8"), report)

    def test_deepseek_only_accepts_the_fixed_source_bound_sentinel_prompt(self):
        self.assertIn('security and execution-safety risks', PROMPT_PREFIX)
        self.assertIn('Do not estimate price, compute requirements, performance, or runtime', PROMPT_PREFIX)
        self.assertIn('Worker owners publish their own rates', PROMPT_PREFIX)
        self.assertNotIn('"predicted_sec"', PROMPT_PREFIX)
        provider = Provider(id="aperture-deepseek", name="Aperture DeepSeek", model="deepseek-flash",
            base_url="https://api.deepseek.com", api_key_env="DEEPSEEK_API_KEY", max_output_tokens=512)
        source = "print(6 * 7)"
        valid = ChatRequest(provider_id=provider.id, messages=[{"role": "user",
            "content": PROMPT_PREFIX + json.dumps(source, ensure_ascii=False)}], max_tokens=64)
        parameters = request_parameters(valid, provider)
        self.assertEqual(validate_request(request_code(parameters), parameters, {provider.id: provider}), valid)
        generic = ChatRequest(provider_id=provider.id, messages=[{"role": "user", "content": "Review safely."}], max_tokens=64)
        generic_parameters = request_parameters(generic, provider)
        with self.assertRaisesRegex(ValueError, "fixed AI Sentinel"):
            validate_request(request_code(generic_parameters), generic_parameters, {provider.id: provider})

    def test_native_gemini_sse_uses_google_key_header_and_content_format(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                captured.append({"path": self.path, "key": self.headers.get("x-goog-api-key"),
                                "authorization": self.headers.get("Authorization"),
                                "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                events = [
                    {"candidates": [{"content": {"role": "model", "parts": [{"text": "A budget "}]}}]},
                    {"candidates": [{"content": {"role": "model", "parts": [{"text": "bounds spending."}]},
                                     "finishReason": "STOP"}]},
                ]
                for event in events:
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                    self.wfile.flush()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        provider = Provider(**{**self.provider.model_dump(), "id": "gemini", "name": "Aperture Gemini",
            "protocol": "gemini_generate_content", "model": "gemini-3.8-flash",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1beta", "api_key_env": "GEMINI_API_KEY"})
        request = ChatRequest(provider_id="gemini", messages=[
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Explain a compute budget."},
        ], max_tokens=64)
        parameters = request_parameters(request, provider)
        code = request_code(parameters)
        directory = self.root / "gemini-runner"
        directory.mkdir()
        (directory / "payload.py").write_text(code, encoding="utf-8")
        (directory / "job.json").write_text(json.dumps({"parameters": parameters}), encoding="utf-8")
        config = self.root / "providers-gemini.json"
        config.write_text(json.dumps([provider.model_dump()]), encoding="utf-8")
        try:
            with patch.dict(os.environ, {"APERTURE_INFERENCE_CONFIG": str(config), "GEMINI_API_KEY": "fixture-secret"}):
                output = io.StringIO()
                with redirect_stdout(output):
                    inference_runner.run(directory)
                self.assertIn("A budget bounds spending.", output.getvalue())
                self.assertIn('"protocol":"gemini_generate_content"', output.getvalue())
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0]["path"], "/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse")
                self.assertEqual(captured[0]["key"], "fixture-secret")
                self.assertIsNone(captured[0]["authorization"])
                self.assertEqual(captured[0]["body"], {
                    "contents": [{"role": "user", "parts": [{"text": "Explain a compute budget."}]}],
                    "systemInstruction": {"parts": [{"text": "Be concise."}]},
                    "generationConfig": {"maxOutputTokens": 64},
                })
        finally:
            server.shutdown()
            server.server_close()

    def test_real_http_stream_subprocess_and_signed_gateway_receipt(self):
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                captured.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for text in ("A budget ", "bounds spending."):
                    event = {"model": "fixture-model", "choices": [{"index": 0, "delta": {"content": text}}]}
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.provider = self.provider.model_copy(update={"base_url": f"http://127.0.0.1:{server.server_port}/v1"})
        self.core.inference_providers = {"local": self.provider}
        identity = WorkerIdentity(self.root / "identity")
        self.advertise(self.provider, identity)
        config = self.root / "providers.json"
        config.write_text(json.dumps([self.provider.model_dump()]), encoding="utf-8")
        try:
            with patch.dict(os.environ, {"APERTURE_INFERENCE_CONFIG": str(config)}):
                quote = self.quote()
                admitted = self.client.post("/execute", json=self.body(quote)).json()
                task = self.fixture.claim()
                executor = InferenceExecutor()
                executor.preflight()
                payload = self.execute_claimed(task, executor)
                self.assertEqual(payload["exit_code"], 0, payload["output"])
                self.assertIn("A budget bounds spending.", payload["output"])
                self.assertEqual(payload["execution_mode"], "inference_proxy")
                signed = identity.attest(task, payload, "test-worker")
                response = self.client.post("/submit_result", json=signed, headers=self.fixture.headers)
                self.assertEqual(response.status_code, 200, response.text)
                receipt = self.core.store.get("jobs", admitted["task_id"])["receipt"]
                self.assertEqual(receipt["settlement_type"], "OFF_CHAIN")
                self.assertEqual(receipt["workload_sha256"], quote["workload_sha256"])
                self.assertEqual(receipt["output_sha256"], hashlib.sha256(payload["output"].encode()).hexdigest())
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0][1]["max_tokens"], 64)
        finally:
            server.shutdown()
            server.server_close()

    def test_gemini_sentinel_runs_through_signed_gateway_and_worker_receipt(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                captured.append({"path": self.path, "key": self.headers.get("x-goog-api-key"),
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))} )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                events = [
                    {"candidates": [{"content": {"role": "model", "parts": [{"text": '{"security":"REVIEW","reason":"Check the loop",'}]}}]},
                    {"candidates": [{"content": {"role": "model", "parts": [{"text": '"findings":[],"cpu":null,"ram":null,"network":null,"predicted_sec":null}'}]}, "finishReason": "STOP"}]},
                ]
                for event in events:
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                    self.wfile.flush()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        provider = Provider(id="aperture-gemini", name="Aperture Gemini",
            protocol="gemini_generate_content", model="gemini-3.8-flash",
            base_url=f"http://127.0.0.1:{server.server_port}/v1beta", api_key_env="GEMINI_API_KEY",
            rate_lamports_sec=2000, max_output_tokens=512)
        self.core.inference_providers = {provider.id: provider}
        identity = WorkerIdentity(self.root / "gemini-worker-identity")
        self.advertise(provider, identity)
        compute_source = 'print(42)'
        prompt = PROMPT_PREFIX + json.dumps(compute_source, ensure_ascii=False)
        self.request.update(provider_id=provider.id, messages=[{"role": "user", "content": prompt}])
        config = self.root / "providers-gemini-e2e.json"
        config.write_text(json.dumps([provider.model_dump()]), encoding="utf-8")
        try:
            with patch.dict(os.environ, {"APERTURE_INFERENCE_CONFIG": str(config), "GEMINI_API_KEY": "fixture-secret"}):
                quote = self.quote()
                self.assertEqual(quote["workload"]["runtime"], "inference.chat")
                self.assertNotIn("fixture-secret", json.dumps(quote))
                admitted = self.client.post("/execute", json=self.body(quote)).json()
                task = self.fixture.claim()
                executor = InferenceExecutor()
                executor.preflight()
                payload = self.execute_claimed(task, executor)
                self.assertEqual(payload["exit_code"], 0, payload["output"])
                self.assertIn('"security":"REVIEW"', payload["output"])
                self.assertIn(prompt, captured[0]["body"]["contents"][0]["parts"][0]["text"])
                self.assertEqual(payload["execution_mode"], "inference_proxy")
                signed = identity.attest(task, payload, "test-worker")
                response = self.client.post("/submit_result", json=signed, headers=self.fixture.headers)
                self.assertEqual(response.status_code, 200, response.text)
                receipt = self.core.store.get("jobs", admitted["task_id"])["receipt"]
                self.assertEqual(receipt["execution_status"], "completed")
                self.assertEqual(receipt["settlement_type"], "OFF_CHAIN")
                self.assertEqual(receipt["workload_sha256"], quote["workload_sha256"])
                self.assertEqual(receipt["output_sha256"], hashlib.sha256(payload["output"].encode()).hexdigest())
                reference = {"task_id": admitted["task_id"], "source_sha256": hashlib.sha256(compute_source.encode()).hexdigest(),
                             "receipt_sha256": receipt["receipt_sha256"]}
                worker = self.core.store.get('workers', 'test-worker')
                worker['runtimes'] = ['inference.chat', 'python']
                self.core.store.put('workers', 'test-worker', worker)
                response = self.client.post('/quotes', json={"wallet": quote['wallet'], "code": compute_source,
                    "max_cost_lamports": 100000, "max_runtime_seconds": 10, "job_version": 1,
                    "parameters": {"aperture_review": reference}})
                self.assertEqual(response.status_code, 200, response.text)
                compute_quote = response.json()
                body = self.fixture.signed_run(compute_quote, code=compute_source)
                body.update(job_version=1, inputs=[], parameters=compute_quote['workload']['parameters'])
                response = self.client.post('/execute', json=body)
                self.assertEqual(response.status_code, 200, response.text)
                compute_id = response.json()['task_id']
                compute_task = self.fixture.claim()
                self.assertEqual(compute_task['task_id'], compute_id)
                cpu = TrustedLocalExecutor()
                cpu.preflight()
                computed = self.execute_claimed(compute_task, cpu)
                self.assertEqual(computed['exit_code'], 0, computed['output'])
                self.assertEqual(computed['output'].strip(), '42')
                signed = identity.attest(compute_task, computed, 'test-worker')
                response = self.client.post('/submit_result', json=signed, headers=self.fixture.headers)
                self.assertEqual(response.status_code, 200, response.text)
                completed = self.core.store.get('jobs', compute_id)
                self.assertEqual(completed['workload']['parameters']['aperture_review'], reference)
                self.assertEqual(completed['receipt']['workload_sha256'], compute_quote['workload_sha256'])
                self.assertEqual(completed['receipt']['execution_status'], 'completed')
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0]["path"], "/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse")
                self.assertEqual(captured[0]["key"], "fixture-secret")
                self.assertIsNone(captured[0]["authorization"])
        finally:
            server.shutdown()
            server.server_close()

    def test_sentinel_5xx_and_truncated_report_fail_closed_without_provider_retry(self):
        source = "print('review this source')"
        prompt = PROMPT_PREFIX + json.dumps(source, ensure_ascii=False)
        for scenario in ("http_503", "truncated_json"):
            with self.subTest(scenario=scenario):
                requests_seen = []

                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *args):
                        pass

                    def do_POST(self):
                        requests_seen.append(self.path)
                        self.rfile.read(int(self.headers["Content-Length"]))
                        if scenario == "http_503":
                            self.send_response(503)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(b'{"error":"fixture outage"}')
                            return
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.end_headers()
                        events = [
                            {"candidates": [{"content": {"parts": [
                                {"text": '{"security":"SAFE","reason":"partial'}]}}]},
                            {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]},
                        ]
                        for event in events:
                            self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                            self.wfile.flush()

                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                provider = Provider(id="aperture-gemini", name="Aperture Gemini",
                    protocol="gemini_generate_content", model="gemini-3.8-flash",
                    base_url=f"http://127.0.0.1:{server.server_port}/v1beta", api_key_env="GEMINI_API_KEY",
                    rate_lamports_sec=2000, max_output_tokens=512)
                self.core.inference_providers = {provider.id: provider}
                identity = WorkerIdentity(self.root / f"sentinel-{scenario}-worker")
                self.advertise(provider, identity)
                self.request.update(provider_id=provider.id, messages=[{"role": "user", "content": prompt}])
                config = self.root / f"providers-{scenario}.json"
                config.write_text(json.dumps([provider.model_dump()]), encoding="utf-8")
                try:
                    with patch.dict(os.environ, {"APERTURE_INFERENCE_CONFIG": str(config), "GEMINI_API_KEY": "fixture-secret"}):
                        quote = self.quote()
                        admitted = self.client.post("/execute", json=self.body(quote))
                        self.assertEqual(admitted.status_code, 200, admitted.text)
                        task = self.fixture.claim()
                        executor = InferenceExecutor()
                        executor.preflight()
                        payload = self.execute_claimed(task, executor)
                        self.assertNotEqual(payload["exit_code"], 0)
                        self.assertIn("[INFERENCE_FAILED: ValueError]", payload["output"])
                        self.assertEqual(payload["artifacts"], [])
                        signed = identity.attest(task, payload, "test-worker")
                        response = self.client.post("/submit_result", json=signed, headers=self.fixture.headers)
                        self.assertEqual(response.status_code, 200, response.text)
                        receipt = self.core.store.get("jobs", admitted.json()["task_id"])["receipt"]
                        self.assertEqual(receipt["execution_status"], "failed")
                        self.assertEqual(receipt["settlement_type"], "OFF_CHAIN")
                        self.assertEqual(len(requests_seen), 1, "the model request must not be retried")
                finally:
                    server.shutdown()
                    server.server_close()

    def test_provider_wait_is_bounded_without_retrying_inference(self):
        requests_seen = []
        class SlowHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                requests_seen.append(self.path)
                self.rfile.read(int(self.headers["Content-Length"]))
                time.sleep(11)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.provider = self.provider.model_copy(update={"base_url": f"http://127.0.0.1:{server.server_port}/v1"})
        self.core.inference_providers = {"local": self.provider}
        identity = WorkerIdentity(self.root / "timeout-worker-identity")
        self.advertise(self.provider, identity)
        source = "print(42)"
        self.request["messages"] = [{"role": "user", "content": PROMPT_PREFIX + json.dumps(source, ensure_ascii=False)}]
        # Leave enough budget for the isolated Python adapter to start on slower
        # Windows/CI hosts before checking that a stalled Sentinel request settles.
        self.request["max_runtime_seconds"] = 8
        config = self.root / "providers.json"
        config.write_text(json.dumps([self.provider.model_dump()]), encoding="utf-8")
        try:
            with patch.dict(os.environ, {"APERTURE_INFERENCE_CONFIG": str(config)}):
                quote = self.quote()
                self.client.post("/execute", json=self.body(quote)).raise_for_status()
                worker = self.core.store.get("workers", "test-worker")
                worker.update(inference_offers=[self.provider.offer()], runtimes=["inference.chat"])
                self.core.store.put("workers", "test-worker", worker)
                task = self.fixture.claim()
                executor = InferenceExecutor()
                executor.preflight()
                started = time.monotonic()
                payload = self.execute_claimed(task, executor)
                self.assertIn(payload["exit_code"], (124, 130))
                self.assertLess(time.monotonic() - started, 8.5)
                self.assertEqual(payload["artifacts"], [])
                signed = identity.attest(task, payload, "test-worker")
                response = self.client.post("/submit_result", json=signed, headers=self.fixture.headers)
                self.assertEqual(response.status_code, 200, response.text)
                receipt = self.core.store.get("jobs", task["task_id"])["receipt"]
                self.assertEqual(receipt["execution_status"], "failed")
                self.assertEqual(receipt["settlement_type"], "OFF_CHAIN")
                self.assertEqual(len(requests_seen), 1)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
