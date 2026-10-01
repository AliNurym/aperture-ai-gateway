"""Private immutable job inputs and outputs, separate from execution journals."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import stat
import tempfile
import threading
import time
from pathlib import Path

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 16 * 1024 * 1024
MAX_JOB_INPUTS = 16
MAX_JOB_ARTIFACTS = 16
SAFE_NAME = re.compile(r"^(?!(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$))[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,78}[A-Za-z0-9_-])?$")
OBJECT_ID = re.compile(r"^obj-[0-9a-f]{32}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def validate_descriptor(item):
    if not isinstance(item, dict) or set(item) != {"object_id", "name", "sha256", "size_bytes"}:
        raise ValueError("Object references must contain object_id, name, sha256 and size_bytes.")
    if (not isinstance(item["object_id"], str) or not OBJECT_ID.fullmatch(item["object_id"])
            or not isinstance(item["name"], str) or not SAFE_NAME.fullmatch(item["name"])
            or not isinstance(item["sha256"], str) or not DIGEST.fullmatch(item["sha256"])
            or type(item["size_bytes"]) is not int or not 0 < item["size_bytes"] <= MAX_INPUT_BYTES):
        raise ValueError("Invalid immutable object reference.")
    return dict(item)


class ArtifactStore:
    def __init__(self, root=None):
        self.temporary = tempfile.TemporaryDirectory(prefix="aperture-objects-") if root is None else None
        self.root = Path(root or self.temporary.name).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "objects.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS objects(
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, agent TEXT NOT NULL,
                name TEXT NOT NULL, digest TEXT NOT NULL, size INTEGER NOT NULL,
                token_hash TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
                task_id TEXT
            );
            CREATE INDEX IF NOT EXISTS object_principal ON objects(owner, agent);
            CREATE INDEX IF NOT EXISTS object_task ON objects(task_id);
            CREATE TABLE IF NOT EXISTS released(
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, agent TEXT NOT NULL,
                name TEXT NOT NULL, digest TEXT NOT NULL, size INTEGER NOT NULL, released REAL NOT NULL
            );
        """)
        self.db.commit()
        # The single gateway process owns this store. Interrupted streams may retry.
        for (object_id,) in self.db.execute("SELECT id FROM objects WHERE state='uploading'").fetchall():
            if OBJECT_ID.fullmatch(object_id):
                (self.root / (object_id + ".incoming")).unlink(missing_ok=True)
        self.db.execute("UPDATE objects SET state='authorized' WHERE state='uploading'")
        self.db.commit()
        for (object_id,) in self.db.execute("SELECT id FROM objects WHERE state='deleting'").fetchall():
            if OBJECT_ID.fullmatch(object_id):
                self._finish_release(object_id)

    @staticmethod
    def descriptor(row):
        return {"object_id": row[0], "name": row[3], "sha256": row[4], "size_bytes": row[5]}

    def get(self, object_id):
        if not isinstance(object_id, str) or not OBJECT_ID.fullmatch(object_id):
            raise ValueError("Invalid object identifier.")
        with self.lock:
            row = self.db.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
        if row is None:
            raise ValueError("Object does not exist.")
        return row

    def authorize(self, *, owner, agent, name, digest, size, task_id=None):
        maximum = MAX_ARTIFACT_BYTES if task_id else MAX_INPUT_BYTES
        if (not isinstance(name, str) or not SAFE_NAME.fullmatch(name)
                or not isinstance(digest, str) or not DIGEST.fullmatch(digest)
                or type(size) is not int or not 0 < size <= maximum):
            raise ValueError("Invalid object name, digest or size.")
        with self.lock:
            if task_id:
                existing = self.db.execute(
                    "SELECT * FROM objects WHERE task_id=? AND name=? COLLATE NOCASE", (task_id, name)
                ).fetchone()
                if existing:
                    if (existing[1:3] != (owner, agent) or existing[3] != name
                            or existing[4:6] != (digest, size)):
                        raise ValueError("A different artifact is already registered under this name.")
                    if existing[7] == "ready":
                        return {**self.descriptor(existing), "uploaded": True}
                    if existing[7] == "uploading":
                        raise ValueError("Artifact upload is already in progress.")
                    token = secrets.token_urlsafe(32)
                    self.db.execute("UPDATE objects SET token_hash=? WHERE id=?",
                        (hashlib.sha256(token.encode()).hexdigest(), existing[0]))
                    self.db.commit()
                    return {**self.descriptor(existing), "upload_token": token}
            stale = self.db.execute(
                "SELECT id FROM objects WHERE state='authorized' AND created<?", (time.time() - 3600,)
            ).fetchall()
            for (stale_id,) in stale:
                self.db.execute("UPDATE objects SET state='deleting' WHERE id=?", (stale_id,))
                self.db.commit()
                self._finish_release(stale_id)
            used, count = self.db.execute(
                "SELECT COALESCE(SUM(size),0),COUNT(*) FROM objects WHERE owner=? AND agent=?", (owner, agent)
            ).fetchone()
            total, all_count = self.db.execute("SELECT COALESCE(SUM(size),0),COUNT(*) FROM objects").fetchone()
            if used + size > 256 * 1024 * 1024 or count >= 512 or total + size > 2 * 1024**3 or all_count >= 10_000:
                self.db.commit()
                raise ValueError("Object storage capacity reached.")
            if task_id:
                output_size, output_count = self.db.execute(
                    "SELECT COALESCE(SUM(size),0),COUNT(*) FROM objects WHERE task_id=?", (task_id,)
                ).fetchone()
                if output_size + size > MAX_ARTIFACT_TOTAL_BYTES or output_count >= MAX_JOB_ARTIFACTS:
                    self.db.commit()
                    raise ValueError("Job artifact capacity reached.")
            object_id, token = "obj-" + secrets.token_hex(16), secrets.token_urlsafe(32)
            self.db.execute("INSERT INTO objects VALUES(?,?,?,?,?,?,?,?,?,?)",
                (object_id, owner, agent, name, digest, size, hashlib.sha256(token.encode()).hexdigest(),
                 "authorized", time.time(), task_id))
            self.db.commit()
            return {"object_id": object_id, "name": name, "sha256": digest,
                    "size_bytes": size, "upload_token": token}

    def upload_authorization(self, object_id, token):
        row = self.get(object_id)
        if not isinstance(token, str) or not hmac.compare_digest(
                row[6], hashlib.sha256(token.encode()).hexdigest()):
            raise PermissionError("Invalid upload capability.")
        if row[7] not in {"authorized", "uploading", "ready"}:
            raise PermissionError("Object is no longer available for upload.")
        return row

    async def upload(self, object_id, token, request):
        row = self.upload_authorization(object_id, token)
        with self.lock:
            changed = self.db.execute(
                "UPDATE objects SET state='uploading' WHERE id=? AND state='authorized'", (object_id,)
            ).rowcount
            self.db.commit()
        if not changed:
            if row[7] == "ready":
                return self.descriptor(row)
            raise ValueError("Upload is already in progress.")
        temporary_path = self.root / (object_id + ".incoming")
        final_path = self.root / object_id
        digest, size = hashlib.sha256(), 0
        try:
            with temporary_path.open("xb") as target:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > row[5]:
                        raise ValueError("Upload exceeds its authorized byte count.")
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if size != row[5] or digest.hexdigest() != row[4]:
                raise ValueError("Upload does not match its authorized size and digest.")
            os.replace(temporary_path, final_path)
            with self.lock:
                self.db.execute("UPDATE objects SET state='ready' WHERE id=?", (object_id,))
                self.db.commit()
            return self.descriptor(row)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            with self.lock:
                self.db.execute("UPDATE objects SET state='authorized' WHERE id=?", (object_id,))
                self.db.commit()
            raise

    def resolve(self, item, *, owner, agent, task_id=None):
        item = validate_descriptor(item)
        row = self.get(item["object_id"])
        if (row[1:3] != (owner, agent) or row[7] != "ready"
                or self.descriptor(row) != item or (task_id is not None and row[9] != task_id)):
            raise PermissionError("Object is unavailable for this job identity.")
        path = self.root / row[0]
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != item["size_bytes"]:
            raise ValueError("Stored object is incomplete.")
        return path

    def usage(self, *, owner, agent):
        with self.lock:
            rows = self.db.execute("SELECT * FROM objects WHERE owner=? AND agent=? ORDER BY created",
                                   (owner, agent)).fetchall()
        return {"size_bytes": sum(row[5] for row in rows), "object_count": len(rows),
                "max_size_bytes": 256 * 1024 * 1024, "max_object_count": 512,
                "objects": [{**self.descriptor(row), "state": row[7], "task_id": row[9]} for row in rows]}

    def _finish_release(self, object_id):
        # Object IDs are validated fixed filenames; never recurse into a user path.
        if not isinstance(object_id, str) or not OBJECT_ID.fullmatch(object_id):
            raise ValueError("Invalid object identifier.")
        (self.root / object_id).unlink(missing_ok=True)
        (self.root / (object_id + ".incoming")).unlink(missing_ok=True)
        row = self.db.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
        if row:
            self.db.execute("INSERT OR IGNORE INTO released VALUES(?,?,?,?,?,?,?)", (*row[:6], time.time()))
        self.db.execute("DELETE FROM objects WHERE id=?", (object_id,))
        self.db.execute("DELETE FROM released WHERE released<?", (time.time() - 7 * 86400,))
        self.db.execute("DELETE FROM released WHERE id IN (SELECT id FROM released ORDER BY released DESC LIMIT -1 OFFSET 4096)")
        self.db.commit()

    def release(self, reference, *, owner, agent):
        reference = validate_descriptor(reference)
        object_id = reference["object_id"]
        with self.lock:
            row = self.db.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
            if row is None:
                old = self.db.execute("SELECT * FROM released WHERE id=?", (object_id,)).fetchone()
                if old is None:
                    raise ValueError("Object does not exist.")
                if old[1:3] != (owner, agent):
                    raise PermissionError("Object belongs to another execution identity.")
                if self.descriptor(old) != reference:
                    raise ValueError("Release reference differs from the retained object.")
                return {"object_id": object_id, "status": "released", "size_bytes": old[5]}
            if row[1:3] != (owner, agent):
                raise PermissionError("Object belongs to another execution identity.")
            if self.descriptor(row) != reference:
                raise ValueError("Release reference differs from the retained object.")
            if row[7] == "uploading":
                raise ValueError("An object upload is still in progress.")
            self.db.execute("UPDATE objects SET state='deleting' WHERE id=?", (object_id,))
            self.db.commit()
            self._finish_release(object_id)
        return {"object_id": object_id, "status": "released", "size_bytes": row[5]}

    def close(self):
        self.db.close()
        if self.temporary:
            self.temporary.cleanup()
