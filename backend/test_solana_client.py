import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from solana_client import validate_devnet_rpc_url


class DevnetEndpointTests(unittest.TestCase):
    def test_accepts_explicit_https_devnet_hosts_and_local_validator(self):
        self.assertEqual(validate_devnet_rpc_url("https://api.devnet.solana.com"), "https://api.devnet.solana.com")
        self.assertEqual(validate_devnet_rpc_url("https://devnet.helius-rpc.com/?api-key=local"), "https://devnet.helius-rpc.com/?api-key=local")
        self.assertEqual(validate_devnet_rpc_url("http://127.0.0.1:8899"), "http://127.0.0.1:8899")

    def test_rejects_mainnet_and_remote_http_before_client_creation(self):
        for value in ("https://api.mainnet-beta.solana.com", "http://api.devnet.solana.com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_devnet_rpc_url(value)


if __name__ == "__main__":
    unittest.main()
