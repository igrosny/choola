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
        name        — human-readable node name shown in the UI.
        category    — grouping label for the sidebar palette (e.g. "routing").
        description — short tooltip text.
        fields      — list of dicts describing the input fields the UI should
                      render.  Each dict has at minimum {"name": ..., "type": ...}.
    """

    name: ClassVar[str] = "Unnamed Node"
    category: ClassVar[str] = "general"
    description: ClassVar[str] = ""
    fields: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, node_id: str | None = None, config: dict[str, Any] | None = None):
        self.node_id: str = node_id or uuid.uuid4().hex[:12]
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
