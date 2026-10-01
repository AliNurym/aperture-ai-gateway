"""Process exit status and main API startup regressions."""
import json
import os
import unittest
from unittest.mock import patch
from solders.keypair import Keypair

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
