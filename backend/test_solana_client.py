import sys
import unittest
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from solana_client import DEFAULT_PROGRAM_ID, SolanaClient, get_anchor_discriminator, validate_devnet_rpc_url


class DevnetEndpointTests(unittest.TestCase):
    def test_accepts_explicit_https_devnet_hosts_and_local_validator(self):
        self.assertEqual(validate_devnet_rpc_url("https://api.devnet.solana.com"), "https://api.devnet.solana.com")
        self.assertEqual(validate_devnet_rpc_url("https://devnet.helius-rpc.com/?api-key=local"), "https://devnet.helius-rpc.com/?api-key=local")
        self.assertEqual(validate_devnet_rpc_url("http://127.0.0.1:8899"), "http://127.0.0.1:8899")

    def test_rejects_mainnet_and_remote_http_before_client_creation(self):
        for value in ("https://api.mainnet-beta.solana.com", "http://api.devnet.solana.com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_devnet_rpc_url(value)


class WorkerPayoutAbiTests(unittest.TestCase):
    def make_client(self):
        client = object.__new__(SolanaClient)
        client.program_id = Pubkey.from_string(DEFAULT_PROGRAM_ID)
        client.ai_signer = Keypair()
        client.get_protocol_config = AsyncMock(return_value={
            "config_pda": Pubkey.new_unique(), "treasury": Pubkey.new_unique(),
        })
        return client

    def test_start_and_stop_instruction_metas_bind_the_worker_recipient(self):
        client = self.make_client()
        owner, agent, worker = (str(Keypair().pubkey()) for _ in range(3))
        task_hash, source_hash = "12" * 32, "34" * 32
        config = client.get_protocol_config.return_value
        channel, _ = client.get_channel_pda(Pubkey.from_string(owner))
        receipt = client.get_task_receipt_pda(task_hash)
        extra = client._start_task_extra(source_hash, agent, Pubkey.from_string(worker), 15, 150, 10)
        self.assertEqual(len(extra), 116)
        self.assertEqual(extra[64:96], bytes(Pubkey.from_string(worker)))
        start_accounts = client._task_instruction_accounts(
            "start_task", owner, agent, channel, receipt, config,
        )
        self.assertEqual(len(start_accounts), 6)
        self.assertNotIn(config["treasury"], [meta.pubkey for meta in start_accounts])

        stop_accounts = client._task_instruction_accounts(
            "stop_task", owner, agent, channel, receipt, config, worker,
        )
        self.assertEqual(stop_accounts[4].pubkey, Pubkey.from_string(worker))
        self.assertTrue(stop_accounts[4].is_writable)

    def test_channel_decoder_exposes_pinned_executor_and_last_paid_worker(self):
        owner, oracle, agent, worker = [Keypair().pubkey() for _ in range(4)]
        client = self.make_client()

        def state_bytes(active):
            data = bytearray(225)
            data[:8] = get_anchor_discriminator("account", "ChannelState")
            data[8:40] = bytes(owner)
            data[40:72] = bytes(oracle)
            struct.pack_into("<Q", data, 72, 1_000_000)
            struct.pack_into("<Q", data, 80, 10 if active else 0)
            struct.pack_into("<q", data, 88, 1_700_000_000)
            data[97:129] = bytes(agent if active else worker)
            data[129:161] = bytes.fromhex("ab" * 32) if active else bytes(32)
            struct.pack_into("<Q", data, 161, 100_000 if active else 0)
            struct.pack_into("<q", data, 169, 1_700_000_100 if active else 0)
            struct.pack_into("<q", data, 177, 1_700_000_000 if active else 0)
            data[185:217] = bytes(worker if active else bytes.fromhex("cd" * 32))
            struct.pack_into("<Q", data, 217, 0xFFFFFFFFFFFFFFFF if active else 42)
            return bytes(data)

        active = client._decode_channel_state_data(state_bytes(True), Pubkey.new_unique())
        self.assertEqual(active["executor_pubkey"], str(worker))
        self.assertTrue(active["worker_payout_bound"])
        self.assertIsNone(active["last_task_hash"])

        idle = client._decode_channel_state_data(state_bytes(False), Pubkey.new_unique())
        self.assertEqual(idle["last_worker_pubkey"], str(worker))
        self.assertEqual(idle["last_charged_lamports"], 42)
        self.assertEqual(idle["last_task_hash"], "cd" * 32)


class WorkerPayoutRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, *, receipt=None, channel_state=None):
        client = object.__new__(SolanaClient)
        client.get_task_receipt = AsyncMock(return_value=receipt)
        client.get_channel_state = AsyncMock(return_value=channel_state)
        client._receipt_settlement = AsyncMock(return_value={
            "signature": "settlement-signature",
            "charged_lamports": 42,
            "evidence": "confirmed_task_receipt",
        })
        client.client = SimpleNamespace(
            get_block_height=AsyncMock(return_value=SimpleNamespace(value=2)),
            get_signature_statuses=AsyncMock(return_value=SimpleNamespace(
                value=[SimpleNamespace(err=None)],
            )),
        )
        return client

    async def test_channel_state_recovery_preserves_chain_observed_worker_payment(self):
        owner, agent, worker = (str(Keypair().pubkey()) for _ in range(3))
        task_hash = "ab" * 32
        start_signature = str(Keypair().sign_message(b"start"))
        client = self.make_client(channel_state={
            "last_task_hash": task_hash,
            "burn_rate_lamports": 0,
            "last_charged_lamports": 42,
            "last_worker_pubkey": worker,
        })

        settlement = await client.stop_task(
            owner, task_hash, agent,
            start_intent={"signature": start_signature, "last_valid_block_height": 1},
            worker_pubkey=worker, worker_payout_bound=True,
        )

        self.assertEqual(settlement["charged_lamports"], 42)
        self.assertEqual(settlement["worker_pubkey"], worker)
        self.assertEqual(settlement["payout_destination"], worker)
        self.assertEqual(settlement["evidence"], "confirmed_channel_state")

    async def test_channel_state_recovery_rejects_a_different_stored_worker(self):
        owner, agent, expected, wrong = (str(Keypair().pubkey()) for _ in range(4))
        task_hash = "cd" * 32
        start_signature = str(Keypair().sign_message(b"start"))
        client = self.make_client(channel_state={
            "last_task_hash": task_hash,
            "burn_rate_lamports": 0,
            "last_charged_lamports": 42,
            "last_worker_pubkey": expected,
        })

        with self.assertRaisesRegex(ValueError, "different worker key"):
            await client.stop_task(
                owner, task_hash, agent,
                start_intent={"signature": start_signature, "last_valid_block_height": 1},
                worker_pubkey=wrong, worker_payout_bound=True,
            )

    async def test_missing_transaction_history_does_not_claim_zero_cost(self):
        owner, agent = (str(Keypair().pubkey()) for _ in range(2))
        client = self.make_client()
        client.client.get_signature_statuses = AsyncMock(return_value=SimpleNamespace(value=[None]))
        start_signature = str(Keypair().sign_message(b"start"))

        settlement = await client.stop_task(
            owner, "12" * 32, agent,
            start_intent={"signature": start_signature, "last_valid_block_height": 1},
        )

        self.assertIsNone(settlement)
        client.get_channel_state.assert_not_awaited()

    async def test_settled_receipt_recovery_records_only_a_pinned_worker(self):
        owner, agent, worker = (str(Keypair().pubkey()) for _ in range(3))
        receipt = {"owner": owner, "agent_pubkey": agent, "settled": True}
        client = self.make_client(receipt=receipt)

        settlement = await client.stop_task(
            owner, "ef" * 32, agent, worker_pubkey=worker,
            worker_payout_bound=True,
        )

        self.assertEqual(settlement["payout_destination"], worker)
        client._receipt_settlement.assert_awaited_once_with(receipt)

        client = self.make_client(receipt=receipt)
        settlement = await client.stop_task(
            owner, "ef" * 32, agent, worker_pubkey=worker,
            worker_payout_bound=False,
        )
        self.assertNotIn("payout_destination", settlement)


if __name__ == "__main__":
    unittest.main()
