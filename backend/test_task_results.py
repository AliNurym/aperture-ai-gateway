import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from solders.keypair import Keypair

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

class TaskResultTests(unittest.TestCase):
    def test_main_import_and_security_headers_from_clean_configuration(self):
        os.environ['APERTURE_ENV'] = 'test'
        os.environ['APERTURE_STATE_DB'] = ':memory:'
        os.environ['APERTURE_WORKER_TOKEN'] = 'test-worker-secret'
        os.environ['APERTURE_DEMO_MODE'] = 'true'
        os.environ['BACKEND_PRIVATE_KEY'] = json.dumps(list(bytes(Keypair())))
        from fastapi.testclient import TestClient
        import main
        with TestClient(main.app) as client:
            response = client.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            health = client.get('/health').json()
            self.assertFalse(health['durable_state'])
            self.assertEqual(health['protocol_version'], 2)
            self.assertNotIn('test-worker-secret', response.text)


if __name__ == '__main__':
    unittest.main()
