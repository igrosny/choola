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
BaseNode — the foundational class contract that every workflow node must inherit.

Handles UUID generation, I/O routing, and provides helpers for persistent
global variables stored in SQLite.
"""

from __future__ import annotations

import abc
import uuid
from typing import Any, ClassVar


class BaseNode(abc.ABC):
    """Abstract base class for all Choola workflow nodes.

    Class-level attributes (override in subclasses):
        node_id     — unique identifier for this node within a workflow (snake_case).
        name        — human-readable node name shown in the UI.
        category    — grouping label for the sidebar palette (e.g. "routing").
        description — short tooltip text.
        fields      — list of dicts describing the input fields the UI should
                      render.  Each dict has at minimum {"name": ..., "type": ...}.
        next_nodes  — list of node_id strings this node passes its output to.
    """

    node_id: ClassVar[str] = ""
    name: ClassVar[str] = "Unnamed Node"
    category: ClassVar[str] = "general"
    description: ClassVar[str] = ""
    fields: ClassVar[list[dict[str, Any]]] = []
    next_nodes: ClassVar[list[str]] = []

    def __init__(self, node_id: str | None = None, config: dict[str, Any] | None = None):
        self.node_id: str = node_id or self.__class__.node_id or uuid.uuid4().hex[:12]
        # Merge defaults from fields with the supplied config.
        # Priority: topology/modal config > field defaults
        defaults = {
            f["name"]: f["default"]
            for f in self.__class__.fields
            if "default" in f
        }
        defaults.update(config or {})
        self.config: dict[str, Any] = defaults
        # Injected at execution time by the engine
        self._db_get_global = None
        self._db_set_global = None
        self._db_get_credential = None
        self._db_query = None
        self._db_execute = None
        self._vector_add = None
        self._vector_query = None
        self._vector_get = None
        self._vector_delete = None
        self._vector_count = None

    # ------------------------------------------------------------------
    # Persistent global helpers (backed by SQLite via the engine)
    # ------------------------------------------------------------------
    async def get_global(self, key: str) -> Any:
        """Retrieve a persistent global variable from the SQLite store."""
        if self._db_get_global is None:
            raise RuntimeError("Database helpers not injected — run via the engine.")
        return await self._db_get_global(key)

    async def set_global(self, key: str, value: Any) -> None:
        """Persist a global variable into the SQLite store."""
        if self._db_set_global is None:
            raise RuntimeError("Database helpers not injected — run via the engine.")
        await self._db_set_global(key, value)

    async def get_credential(self, name: str) -> dict | None:
        """Retrieve a stored credential by name.

        Returns a dict with keys: name, provider, value, created_at, updated_at.
        Returns None if the credential does not exist.
        """
        if self._db_get_credential is None:
            raise RuntimeError("Database helpers not injected — run via the engine.")
        return await self._db_get_credential(name)

    # ------------------------------------------------------------------
    # Per-workflow SQLite helpers (files/db.sqlite)
    # ------------------------------------------------------------------
    async def db_query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        """Run a SELECT against the workflow's SQLite DB; return list of dicts."""
        if self._db_query is None:
            raise RuntimeError("Database helpers not injected — run via the engine.")
        return await self._db_query(sql, params)

    async def db_execute(self, sql: str, params: tuple | list = ()) -> int:
        """Run an INSERT/UPDATE/DELETE against the workflow's SQLite DB; return rowcount."""
        if self._db_execute is None:
            raise RuntimeError("Database helpers not injected — run via the engine.")
        return await self._db_execute(sql, params)

    # ------------------------------------------------------------------
    # Per-workflow ChromaDB helpers (files/chroma/)
    # ------------------------------------------------------------------
    async def vector_add(
        self,
        collection: str,
        ids: list[str],
        documents: list[str] | None = None,
        metadatas: list[dict] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> int:
        """Upsert vectors into the workflow's ChromaDB collection.

        Either `documents` (auto-embedded) or `embeddings` (pre-computed) must
        be supplied — ChromaDB will raise if both are None. `ids` must be
        unique per item and are used as the upsert key.
        """
        if self._vector_add is None:
            raise RuntimeError("Vector helpers not injected — run via the engine.")
        return await self._vector_add(collection, ids, documents, metadatas, embeddings)

    async def vector_query(
        self,
        collection: str,
        query_texts: list[str] | None = None,
        query_embeddings: list[list[float]] | None = None,
        n_results: int = 10,
        where: dict | None = None,
        where_document: dict | None = None,
    ) -> dict:
        """Query the workflow's ChromaDB collection for nearest neighbours.

        Returns a ChromaDB query result dict with keys `ids`, `documents`,
        `metadatas`, `distances`, `embeddings` (each a list-of-lists keyed
        per-query).
        """
        if self._vector_query is None:
            raise RuntimeError("Vector helpers not injected — run via the engine.")
        return await self._vector_query(
            collection, query_texts, query_embeddings, n_results, where, where_document
        )

    async def vector_get(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
        limit: int | None = None,
    ) -> dict:
        """Fetch items from a collection by id or metadata filter (no similarity search)."""
        if self._vector_get is None:
            raise RuntimeError("Vector helpers not injected — run via the engine.")
        return await self._vector_get(collection, ids, where, limit)

    async def vector_delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
    ) -> None:
        """Delete items from a collection by id or metadata filter."""
        if self._vector_delete is None:
            raise RuntimeError("Vector helpers not injected — run via the engine.")
        await self._vector_delete(collection, ids, where)

    async def vector_count(self, collection: str) -> int:
        """Return the number of items in a collection."""
        if self._vector_count is None:
            raise RuntimeError("Vector helpers not injected — run via the engine.")
        return await self._vector_count(collection)

    # ------------------------------------------------------------------
    # Contract — subclasses MUST implement
    # ------------------------------------------------------------------
    @abc.abstractmethod
    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Run the node's logic.

        Args:
            payload:  data flowing through the workflow (mutable between nodes).
            context:  read-only execution metadata (workflow name, run id, etc.).

        Returns:
            The (possibly mutated) payload dict to pass downstream.
        """
        ...

    # ------------------------------------------------------------------
    # UI metadata (consumed by /api/nodes)
    # ------------------------------------------------------------------
    @classmethod
    def ui_metadata(cls) -> dict[str, Any]:
        return {
            "type": f"{cls.__module__}.{cls.__name__}",
            "name": cls.name,
            "category": cls.category,
            "description": cls.description,
            "fields": cls.fields,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.node_id}>"
