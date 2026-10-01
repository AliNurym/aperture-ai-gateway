"""Durable single-gateway admission, identity, and execution evidence."""
import json
import math
import sqlite3
import threading
import os
import time
from contextlib import contextmanager
from pathlib import Path

ACTIVE_STATES = ("queued", "starting", "running", "settlement_pending")
ACTIVE_STATES_SQL = "('" + "','".join(state.replace("'", "''") for state in ACTIVE_STATES) + "')"

class StateStore:
    def __init__(self, path):
        self.durable_state = str(path) != ":memory:"
        self.process_lock = None
        if self.durable_state:
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
        self.connection.executescript(f"""
          CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, data TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS challenges (id TEXT PRIMARY KEY, data TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, wallet TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL, agent_pubkey TEXT);
          CREATE TABLE IF NOT EXISTS agent_spend (agent_pubkey TEXT PRIMARY KEY, charged_lamports INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS store_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS active_jobs_by_state ON jobs(state)
            WHERE state IN {ACTIVE_STATES_SQL};
          CREATE UNIQUE INDEX IF NOT EXISTS active_wallet ON jobs(wallet)
            WHERE state IN {ACTIVE_STATES_SQL};
        """)
        self._migrate_job_identity_index()
        self._migrate_job_quote_index()
        self.connection.commit()
        self.lock = threading.RLock()
        self._migrate_agent_spend()
        self._migrate_statistics()

    @staticmethod
    def _completion_statistics(job):
        receipt = job.get("receipt") or {}
        elapsed = receipt.get("execution_time")
        elapsed = float(elapsed) if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0 else 0.0
        charged = receipt.get("charged_lamports")
        charged = charged if receipt.get("settlement_type") == "DEVNET" and type(charged) is int and charged >= 0 else 0
        return {
            "tasks_finished": 1,
            "tasks_completed": int(receipt.get("execution_status") == "completed"),
            "total_compute_seconds": elapsed,
            "total_charged_lamports": charged,
        }

    def _migrate_statistics(self):
        """Seed durable totals from retained evidence; older pruned history is unknown."""
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM store_metadata WHERE key='gateway_statistics_v1'").fetchone():
                return
            totals = {"tasks_finished": 0, "tasks_completed": 0,
                      "total_compute_seconds": 0.0, "total_charged_lamports": 0}
            for (raw,) in db.execute("SELECT data FROM jobs WHERE state='completed'"):
                for key, value in self._completion_statistics(json.loads(raw)).items():
                    totals[key] += value
            totals["tracked_since"] = time.time()
            totals["baseline_finished"] = totals["tasks_finished"]
            db.execute("INSERT INTO store_metadata(key,value) VALUES ('gateway_statistics_v1',?)",
                       (json.dumps(totals, sort_keys=True),))

    def telemetry_totals(self):
        with self.lock:
            row = self.connection.execute("SELECT value FROM store_metadata WHERE key='gateway_statistics_v1'").fetchone()
            return json.loads(row[0])

    def _record_completion_statistics(self, db, job):
        row = db.execute("SELECT value FROM store_metadata WHERE key='gateway_statistics_v1'").fetchone()
        totals = json.loads(row[0])
        for key, value in self._completion_statistics(job).items():
            totals[key] += value
        db.execute("UPDATE store_metadata SET value=? WHERE key='gateway_statistics_v1'",
                   (json.dumps(totals, sort_keys=True),))

    def _migrate_job_identity_index(self):
        """Index persisted jobs by the owner and agent that can recover them."""
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        if "agent_pubkey" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN agent_pubkey TEXT")

        missing = self.connection.execute(
            "SELECT id,data FROM jobs WHERE agent_pubkey IS NULL"
        ).fetchall()
        updates = []
        for task_id, raw in missing:
            job = json.loads(raw)
            agent = job.get("agent_pubkey")
            if isinstance(agent, str) and agent:
                updates.append((agent, task_id))
        if updates:
            self.connection.executemany(
                "UPDATE jobs SET agent_pubkey=? WHERE id=?", updates
            )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS jobs_by_owner_agent_state "
            "ON jobs(wallet,agent_pubkey,state)"
        )

    def _migrate_job_quote_index(self):
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        if "quote_id" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN quote_id TEXT")
        updates = []
        for task_id, raw in self.connection.execute("SELECT id,data FROM jobs WHERE quote_id IS NULL"):
            quote_id = json.loads(raw).get("quote_id")
            if isinstance(quote_id, str) and quote_id:
                updates.append((quote_id, task_id))
        self.connection.executemany("UPDATE jobs SET quote_id=? WHERE id=?", updates)
        self.connection.execute("CREATE INDEX IF NOT EXISTS jobs_by_quote ON jobs(quote_id)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS jobs_by_state ON jobs(state)")

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
            elif table == 'challenges' and consumed and value.get('action') in {'usage', 'agent-task-access'}:
                # A live read nonce is a replay guard, not an evictable approval.
                continue
            elif table == 'challenges' or not consumed:
                unused.append(key)
        if remove:
            db.executemany(f"DELETE FROM {table} WHERE id=?", remove)
        # Leave room for the row which the caller is about to insert.
        retained = len(rows) - len(remove) if table == 'challenges' else len(unused)
        overflow = retained - 9_999
        if overflow > 0:
            # Oldest unused approvals can be requested again; never evict a
            # consumed quote while its task may still need exact replay recovery.
            victims = unused[:overflow]
            db.executemany(f"DELETE FROM {table} WHERE id=?", ((key,) for key in victims))
            if len(victims) < overflow:
                raise ValueError("challenge_capacity")

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

    def job_for_quote(self, quote_id):
        with self.lock:
            row = self.connection.execute("SELECT data FROM jobs WHERE quote_id=? ORDER BY rowid LIMIT 1", (quote_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list_active_jobs(self, *, agent_pubkey=None):
        query = f"SELECT data FROM jobs WHERE state IN {ACTIVE_STATES_SQL}"
        params = ()
        if agent_pubkey is not None:
            query += " AND agent_pubkey=?"
            params = (agent_pubkey,)
        with self.lock:
            return [json.loads(row[0]) for row in self.connection.execute(query + " ORDER BY rowid", params)]

    def list_unused_quotes(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.connection.execute("SELECT data FROM quotes WHERE consumed=0")]

    def count_completed_jobs(self):
        with self.lock:
            return self.connection.execute("SELECT COUNT(*) FROM jobs WHERE state='completed'").fetchone()[0]

    def list_agent_jobs(self, owner, agent_pubkey, limit=20, *, cursor=None):
        """Return one bounded, descending page for an owner/agent pair."""
        if type(limit) is not int or not 1 <= limit <= 51:
            raise ValueError("limit must be between 1 and 51")
        with self.lock:
            before_rowid = None
            if cursor is not None:
                anchor = self.connection.execute(
                    "SELECT rowid FROM jobs WHERE id=? AND wallet=? AND agent_pubkey=?",
                    (cursor, owner, agent_pubkey),
                ).fetchone()
                if not anchor:
                    return []
                before_rowid = anchor[0]
            query = (
                "SELECT data FROM jobs WHERE wallet=? AND agent_pubkey=? "
            )
            params = [owner, agent_pubkey]
            if before_rowid is not None:
                query += "AND rowid < ? "
                params.append(before_rowid)
            query += "ORDER BY rowid DESC LIMIT ?"
            params.append(limit)
            rows = self.connection.execute(
                query, tuple(params),
            ).fetchall()
            return [json.loads(row[0]) for row in rows]

    def admit(self, quote_id, job, max_pending, max_active=None):
        """Replay consumption and wallet reservation commit together."""
        with self.transaction() as db:
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state='queued'").fetchone()[0] >= max_pending:
                raise ValueError("queue_full")
            if max_active is not None:
                if max_active < 1:
                    raise ValueError("invalid_active_limit")
                active_count = db.execute(
                    f"SELECT COUNT(*) FROM jobs WHERE state IN {ACTIVE_STATES_SQL}"
                ).fetchone()[0]
                if active_count >= max_active:
                    raise ValueError("active_tasks_full")
            row = db.execute("SELECT consumed FROM quotes WHERE id=?", (quote_id,)).fetchone()
            if not row or row[0]:
                raise ValueError("quote_consumed")
            db.execute("INSERT INTO jobs(id,wallet,state,data,agent_pubkey,quote_id) VALUES (?,?,?,?,?,?)", (job["task_id"], job["wallet"], job["state"], json.dumps(job, sort_keys=True), job.get("agent_pubkey"), job.get("quote_id")))
            db.execute("UPDATE quotes SET consumed=1 WHERE id=?", (quote_id,))

    def consume_challenge(self, challenge_id, agent):
        with self.transaction() as db:
            row = db.execute("SELECT consumed FROM challenges WHERE id=?", (challenge_id,)).fetchone()
            if not row or row[0]:
                raise ValueError("challenge_consumed")
            db.execute("UPDATE challenges SET consumed=1 WHERE id=?", (challenge_id,))
            db.execute("INSERT INTO agents(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (agent["agent_pubkey"], json.dumps(agent, sort_keys=True)))

    def consume_read_nonce(self, nonce, expires_at, scope="usage"):
        """Persist a one-time marker for a signed read request."""
        if scope not in {"usage", "agent-task-access"}:
            raise ValueError("Invalid read nonce scope")
        challenge_id = scope + ":" + nonce
        challenge = {"action": scope, "expires_at": int(expires_at)}
        with self.transaction() as db:
            self._prune_ephemeral(db, "challenges")
            if db.execute("SELECT 1 FROM challenges WHERE id=?", (challenge_id,)).fetchone():
                raise ValueError("read_nonce_consumed")
            db.execute(
                "INSERT INTO challenges(id,data,consumed) VALUES (?,?,1)",
                (challenge_id, json.dumps(challenge, sort_keys=True)),
            )

    def save_job(self, job):
        with self.transaction() as db:
            previous = db.execute("SELECT state FROM jobs WHERE id=?", (job["task_id"],)).fetchone()
            db.execute("INSERT INTO jobs(id,wallet,state,data,agent_pubkey,quote_id) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data,agent_pubkey=excluded.agent_pubkey,quote_id=excluded.quote_id", (job["task_id"], job["wallet"], job["state"], json.dumps(job, sort_keys=True), job.get("agent_pubkey"), job.get("quote_id")))
            if job.get("state") == "completed" and (not previous or previous[0] != "completed"):
                self._record_completion_statistics(db, job)
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
