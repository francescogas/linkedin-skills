"""SQLite persistence: profiles, jobs, drafts (approval queue), schedules.

One file on disk, no server, so it works offline and survives restarts. All
access goes through a lock because the worker, the scheduler and the HTTP
server share the connection.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT, role TEXT, goal TEXT,
  audience TEXT, voice TEXT, profile_text TEXT, created REAL);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, workflow TEXT NOT NULL, profile_id INTEGER, input TEXT,
  status TEXT NOT NULL, steps TEXT NOT NULL DEFAULT '[]', error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0, run_after REAL NOT NULL DEFAULT 0,
  schedule_id INTEGER, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS drafts(
  id INTEGER PRIMARY KEY, job_id INTEGER, profile_id INTEGER, kind TEXT NOT NULL,
  text TEXT NOT NULL, target_url TEXT, status TEXT NOT NULL DEFAULT 'pending',
  result TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS schedules(
  id INTEGER PRIMARY KEY, workflow TEXT NOT NULL, profile_id INTEGER, input TEXT,
  every_minutes INTEGER NOT NULL, next_run REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
"""

_JSON_COLS = {"steps", "result"}


class Store:
    def __init__(self, path: Optional[str] = None):
        data_dir = Path(os.getenv("LINKEDIN_APP_DATA", ROOT / "app" / "data"))
        if path is None:
            data_dir.mkdir(parents=True, exist_ok=True)
            path = str(data_dir / "studio.db")
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            # Crash recovery: anything that was mid-run goes back on the queue;
            # finished steps are kept, so it resumes instead of starting over.
            self.db.execute("UPDATE jobs SET status='queued' WHERE status='running'")
            self.db.commit()

    @staticmethod
    def _row(r: Optional[sqlite3.Row]) -> Optional[dict]:
        if r is None:
            return None
        d = dict(r)
        for c in _JSON_COLS & d.keys():
            d[c] = json.loads(d[c]) if d[c] else None
        return d

    def insert(self, table: str, **vals: Any) -> int:
        for c in _JSON_COLS & vals.keys():
            vals[c] = json.dumps(vals[c])
        cols = ",".join(vals)
        with self.lock:
            cur = self.db.execute(
                f"INSERT INTO {table}({cols}) VALUES({','.join('?' * len(vals))})", list(vals.values())
            )
            self.db.commit()
            return cur.lastrowid

    def update(self, table: str, id: int, **vals: Any) -> None:
        for c in _JSON_COLS & vals.keys():
            vals[c] = json.dumps(vals[c])
        sets = ",".join(f"{k}=?" for k in vals)
        with self.lock:
            self.db.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*vals.values(), id])
            self.db.commit()

    def get(self, table: str, id: int) -> Optional[dict]:
        with self.lock:
            return self._row(self.db.execute(f"SELECT * FROM {table} WHERE id=?", (id,)).fetchone())

    def list(self, table: str, where: str = "1=1", args: tuple = (), order: str = "id DESC", limit: int = 200) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                f"SELECT * FROM {table} WHERE {where} ORDER BY {order} LIMIT ?", (*args, limit)
            ).fetchall()
        return [self._row(r) for r in rows]

    def delete(self, table: str, id: int) -> None:
        with self.lock:
            self.db.execute(f"DELETE FROM {table} WHERE id=?", (id,))
            self.db.commit()

    def claim_job(self) -> Optional[dict]:
        """Atomically take the oldest runnable job."""
        with self.lock:
            r = self.db.execute(
                "SELECT * FROM jobs WHERE status='queued' AND run_after<=? ORDER BY id LIMIT 1", (time.time(),)
            ).fetchone()
            if not r:
                return None
            self.db.execute(
                "UPDATE jobs SET status='running', updated=? WHERE id=?", (time.time(), r["id"])
            )
            self.db.commit()
            return self._row(self.db.execute("SELECT * FROM jobs WHERE id=?", (r["id"],)).fetchone())
