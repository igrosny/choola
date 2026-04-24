"""Tests for choola.database.

Grouped by concept: schema init, globals, run_logs, credentials encryption,
per-workflow SQLite, and per-workflow ChromaDB. ChromaDB tests pass pre-
computed embeddings so they never need to download a model.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from choola import database as db


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


def test_init_db_creates_all_tables(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    assert {"globals", "run_logs", "credentials"}.issubset(tables)


def test_init_db_is_idempotent(db_path: Path):
    # Second call must not raise.
    db.init_db(db_path)
    db.init_db(db_path)


def test_init_db_backfills_token_columns(tmp_cwd: Path):
    """An older run_logs table without token columns should be upgraded."""
    path = tmp_cwd / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, workflow_name TEXT, node_id TEXT, node_type TEXT,
            status TEXT, payload_in TEXT, payload_out TEXT, error TEXT,
            started_at TEXT, finished_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    db.init_db(path)

    conn = sqlite3.connect(str(path))
    cols = {c[1] for c in conn.execute("PRAGMA table_info(run_logs)")}
    conn.close()
    assert "prompt_tokens" in cols
    assert "completion_tokens" in cols


# ---------------------------------------------------------------------------
# Globals (sync + async)
# ---------------------------------------------------------------------------


def test_globals_roundtrip_primitive(db_path: Path):
    db.set_global_sync("max_tokens_per_run", 5000, db_path)
    assert db.get_global_sync("max_tokens_per_run", db_path) == 5000


def test_globals_roundtrip_structured(db_path: Path):
    value = {"a": [1, 2, 3], "b": "text"}
    db.set_global_sync("complex", value, db_path)
    assert db.get_global_sync("complex", db_path) == value


def test_globals_upsert_overwrites(db_path: Path):
    db.set_global_sync("key", "first", db_path)
    db.set_global_sync("key", "second", db_path)
    assert db.get_global_sync("key", db_path) == "second"


def test_globals_missing_returns_none(db_path: Path):
    assert db.get_global_sync("nope", db_path) is None


async def test_globals_async_wrappers(db_path: Path):
    await db.set_global_async("k", [1, 2], db_path)
    assert await db.get_global_async("k", db_path) == [1, 2]


# ---------------------------------------------------------------------------
# Run logs
# ---------------------------------------------------------------------------


def test_insert_run_log_serializes_payloads(db_path: Path):
    db.insert_run_log(
        run_id="r1",
        workflow_name="demo",
        node_id="n1",
        node_type="pkg.Node",
        status="COMPLETED",
        payload_in={"in": 1},
        payload_out={"out": 2},
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        prompt_tokens=10,
        completion_tokens=7,
        db_path=db_path,
    )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM run_logs WHERE run_id = ?", ("r1",)).fetchone()
    conn.close()

    assert row["status"] == "COMPLETED"
    assert json.loads(row["payload_in"]) == {"in": 1}
    assert json.loads(row["payload_out"]) == {"out": 2}
    assert row["prompt_tokens"] == 10
    assert row["completion_tokens"] == 7


def test_insert_run_log_handles_none_payloads(db_path: Path):
    db.insert_run_log(
        run_id="r2",
        workflow_name="demo",
        node_id="n",
        node_type="t",
        status="ERROR",
        error="boom",
        db_path=db_path,
    )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM run_logs WHERE run_id = ?", ("r2",)).fetchone()
    conn.close()

    assert row["payload_in"] is None
    assert row["payload_out"] is None
    assert row["error"] == "boom"
    # Defaults: 0 tokens
    assert row["prompt_tokens"] == 0
    assert row["completion_tokens"] == 0


# ---------------------------------------------------------------------------
# Credentials encryption
# ---------------------------------------------------------------------------


def test_upsert_and_get_credential_decrypts_value(db_path: Path):
    db.upsert_credential("key1", "anthropic", "sk-secret", db_path)
    cred = db.get_credential("key1", db_path)
    assert cred is not None
    assert cred["name"] == "key1"
    assert cred["provider"] == "anthropic"
    assert cred["value"] == "sk-secret"
    assert "created_at" in cred and "updated_at" in cred


def test_credential_value_is_encrypted_at_rest(db_path: Path):
    db.upsert_credential("key1", "anthropic", "sk-secret", db_path)
    # Read raw value directly, bypass decryption.
    conn = sqlite3.connect(str(db_path))
    raw = conn.execute("SELECT value FROM credentials WHERE name = ?", ("key1",)).fetchone()[0]
    conn.close()
    assert raw != "sk-secret"
    assert "sk-secret" not in raw


def test_upsert_overwrites_existing_credential(db_path: Path):
    db.upsert_credential("key1", "anthropic", "v1", db_path)
    db.upsert_credential("key1", "google", "v2", db_path)

    cred = db.get_credential("key1", db_path)
    assert cred["value"] == "v2"
    assert cred["provider"] == "google"


def test_get_credential_missing_returns_none(db_path: Path):
    assert db.get_credential("absent", db_path) is None


def test_delete_credential_returns_existence_flag(db_path: Path):
    db.upsert_credential("k", "p", "v", db_path)
    assert db.delete_credential("k", db_path) is True
    assert db.delete_credential("k", db_path) is False
    assert db.get_credential("k", db_path) is None


def test_list_credentials_masks_values(db_path: Path):
    db.upsert_credential("alpha", "anthropic", "secret-a", db_path)
    db.upsert_credential("beta", "google", "secret-b", db_path)

    creds = db.list_credentials(db_path)
    names = [c["name"] for c in creds]
    assert names == ["alpha", "beta"]  # sorted by name
    for c in creds:
        assert "value" not in c  # value is intentionally NOT returned


def test_get_credential_falls_back_to_plaintext_for_pre_encryption_rows(db_path: Path):
    """Legacy rows written before encryption landed must still decode."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO credentials (name, provider, value, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("legacy", "anthropic", "plain-value", "2024-01-01", "2024-01-01"),
    )
    conn.commit()
    conn.close()

    cred = db.get_credential("legacy", db_path)
    assert cred["value"] == "plain-value"


