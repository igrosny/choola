# Copyright 2026 Ivan Grosny
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
database.py — SQLite initialization, schema management, and async query wrappers.

Two tables:
  globals   – persistent key/value store accessed by BaseNode helpers.
  run_logs  – execution telemetry (one row per node execution).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

# Database lives in the user's current working directory (project-local).
DB_PATH = Path(os.getcwd()) / "choola.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS globals (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL,
    workflow_name TEXT    NOT NULL,
    node_id       TEXT    NOT NULL,
    node_type     TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'IDLE',
    payload_in    TEXT,
    payload_out   TEXT,
    error         TEXT,
    started_at    TEXT,
    finished_at   TEXT
);

CREATE TABLE IF NOT EXISTS credentials (
    name        TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


# ------------------------------------------------------------------
# Synchronous helpers (used by the CLI and startup)
# ------------------------------------------------------------------
def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def get_global_sync(key: str, db_path: Path = DB_PATH) -> Any:
    conn = get_connection(db_path)
    row = conn.execute("SELECT value FROM globals WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row is None:
        return None
    return json.loads(row["value"])


def set_global_sync(key: str, value: Any, db_path: Path = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO globals (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()
    conn.close()


def insert_run_log(
    run_id: str,
    workflow_name: str,
    node_id: str,
    node_type: str,
    status: str,
    payload_in: Any = None,
    payload_out: Any = None,
    error: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO run_logs
           (run_id, workflow_name, node_id, node_type, status,
            payload_in, payload_out, error, started_at, finished_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            workflow_name,
            node_id,
            node_type,
            status,
            json.dumps(payload_in) if payload_in is not None else None,
            json.dumps(payload_out) if payload_out is not None else None,
            error,
            started_at,
            finished_at,
        ),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# Async wrappers (for use inside BaseNode via the engine)
# ------------------------------------------------------------------
async def get_global_async(key: str, db_path: Path = DB_PATH) -> Any:
    """Async-compatible wrapper — runs sync SQLite in the current thread."""
    return get_global_sync(key, db_path)


async def set_global_async(key: str, value: Any, db_path: Path = DB_PATH) -> None:
    set_global_sync(key, value, db_path)


# ------------------------------------------------------------------
# Credentials helpers
# ------------------------------------------------------------------
def list_credentials(db_path: Path = DB_PATH) -> list[dict]:
    """Return all credentials (value masked)."""
    conn = get_connection(db_path)
    rows = conn.execute("SELECT name, provider, created_at, updated_at FROM credentials ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_credential(name: str, db_path: Path = DB_PATH) -> dict | None:
    """Return a single credential by name (full value included)."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT name, provider, value, created_at, updated_at FROM credentials WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_credential(name: str, provider: str, value: str, db_path: Path = DB_PATH) -> None:
    """Insert or update a credential."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO credentials (name, provider, value, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET provider = excluded.provider,
                                           value = excluded.value,
                                           updated_at = excluded.updated_at""",
        (name, provider, value, now, now),
    )
    conn.commit()
    conn.close()


def delete_credential(name: str, db_path: Path = DB_PATH) -> bool:
    """Delete a credential. Returns True if it existed."""
    conn = get_connection(db_path)
    cursor = conn.execute("DELETE FROM credentials WHERE name = ?", (name,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


async def get_credential_async(name: str, db_path: Path = DB_PATH) -> dict | None:
    """Async-compatible wrapper for get_credential."""
    return get_credential(name, db_path)


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
