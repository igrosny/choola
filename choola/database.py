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

from cryptography.fernet import Fernet, InvalidToken

# Database lives in the user's current working directory (project-local).
DB_PATH = Path(os.getcwd()) / "choola.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS globals (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT    NOT NULL,
    workflow_name    TEXT    NOT NULL,
    node_id          TEXT    NOT NULL,
    node_type        TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'IDLE',
    payload_in       TEXT,
    payload_out      TEXT,
    error            TEXT,
    started_at       TEXT,
    finished_at      TEXT,
    prompt_tokens    INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_run_logs_started_at ON run_logs(started_at);

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
    # Backfill token columns on pre-existing run_logs tables.
    existing_cols = {c["name"] for c in conn.execute("PRAGMA table_info(run_logs)").fetchall()}
    if "prompt_tokens" not in existing_cols:
        conn.execute("ALTER TABLE run_logs ADD COLUMN prompt_tokens INTEGER DEFAULT 0")
    if "completion_tokens" not in existing_cols:
        conn.execute("ALTER TABLE run_logs ADD COLUMN completion_tokens INTEGER DEFAULT 0")
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
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    db_path: Path = DB_PATH,
) -> None:
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO run_logs
           (run_id, workflow_name, node_id, node_type, status,
            payload_in, payload_out, error, started_at, finished_at,
            prompt_tokens, completion_tokens)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            int(prompt_tokens or 0),
            int(completion_tokens or 0),
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
# Credentials encryption — zero-config key manager
# ------------------------------------------------------------------
_FERNET_CACHE: Fernet | None = None