async def test_get_credential_async_wrapper(db_path: Path):
    db.upsert_credential("k", "anthropic", "v", db_path)
    cred = await db.get_credential_async("k", db_path)
    assert cred["value"] == "v"


# ---------------------------------------------------------------------------
# Encryption key resolution
# ---------------------------------------------------------------------------


def test_encryption_key_prefers_env(monkeypatch, tmp_cwd: Path):
    from cryptography.fernet import Fernet

    env_key = Fernet.generate_key()
    monkeypatch.setenv("CHOOLA_SECRET_KEY", env_key.decode())
    db._FERNET_CACHE = None
    assert db.get_encryption_key() == env_key


def test_encryption_key_reads_from_keyfile_when_env_absent(
    monkeypatch, tmp_cwd: Path
):
    from cryptography.fernet import Fernet

    monkeypatch.delenv("CHOOLA_SECRET_KEY", raising=False)
    key_file = tmp_cwd / ".choola_key"
    key = Fernet.generate_key()
    key_file.write_bytes(key)

    db._FERNET_CACHE = None
    assert db.get_encryption_key() == key


def test_encryption_key_generates_and_persists_when_missing(
    monkeypatch, tmp_cwd: Path
):
    monkeypatch.delenv("CHOOLA_SECRET_KEY", raising=False)
    db._FERNET_CACHE = None
    key_file = tmp_cwd / ".choola_key"
    assert not key_file.exists()

    k1 = db.get_encryption_key()
    assert key_file.exists()
    assert key_file.read_bytes().strip() == k1

    # Second call returns the same persisted key.
    db._FERNET_CACHE = None
    assert db.get_encryption_key() == k1


# ---------------------------------------------------------------------------
# Per-workflow SQLite
# ---------------------------------------------------------------------------


def test_workflow_db_path_creates_files_dir(tmp_cwd: Path):
    path = db.workflow_db_path("demo")
    assert path == tmp_cwd / "workflows" / "demo" / "files" / "db.sqlite"
    assert path.parent.exists()


async def test_workflow_db_executescript_then_query(tmp_cwd: Path):
    await db.workflow_db_executescript_async(
        "demo",
        "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT);",
    )

    rowcount = await db.workflow_db_execute_async(
        "demo", "INSERT INTO items (name) VALUES (?)", ("widget",)
    )
    assert rowcount == 1

    rows = await db.workflow_db_query_async("demo", "SELECT name FROM items", ())
    assert rows == [{"id": 1, "name": "widget"}] or rows == [{"name": "widget"}]


