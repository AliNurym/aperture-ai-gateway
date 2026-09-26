"""Durable single-gateway admission, identity, and execution evidence."""
import json
import sqlite3
import threading
import os
from contextlib import contextmanager
from pathlib import Path

ACTIVE_STATES = ("queued", "starting", "running", "settlement_pending")

class StateStore:
    def __init__(self, path):
        self.process_lock = None
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            # A queue claimant must have one gateway process. SQLite alone
            # protects admission but not the await/RPC gap during a claim.
            self.process_lock = open(str(path) + '.lock', 'a+b')
            self.process_lock.seek(0)
            if not self.process_lock.read(1):
                self.process_lock.write(b'1')
                self.process_lock.flush()
            self.process_lock.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.process_lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.process_lock.close()
                raise RuntimeError('This state database is already owned by another gateway process. Run one gateway instance per database.')
        self.connection = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript("""
          CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, data TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS challenges (id TEXT PRIMARY KEY, data TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, wallet TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL);
          CREATE UNIQUE INDEX IF NOT EXISTS active_wallet ON jobs(wallet)
            WHERE state IN ('queued','starting','running','settlement_pending');
        """)
        self.connection.commit()
        self.lock = threading.RLock()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def put(self, table, key, value):
        assert table in {"quotes", "challenges", "agents", "workers"}
        with self.transaction() as db:
            db.execute(f"INSERT INTO {table}(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (key, json.dumps(value, sort_keys=True)))

    def get(self, table, key):
        assert table in {"quotes", "challenges", "agents", "jobs", "workers"}
        with self.lock:
            row = self.connection.execute(f"SELECT data FROM {table} WHERE id=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def list(self, table):
        assert table in {"quotes", "challenges", "agents", "jobs", "workers"}
        with self.lock:
            return [json.loads(row[0]) for row in self.connection.execute(f"SELECT data FROM {table} ORDER BY rowid")]

    def admit(self, quote_id, job, max_pending):
        """Replay consumption and wallet reservation commit together."""
        with self.transaction() as db:
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state='queued'").fetchone()[0] >= max_pending:
                raise ValueError("queue_full")
            row = db.execute("SELECT consumed FROM quotes WHERE id=?", (quote_id,)).fetchone()
            if not row or row[0]:
                raise ValueError("quote_consumed")
            db.execute("INSERT INTO jobs(id,wallet,state,data) VALUES (?,?,?,?)", (job["task_id"], job["wallet"], job["state"], json.dumps(job, sort_keys=True)))
            db.execute("UPDATE quotes SET consumed=1 WHERE id=?", (quote_id,))

    def consume_challenge(self, challenge_id, agent):
        with self.transaction() as db:
            row = db.execute("SELECT consumed FROM challenges WHERE id=?", (challenge_id,)).fetchone()
            if not row or row[0]:
                raise ValueError("challenge_consumed")
            db.execute("UPDATE challenges SET consumed=1 WHERE id=?", (challenge_id,))
            db.execute("INSERT INTO agents(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (agent["agent_pubkey"], json.dumps(agent, sort_keys=True)))

    def save_job(self, job):
        with self.transaction() as db:
            db.execute("INSERT INTO jobs(id,wallet,state,data) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data", (job["task_id"], job["wallet"], job["state"], json.dumps(job, sort_keys=True)))

    def close(self):
        with self.lock:
            self.connection.close()
            if self.process_lock:
                if os.name == 'nt':
                    import msvcrt
                    self.process_lock.seek(0)
                    msvcrt.locking(self.process_lock.fileno(), msvcrt.LK_UNLCK, 1)
                self.process_lock.close()
                self.process_lock = None
