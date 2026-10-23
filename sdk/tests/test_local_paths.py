import sys
import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / 'python'))
from aperture_client.local_paths import durable_path, readonly_sqlite_uri
from aperture_client.workflow_tools import WorkflowTools


class LongWorkflowPathTests(unittest.TestCase):
    def test_plan_atomic_write_and_reopen_under_a_long_workspace_path(self):
        base = durable_path(Path(__file__).parents[2] / '.aperture' / 'test-temp')
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            root = durable_path(temporary)
            for index in range(8):
                root /= f'workspace-{index}-' + 'a' * 24
            self.assertGreater(len(str(root)), 300)
            client = SimpleNamespace(owner='owner', agent='agent', program_id='program',
                gateway_pubkey='gateway', network='off_chain', treasury=None, url='http://127.0.0.1:8000')
            tools = SimpleNamespace(client=client, max_cost_lamports=100000,
                max_runtime_seconds=30, max_rate_lamports=25000)
            steps = [{'id': 'one', 'source': 'print(42)', 'inputs': [], 'parameters': {},
                      'max_cost_lamports': 10000, 'max_runtime_seconds': 10}]
            first = WorkflowTools(tools, root, 100000)
            prepared = first.prepare(steps, 10000)
            second = WorkflowTools(tools, root, 100000)
            retained = second.get(prepared['workflow_id'])
            self.assertEqual(retained['status'], 'prepared')
            self.assertEqual(retained['workflow_id'], prepared['workflow_id'])
            self.assertEqual(second._load(prepared['workflow_id'])['steps'][0]['source'], 'print(42)')
            self.assertEqual(list(root.glob('*.tmp-*')), [])
            journal = second._path(prepared['workflow_id'], '.sqlite3')
            self.assertEqual(second._journal_rows(prepared['workflow_id'], 'completed'), [])
            self.assertFalse(journal.exists(), 'A read must not create a missing journal')
            with closing(sqlite3.connect(journal)) as database:
                database.execute('CREATE TABLE steps (id TEXT, state TEXT, data TEXT)')
                database.execute("INSERT INTO steps VALUES ('one','completed','{}')")
                database.commit()
            self.assertEqual(second._journal_rows(prepared['workflow_id'], 'completed'), [('completed', '{}')])
            with closing(sqlite3.connect(readonly_sqlite_uri(journal), uri=True)) as database:
                with self.assertRaisesRegex(sqlite3.OperationalError, 'readonly'):
                    database.execute('CREATE TABLE prohibited (id TEXT)')


if __name__ == '__main__':
    unittest.main()