def get_encryption_key() -> bytes:
    """Resolve the Fernet key from env, a local keyfile, or by generating one.

    Precedence:
      1. CHOOLA_SECRET_KEY env var.
      2. .choola_key file in the current working directory.
      3. Freshly generated key written to .choola_key (0600 when possible).
    """
    env_key = os.environ.get("CHOOLA_SECRET_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key

    key_file = Path.cwd() / ".choola_key"
    if key_file.exists():
        return key_file.read_bytes().strip()

    key = Fernet.generate_key()
    key_file.write_bytes(key)
    try:
        os.chmod(key_file, 0o600)
    except (OSError, NotImplementedError):
        pass
    return key


def _get_fernet() -> Fernet:
    global _FERNET_CACHE
    if _FERNET_CACHE is None:
        _FERNET_CACHE = Fernet(get_encryption_key())
    return _FERNET_CACHE


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
    """Return a single credential by name (full value included, decrypted)."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT name, provider, value, created_at, updated_at FROM credentials WHERE name = ?", (name,)).fetchone()
    conn.close()
    if row is None:
        return None
    record = dict(row)
    stored = record["value"]
    try:
        record["value"] = _get_fernet().decrypt(stored.encode()).decode()
    except InvalidToken:
        # Pre-encryption plaintext credential — return as-is for backward compat.
        record["value"] = stored
    return record


def upsert_credential(name: str, provider: str, value: str, db_path: Path = DB_PATH) -> None:
    """Insert or update a credential. The value is encrypted at rest."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    encrypted = _get_fernet().encrypt(value.encode()).decode()
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO credentials (name, provider, value, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET provider = excluded.provider,
                                           value = excluded.value,
                                           updated_at = excluded.updated_at""",
        (name, provider, encrypted, now, now),
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


# ------------------------------------------------------------------
# Per-workflow SQLite (one DB per workflow, at files/db.sqlite)
# ------------------------------------------------------------------
def workflow_db_path(workflow_name: str) -> Path:
    """Return the path to the workflow's SQLite file, creating files/ if missing."""
    files_dir = Path.cwd() / "workflows" / workflow_name / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    return files_dir / "db.sqlite"


def _workflow_db_query_sync(workflow_name: str, sql: str, params: tuple | list) -> list[dict]:
    conn = get_connection(workflow_db_path(workflow_name))
    try:
        return [dict(r) for r in conn.execute(sql, params or ()).fetchall()]
    finally:
        conn.close()


def _workflow_db_execute_sync(workflow_name: str, sql: str, params: tuple | list) -> int:
    conn = get_connection(workflow_db_path(workflow_name))
    try:
        cur = conn.execute(sql, params or ())
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _workflow_db_executescript_sync(workflow_name: str, sql: str) -> None:
    conn = get_connection(workflow_db_path(workflow_name))
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


async def workflow_db_query_async(
    workflow_name: str, sql: str, params: tuple | list = ()
) -> list[dict]:
    return _workflow_db_query_sync(workflow_name, sql, params)


async def workflow_db_execute_async(
    workflow_name: str, sql: str, params: tuple | list = ()
) -> int:
    return _workflow_db_execute_sync(workflow_name, sql, params)


async def workflow_db_executescript_async(workflow_name: str, sql: str) -> None:
    _workflow_db_executescript_sync(workflow_name, sql)


# ------------------------------------------------------------------
# Per-workflow ChromaDB (persistent vector store at files/chroma/)
# ------------------------------------------------------------------
# Cached per-workflow PersistentClient — chromadb keeps the store consistent
# across multiple clients against the same path, but reusing a single client
# avoids the repeated startup cost on every call.
_vector_clients: dict[str, Any] = {}


def workflow_vectordb_path(workflow_name: str) -> Path:
    """Return the directory that holds the workflow's ChromaDB persistent store."""
    chroma_dir = Path.cwd() / "workflows" / workflow_name / "files" / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)
    return chroma_dir


def _workflow_vector_client(workflow_name: str):
    client = _vector_clients.get(workflow_name)
    if client is not None:
        return client
    import chromadb
    client = chromadb.PersistentClient(path=str(workflow_vectordb_path(workflow_name)))
    _vector_clients[workflow_name] = client
    return client


def _workflow_vector_collection(workflow_name: str, collection: str, create: bool = True):
    client = _workflow_vector_client(workflow_name)
    if create:
        return client.get_or_create_collection(name=collection)
    return client.get_collection(name=collection)


def _workflow_vector_add_sync(
    workflow_name: str,
    collection: str,
    ids: list[str],
    documents: list[str] | None,
    metadatas: list[dict] | None,
    embeddings: list[list[float]] | None,
) -> int:
    col = _workflow_vector_collection(workflow_name, collection, create=True)
    kwargs: dict[str, Any] = {"ids": ids}
    if documents is not None:
        kwargs["documents"] = documents
    if metadatas is not None:
        kwargs["metadatas"] = metadatas
    if embeddings is not None:
        kwargs["embeddings"] = embeddings
    col.upsert(**kwargs)
    return len(ids)


def _workflow_vector_query_sync(
    workflow_name: str,
    collection: str,
    query_texts: list[str] | None,
    query_embeddings: list[list[float]] | None,
    n_results: int,
    where: dict | None,
    where_document: dict | None,
) -> dict:
    col = _workflow_vector_collection(workflow_name, collection, create=False)
    kwargs: dict[str, Any] = {"n_results": n_results}
    if query_texts is not None:
        kwargs["query_texts"] = query_texts
    if query_embeddings is not None:
        kwargs["query_embeddings"] = query_embeddings
    if where is not None:
        kwargs["where"] = where
    if where_document is not None:
        kwargs["where_document"] = where_document
    return col.query(**kwargs)


def _workflow_vector_get_sync(
    workflow_name: str,
    collection: str,
    ids: list[str] | None,
    where: dict | None,
    limit: int | None,
) -> dict:
    col = _workflow_vector_collection(workflow_name, collection, create=False)
    kwargs: dict[str, Any] = {}
    if ids is not None:
        kwargs["ids"] = ids
    if where is not None:
        kwargs["where"] = where
    if limit is not None:
        kwargs["limit"] = limit
    return col.get(**kwargs)


def _workflow_vector_delete_sync(
    workflow_name: str,
    collection: str,
    ids: list[str] | None,
    where: dict | None,
) -> None:
    col = _workflow_vector_collection(workflow_name, collection, create=False)
    kwargs: dict[str, Any] = {}
    if ids is not None:
        kwargs["ids"] = ids
    if where is not None:
        kwargs["where"] = where
    col.delete(**kwargs)


def _workflow_vector_count_sync(workflow_name: str, collection: str) -> int:
    col = _workflow_vector_collection(workflow_name, collection, create=False)
    return col.count()


def _workflow_vector_create_collection_sync(
    workflow_name: str, collection: str, metadata: dict | None
) -> None:
    client = _workflow_vector_client(workflow_name)
    client.get_or_create_collection(name=collection, metadata=metadata or None)


def _workflow_vector_list_collections_sync(workflow_name: str) -> list[dict]:
    client = _workflow_vector_client(workflow_name)
    out: list[dict] = []
    for col in client.list_collections():
        try:
            instance = client.get_collection(name=col.name)
            count = instance.count()
        except Exception:
            count = None
        out.append({"name": col.name, "metadata": dict(col.metadata or {}), "count": count})
    return out


async def workflow_vector_add_async(
    workflow_name: str,
    collection: str,
    ids: list[str],
    documents: list[str] | None = None,
    metadatas: list[dict] | None = None,
    embeddings: list[list[float]] | None = None,
) -> int:
    return _workflow_vector_add_sync(
        workflow_name, collection, ids, documents, metadatas, embeddings
    )


async def workflow_vector_query_async(
    workflow_name: str,
    collection: str,
    query_texts: list[str] | None = None,
    query_embeddings: list[list[float]] | None = None,
    n_results: int = 10,
    where: dict | None = None,
    where_document: dict | None = None,
) -> dict:
    return _workflow_vector_query_sync(
        workflow_name, collection, query_texts, query_embeddings,
        n_results, where, where_document,
    )


async def workflow_vector_get_async(
    workflow_name: str,
    collection: str,
    ids: list[str] | None = None,
    where: dict | None = None,
    limit: int | None = None,
) -> dict:
    return _workflow_vector_get_sync(workflow_name, collection, ids, where, limit)


async def workflow_vector_delete_async(
    workflow_name: str,
    collection: str,
    ids: list[str] | None = None,
    where: dict | None = None,
) -> None:
    _workflow_vector_delete_sync(workflow_name, collection, ids, where)


async def workflow_vector_count_async(workflow_name: str, collection: str) -> int:
    return _workflow_vector_count_sync(workflow_name, collection)


async def workflow_vector_create_collection_async(
    workflow_name: str, collection: str, metadata: dict | None = None
) -> None:
    _workflow_vector_create_collection_sync(workflow_name, collection, metadata)


async def workflow_vector_list_collections_async(workflow_name: str) -> list[dict]:
    return _workflow_vector_list_collections_sync(workflow_name)


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
