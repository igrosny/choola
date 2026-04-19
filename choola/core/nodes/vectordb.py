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
@choola-node: VectorDB
@category: processing
@description: Provisions the workflow's persistent ChromaDB store. Other nodes then upsert/query via self.vector_add and self.vector_query.
@input-payload:
  - (passes through unchanged)
@output-payload:
  - vectordb_path (str): Absolute path to the workflow's ChromaDB directory
  - collections (list[str]): Names of collections ensured by this node
  - (all prior payload keys are preserved)
@config-fields:
  - collections (json, required): List of collection names, or a list of {name, metadata} dicts. Collections are created if missing and left alone if present.
@example-input: {}
@example-output: {"vectordb_path": "/abs/path/workflows/demo/files/chroma", "collections": ["documents"]}
@side-effects: Creates workflows/<name>/files/chroma/ if missing; calls get_or_create_collection for each configured collection.
@errors: Empty or invalid collections list; ChromaDB errors from invalid collection names/metadata.
@cost: free
"""

from __future__ import annotations

import json
from typing import Any

from choola.core.base_node import BaseNode
from choola.database import (
    workflow_vector_create_collection_async,
    workflow_vectordb_path,
)


class VectorDB(BaseNode):
    name = "VectorDB"
    category = "processing"
    description = "Provisions the workflow's persistent ChromaDB collections."
    fields = [
        {
            "name": "collections",
            "type": "json",
            "required": True,
            "default": '["documents"]',
            "placeholder": '["documents"] or [{"name": "documents", "metadata": {"hnsw:space": "cosine"}}]',
            "description": (
                "Collection names to ensure. Either a list of strings, or a list of "
                "objects with `name` and optional `metadata` (passed to ChromaDB)."
            ),
        },
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        raw = self.config.get("collections")
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                raise ValueError("collections is required — configure it in the node settings")
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"collections must be valid JSON: {e}") from e

        if not isinstance(raw, list) or not raw:
            raise ValueError("collections must be a non-empty list")

        workflow_name = context["workflow"]
        names: list[str] = []
        for entry in raw:
            if isinstance(entry, str):
                name, metadata = entry, None
            elif isinstance(entry, dict) and "name" in entry:
                name = entry["name"]
                metadata = entry.get("metadata")
            else:
                raise ValueError(
                    "Each collection must be a string or an object with a `name` field"
                )
            await workflow_vector_create_collection_async(workflow_name, name, metadata)
            names.append(name)

        payload["vectordb_path"] = str(workflow_vectordb_path(workflow_name))
        payload["collections"] = names
        return payload
