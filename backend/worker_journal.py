"""Durable result outbox and execution recovery; contains no worker credentials."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path


class WorkerJournal:
    def __init__(self, state_root: Path):
        state_root.mkdir(parents=True, exist_ok=True)
        try:
            state_root.chmod(0o700)
        except OSError:
            pass
        self.connection = sqlite3.connect(state_root / "worker.sqlite3")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS jobs (task_id TEXT PRIMARY KEY, state TEXT NOT NULL, "
            "task_json TEXT NOT NULL, result_json TEXT, started REAL NOT NULL, "
            "next_attempt REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT)"
        )
        self.connection.commit()

    def begin(self, task: dict):
        # PRIMARY KEY prohibits accidental execution of a locally completed task.
        self.connection.execute(
            "INSERT INTO jobs(task_id,state,task_json,started) VALUES(?,?,?,?)",
            (task["task_id"], "running", json.dumps(task), time.time()),
        )
        self.connection.commit()

    def finish(self, task_id: str, payload: dict):
        self.connection.execute(
            "UPDATE jobs SET state='pending',result_json=?,next_attempt=0 WHERE task_id=?",
            (json.dumps(payload, ensure_ascii=False), task_id),
        )
        self.connection.commit()

    def running(self):
        return [(json.loads(row[0]), row[1]) for row in self.connection.execute(
            "SELECT task_json,started FROM jobs WHERE state='running'"
        )]

    def pending(self, now=None):
        now = time.time() if now is None else now
        return [json.loads(row[0]) for row in self.connection.execute(
            "SELECT result_json FROM jobs WHERE state='pending' AND next_attempt<=? ORDER BY started", (now,)
        )]

    def task(self, task_id):
        row = self.connection.execute("SELECT task_json FROM jobs WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError("Worker journal no longer contains this task.")
        return json.loads(row[0])

    def acknowledge(self, task_id):
        self.connection.execute("DELETE FROM jobs WHERE task_id=?", (task_id,))
        self.connection.commit()

    def retry(self, task_id: str, reason: str):
        attempts = self.connection.execute("SELECT attempts FROM jobs WHERE task_id=?", (task_id,)).fetchone()[0] + 1
        delay = min(30, 2 ** min(attempts, 5))
        self.connection.execute(
            "UPDATE jobs SET attempts=?,next_attempt=?,last_error=? WHERE task_id=?",
            (attempts, time.time() + delay, reason[:500], task_id),
        )
        self.connection.commit()

    def blocked(self):
        return bool(self.connection.execute("SELECT 1 FROM jobs LIMIT 1").fetchone())

    def close(self):
        self.connection.close()


class WorkerInstanceLock:
    """One coordinator per state directory; prevents double claims on restart."""
    def __init__(self, state_root: Path):
        state_root.mkdir(parents=True, exist_ok=True)
        self.handle = open(state_root / "coordinator.lock", "a+b")
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise RuntimeError("Another worker is already using this state directory.") from exc

    def close(self):
        if self.handle.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def container_name(node_id: str, task_id: str) -> str:
    digest = hashlib.sha256(f"{node_id}:{task_id}".encode("utf-8")).hexdigest()[:32]
    return f"aperture-task-{digest}"