async def test_workflow_db_query_parameter_binding(tmp_cwd: Path):
    await db.workflow_db_executescript_async(
        "demo",
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);",
    )
    await db.workflow_db_execute_async(
        "demo", "INSERT INTO items (name) VALUES (?)", ("a",)
    )
    await db.workflow_db_execute_async(
        "demo", "INSERT INTO items (name) VALUES (?)", ("b",)
    )
    rows = await db.workflow_db_query_async(
        "demo", "SELECT name FROM items WHERE name = ?", ("a",)
    )
    assert [r["name"] for r in rows] == ["a"]


async def test_workflow_db_is_isolated_per_workflow(tmp_cwd: Path):
    await db.workflow_db_executescript_async(
        "wf_a", "CREATE TABLE items (id INTEGER PRIMARY KEY);"
    )
    await db.workflow_db_executescript_async(
        "wf_b", "CREATE TABLE items (id INTEGER PRIMARY KEY);"
    )
    await db.workflow_db_execute_async(
        "wf_a", "INSERT INTO items (id) VALUES (?)", (1,)
    )

    assert (
        await db.workflow_db_query_async("wf_a", "SELECT COUNT(*) AS c FROM items")
    )[0]["c"] == 1
    assert (
        await db.workflow_db_query_async("wf_b", "SELECT COUNT(*) AS c FROM items")
    )[0]["c"] == 0


# ---------------------------------------------------------------------------
# Per-workflow ChromaDB
# ---------------------------------------------------------------------------
# chromadb's default embedder downloads ~80MB on first use. Every test here
# passes explicit embeddings so nothing is ever downloaded.


async def test_vector_add_and_count(tmp_cwd: Path):
    await db.workflow_vector_create_collection_async("demo", "docs")

    n = await db.workflow_vector_add_async(
        "demo",
        "docs",
        ids=["a", "b"],
        embeddings=[[0.1, 0.2], [0.3, 0.4]],
        metadatas=[{"src": "x"}, {"src": "y"}],
    )
    assert n == 2
    assert await db.workflow_vector_count_async("demo", "docs") == 2


async def test_vector_query_returns_nearest(tmp_cwd: Path):
    await db.workflow_vector_create_collection_async("demo", "docs")
    await db.workflow_vector_add_async(
        "demo",
        "docs",
        ids=["a", "b"],
        embeddings=[[0.0, 0.0], [10.0, 10.0]],
    )

    result = await db.workflow_vector_query_async(
        "demo", "docs", query_embeddings=[[0.01, 0.01]], n_results=1
    )
    # Chroma returns list-of-lists keyed per-query.
    assert result["ids"] == [["a"]]


async def test_vector_get_delete_and_filter(tmp_cwd: Path):
    await db.workflow_vector_create_collection_async("demo", "docs")
    await db.workflow_vector_add_async(
        "demo",
        "docs",
        ids=["a", "b", "c"],
        embeddings=[[0.0], [1.0], [2.0]],
        metadatas=[{"group": "x"}, {"group": "x"}, {"group": "y"}],
    )

    got = await db.workflow_vector_get_async("demo", "docs", where={"group": "x"})
    assert set(got["ids"]) == {"a", "b"}

    await db.workflow_vector_delete_async("demo", "docs", ids=["a"])
    assert await db.workflow_vector_count_async("demo", "docs") == 2


async def test_vector_list_collections(tmp_cwd: Path):
    await db.workflow_vector_create_collection_async("demo", "alpha")
    await db.workflow_vector_create_collection_async("demo", "beta")
    lst = await db.workflow_vector_list_collections_async("demo")
    names = {c["name"] for c in lst}
    assert {"alpha", "beta"}.issubset(names)


async def test_vector_store_isolated_per_workflow(tmp_cwd: Path):
    await db.workflow_vector_create_collection_async("wf_a", "docs")
    await db.workflow_vector_add_async(
        "wf_a", "docs", ids=["x"], embeddings=[[0.1]]
    )
    await db.workflow_vector_create_collection_async("wf_b", "docs")

    assert await db.workflow_vector_count_async("wf_a", "docs") == 1
    assert await db.workflow_vector_count_async("wf_b", "docs") == 0
