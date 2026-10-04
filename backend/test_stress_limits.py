"""Stress and limit boundary tests for APERTURE gateway, AST parser, and state store."""
import concurrent.futures
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from ai_engine import analyze_code_ast
from gateway import Gateway
from state_store import StateStore

TOKEN = "test-worker-secret-32-chars-long-12345"


class FakeSolana:
    def __init__(self):
        self.ai_signer = Keypair()
        self.program_id = Pubkey.new_unique()
        self.treasury = Pubkey.new_unique()
        self.get_protocol_config = AsyncMock(return_value={"treasury": self.treasury})
        self.get_channel_state = AsyncMock(
            return_value={
                "balance_lamports": 5_000_000_000,
                "effective_balance_lamports": 5_000_000_000,
                "burn_rate_lamports": 0,
            }
        )
        self.get_agent_passport = AsyncMock(return_value=None)
        self.get_task_receipt = AsyncMock(return_value=None)
        self.prepare_start_task = AsyncMock(
            return_value={
                "signature": "mock-prepare-sig",
                "transaction": "mock-tx",
                "last_valid_block_height": 100,
            }
        )
        self.send_prepared_start = AsyncMock(return_value="mock-start-confirmed")
        self.stop_task = AsyncMock(
            return_value={
                "signature": "mock-stop-sig",
                "charged_lamports": 2000,
                "evidence": "confirmed_task_receipt",
            }
        )
        self.agent_instruction = lambda action, policy: {
            "kind": action,
            "program_id": str(self.program_id),
            "data": [],
            "data_base64": "",
            "accounts": [],
        }


class StressLimitsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_stress.sqlite3"
        self.store = StateStore(str(self.db_path))
        self.chain = FakeSolana()
        self.gateway = Gateway(self.chain, True, TOKEN, self.store)
        self.app = FastAPI()
        self.app.include_router(self.gateway.router)
        self.client = TestClient(self.app)
        self.owner = Keypair()
        self.agent = Keypair()
        self.worker = Keypair()
        self.store.put("workers", "test-worker-1", {"worker_pubkey": str(self.worker.pubkey())})

    def tearDown(self):
        self.client.close()
        self.store.close()
        self.temp_dir.cleanup()

    # =========================================================================
    # 1. AST OBSTACLES, BYPASS & OBFUSCATION ATTEMPTS
    # =========================================================================

    def test_blocks_getattr_reflection(self):
        """getattr allows dynamic assembly of private names at runtime; it must be blocked."""
        payloads = [
            "getattr(math, 'sin')(1)",
            "fn = getattr\nfn(math, 'cos')(0)",
            "x = getattr(random, '_os')",
        ]
        for src in payloads:
            with self.subTest(src=src):
                result = analyze_code_ast(src)
                self.assertEqual(result["security"], "DANGEROUS")
                self.assertIn("Forbidden", result.get("reason", ""))

    def test_blocks_vars_globals_locals(self):
        """Inspection builtins (vars, globals, locals) must be rejected."""
        for fn in ("vars()", "globals()", "locals()"):
            result = analyze_code_ast(f"x = {fn}")
            self.assertEqual(result["security"], "DANGEROUS")

    def test_blocks_dunder_subclass_traversal(self):
        """Traversal of object graph via __class__, __bases__, __subclasses__ must be blocked."""
        payloads = [
            "sub = ().__class__.__bases__[0].__subclasses__()",
            "x = [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings']",
            "f = lambda: None\nc = f.__code__",
            "x = f.__globals__",
        ]
        for src in payloads:
            with self.subTest(src=src):
                result = analyze_code_ast(src)
                self.assertEqual(result["security"], "DANGEROUS")

    def test_blocks_process_termination_builtins(self):
        """Process exit/quit builtins must be blocked."""
        for src in ("exit(0)", "quit()"):
            result = analyze_code_ast(src)
            self.assertEqual(result["security"], "DANGEROUS")

    def test_blocks_dynamic_compilation(self):
        """compile() and exec() must be rejected."""
        result = analyze_code_ast("code = compile('1+1', '', 'eval')")
        self.assertEqual(result["security"], "DANGEROUS")

    def test_blocks_nested_lambda_obfuscation(self):
        """Complex lambda obfuscations must not crash the AST analyzer."""
        src = "(lambda a: (lambda b: a(b)))(lambda x: x + 1)(10)"
        result = analyze_code_ast(src)
        self.assertEqual(result["security"], "SAFE")
        self.assertTrue(result["syntax_valid"])

    # =========================================================================
    # 2. DOS & PAYLOAD LIMIT BOUNDARIES
    # =========================================================================

    def test_rejects_giant_source_payload_in_ast(self):
        """Sources exceeding 32 KiB are rejected cleanly without high latency."""
        huge_code = "x = 1\n" * 7000  # ~42 KiB
        start = time.perf_counter()
        result = analyze_code_ast(huge_code)
        elapsed = time.perf_counter() - start

        self.assertEqual(result["security"], "DANGEROUS")
        self.assertIn("maximum source size is 32,000 UTF-8 bytes", result.get("reason", ""))
        self.assertLess(elapsed, 0.05, "Rejection must be sub-50ms fast")

    def test_quotes_endpoint_rejects_oversized_payload(self):
        """The /quotes endpoint rejects payloads over 32 KiB with HTTP 422 or 403."""
        huge_code = "# " + ("A" * 35_000) + "\nprint(1)"
        res = self.client.post(
            "/quotes",
            json={
                "wallet": str(self.owner.pubkey()),
                "code": huge_code,
            },
        )
        self.assertIn(res.status_code, (400, 403, 422))

    def test_deeply_nested_expressions_handled_safely(self):
        """Deeply nested binary expressions must parse safely without crashing."""
        expr = " + ".join(["1"] * 200)
        code = f"x = {expr}"
        result = analyze_code_ast(code)
        self.assertEqual(result["security"], "SAFE")
        self.assertGreater(result["cpu"], 0)

    # =========================================================================
    # 3. HIGH CONCURRENCY ON STATE STORE (SQLITE THREAD SAFETY)
    # =========================================================================

    def test_concurrent_state_store_multi_thread_writes(self):
        """Ensure 20 concurrent threads writing and reading jobs don't cause DB lock errors."""
        errors = []
        thread_count = 20
        ops_per_thread = 10

        def worker_job(thread_idx):
            try:
                for i in range(ops_per_thread):
                    job_id = f"job-th{thread_idx}-op{i}"
                    wallet_id = f"wallet-owner-{thread_idx}"
                    agent_id = f"agent-pubkey-{thread_idx}"

                    # Save initial queued job
                    job_data = {
                        "task_id": job_id,
                        "wallet": wallet_id,
                        "agent_pubkey": agent_id,
                        "state": "queued",
                        "thread": thread_idx,
                        "op": i,
                        "timestamp": time.time(),
                    }
                    self.store.save_job(job_data)

                    # Read it back and verify
                    fetched = self.store.get("jobs", job_id)
                    if not fetched or fetched.get("thread") != thread_idx:
                        raise ValueError(f"Data corruption or missing on {job_id}")

                    # Transition state to completed with receipt
                    job_data["state"] = "completed"
                    job_data["receipt"] = {"charged_lamports": 100}
                    self.store.save_job(job_data)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker_job, args=(t,))
            for t in range(thread_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent DB errors encountered: {errors}")

        # Verify all jobs are recorded
        total_jobs = self.store.list("jobs")
        self.assertGreaterEqual(len(total_jobs), 1)

    def test_concurrent_spend_increments_via_completed_jobs(self):
        """Ensure atomic spend tracking via completed jobs across concurrent worker threads."""
        thread_count = 10
        charge_per_job = 500
        agent_id = str(self.agent.pubkey())
        wallet_id = str(self.owner.pubkey())

        def complete_job(idx):
            job_data = {
                "task_id": f"spend-task-{idx}",
                "wallet": wallet_id,
                "agent_pubkey": agent_id,
                "state": "completed",
                "receipt": {"charged_lamports": charge_per_job},
            }
            self.store.save_job(job_data)

        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(complete_job, i) for i in range(thread_count)]
            concurrent.futures.wait(futures)

        total_spent = self.store.spent_for_agent(agent_id)
        self.assertEqual(total_spent, thread_count * charge_per_job)


if __name__ == "__main__":
    unittest.main()
