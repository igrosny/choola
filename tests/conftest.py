"""Shared pytest fixtures for the Choola test suite.

Most Choola modules resolve filesystem paths off `Path.cwd()` at call time
(`choola.db` in the CWD, `workflows/<name>/files/...`, etc.) so the dominant
fixture here is `tmp_cwd`, which builds an isolated working directory and
initializes the database inside it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure the repo root is importable when the test suite is invoked via
# `pytest` directly (without `pip install -e .`).
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


_DB_FN_NAMES = (
    "get_connection",
    "init_db",
    "get_global_sync",
    "set_global_sync",
    "insert_run_log",
    "get_global_async",
    "set_global_async",
    "list_credentials",
    "get_credential",
    "upsert_credential",
    "delete_credential",
    "get_credential_async",
)


def _rebind_db_path_default(module, fn_name: str, new_path: Path) -> None:
    """Replace the trailing ``db_path=DB_PATH`` default on a module function.

    The Choola db-layer captures `DB_PATH = Path(os.getcwd()) / "choola.db"` at
    import time and bakes it into every helper's default arguments. Tests that
    change CWD must also rebind those defaults, otherwise helpers called
    without an explicit `db_path` will hit the original import-time location.
    """
    fn = getattr(module, fn_name)
    if not fn.__defaults__:
        return
    new_defaults = list(fn.__defaults__)
    new_defaults[-1] = new_path
    fn.__defaults__ = tuple(new_defaults)


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chdir into an isolated temp directory and initialize an empty DB there.

    Also resets database-module caches that pin to the first key seen
    (`_FERNET_CACHE`) and to workflow-scoped Chroma clients, and rebinds the
    default `db_path=DB_PATH` argument of every database helper.
    """
    monkeypatch.chdir(tmp_path)

    # Provide a deterministic Fernet key so credentials encryption is stable
    # across tests (and doesn't write a .choola_key file in the repo).
    from cryptography.fernet import Fernet

    monkeypatch.setenv("CHOOLA_SECRET_KEY", Fernet.generate_key().decode())

    import choola.database as db
    from choola import tokens

    # Reset module-level caches that would otherwise leak state between tests.
    db._FERNET_CACHE = None
    db._vector_clients.clear()

    new_path = tmp_path / "choola.db"

    # Snapshot original defaults so we can restore them on teardown.
    originals: list[tuple[object, str, tuple]] = []
    for name in _DB_FN_NAMES:
        fn = getattr(db, name)
        if fn.__defaults__:
            originals.append((db, name, fn.__defaults__))
            _rebind_db_path_default(db, name, new_path)
    for name in ("_rolling_hour_total", "check_limits"):
        fn = getattr(tokens, name)
        if fn.__defaults__:
            originals.append((tokens, name, fn.__defaults__))
            _rebind_db_path_default(tokens, name, new_path)

    # Module-level constants — harmless to keep in sync, helps any code that
    # reads the attribute directly rather than via a default.
    monkeypatch.setattr(db, "DB_PATH", new_path)
    monkeypatch.setattr(tokens, "DB_PATH", new_path)

    db.init_db(new_path)

    yield tmp_path

    for module, name, defaults in originals:
        getattr(module, name).__defaults__ = defaults


@pytest.fixture
def db_path(tmp_cwd: Path) -> Path:
    """The initialized choola.db inside the isolated CWD."""
    return tmp_cwd / "choola.db"


@pytest.fixture(autouse=True)
def _clear_token_tally():
    """Reset the in-memory per-run token tally between tests."""
    from choola import tokens

    tokens._run_tallies.clear()
    yield
    tokens._run_tallies.clear()
