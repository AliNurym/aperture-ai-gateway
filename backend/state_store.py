"""Durable single-gateway admission, identity, and execution evidence."""
import json
import sqlite3
import threading
import os
import time
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
          CREATE TABLE IF NOT EXISTS agent_spend (agent_pubkey TEXT PRIMARY KEY, charged_lamports INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS store_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE UNIQUE INDEX IF NOT EXISTS active_wallet ON jobs(wallet)
            WHERE state IN ('queued','starting','running','settlement_pending');
        """)
        self.connection.commit()
        self.lock = threading.RLock()
        self._migrate_agent_spend()

    def _migrate_agent_spend(self):
        """Preserve delegated allowance accounting before completed jobs are pruned."""
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM store_metadata WHERE key='agent_spend_v1'").fetchone():
                return
            totals = {}
            for (raw,) in db.execute("SELECT data FROM jobs WHERE state='completed'"):
                job = json.loads(raw)
                receipt = job.get('receipt') or {}
                agent = job.get('agent_pubkey')
                charged = receipt.get('charged_lamports')
                if agent and type(charged) is int and charged >= 0:
                    totals[agent] = totals.get(agent, 0) + charged
            db.executemany(
                "INSERT INTO agent_spend(agent_pubkey,charged_lamports) VALUES (?,?) "
                "ON CONFLICT(agent_pubkey) DO UPDATE SET charged_lamports=excluded.charged_lamports",
                totals.items(),
            )
            db.execute("INSERT INTO store_metadata(key,value) VALUES ('agent_spend_v1','done')")

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
            if table in {"quotes", "challenges"}:
                self._prune_ephemeral(db, table)
            db.execute(f"INSERT INTO {table}(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (key, json.dumps(value, sort_keys=True)))

    def _prune_ephemeral(self, db, table):
        now = int(time.time())
        rows = db.execute(f"SELECT id,data,consumed FROM {table} ORDER BY rowid").fetchall()
        remove = []
        unused = []
        for key, raw, consumed in rows:
            value = json.loads(raw)
            expired = type(value.get('expires_at')) is int and value['expires_at'] <= now
            if expired and (table == 'challenges' or not consumed):
                remove.append((key,))
            elif table == 'challenges' or not consumed:
                unused.append(key)
        if remove:
            db.executemany(f"DELETE FROM {table} WHERE id=?", remove)
        # Leave room for the row which the caller is about to insert.
        overflow = len(unused) - 9_999
        if overflow > 0:
            # Oldest unused approvals can be requested again; never evict a
            # consumed quote while its task may still need exact replay recovery.
            victims = unused[:overflow]
            db.executemany(f"DELETE FROM {table} WHERE id=?", ((key,) for key in victims))

    def spent_for_agent(self, agent_pubkey):
        with self.lock:
            row = self.connection.execute("SELECT charged_lamports FROM agent_spend WHERE agent_pubkey=?", (agent_pubkey,)).fetchone()
            return row[0] if row else 0

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
            previous = db.execute("SELECT state FROM jobs WHERE id=?", (job["task_id"],)).fetchone()
            db.execute("INSERT INTO jobs(id,wallet,state,data) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data", (job["task_id"], job["wallet"], job["state"], json.dumps(job, sort_keys=True)))
            if job.get("state") == "completed" and (not previous or previous[0] != "completed"):
                charged = (job.get("receipt") or {}).get("charged_lamports")
                if type(charged) is int and charged >= 0:
                    db.execute(
                        "INSERT INTO agent_spend(agent_pubkey,charged_lamports) VALUES (?,?) "
                        "ON CONFLICT(agent_pubkey) DO UPDATE SET charged_lamports=charged_lamports+excluded.charged_lamports",
                        (job["agent_pubkey"], charged),
                    )
            if job.get("state") == "completed":
                self._prune_completed_jobs(db)

    def _prune_completed_jobs(self, db):
        try:
            keep = max(1, min(100_000, int(os.getenv("APERTURE_MAX_COMPLETED_TASKS", "1000"))))
        except ValueError:
            keep = 1000
        stale = db.execute(
            "SELECT id,data FROM jobs WHERE state='completed' ORDER BY rowid DESC LIMIT -1 OFFSET ?",
            (keep,),
        ).fetchall()
        if not stale:
            return
        task_ids = [row[0] for row in stale]
        quote_ids = [json.loads(row[1]).get('quote_id') for row in stale]
        db.executemany("DELETE FROM jobs WHERE id=?", ((task_id,) for task_id in task_ids))
        db.executemany("DELETE FROM quotes WHERE id=? AND consumed=1", ((quote_id,) for quote_id in quote_ids if quote_id))

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
