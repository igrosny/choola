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
@choola-node: DB
@category: processing
@description: Provisions the workflow's SQLite schema. Other nodes then read/write via self.db_query and self.db_execute.
@input-payload:
  - (passes through unchanged)
@output-payload:
  - db_path (str): Absolute path to the workflow's SQLite file
  - (all prior payload keys are preserved)
@config-fields:
  - schema (textarea, required): Idempotent SQL DDL run on every execution (CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS, ...)
@example-input: {}
@example-output: {"db_path": "/abs/path/workflows/demo/files/db.sqlite"}
@side-effects: Creates workflows/<name>/files/db.sqlite if missing; runs the schema DDL against it.
@errors: Missing schema; SQLite errors from invalid DDL.
@cost: free
"""

from __future__ import annotations

from typing import Any

from choola.core.base_node import BaseNode
from choola.database import workflow_db_executescript_async, workflow_db_path


class DB(BaseNode):
    name = "DB"
    category = "processing"
    description = "Provisions the workflow's SQLite schema (tables, indexes)."
    fields = [
        {
            "name": "schema",
            "type": "textarea",
            "required": True,
            "placeholder": "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT);",
            "description": "Idempotent SQL DDL. Runs on every execution.",
        },
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        schema = (self.config.get("schema") or "").strip()
        if not schema:
            raise ValueError("schema is required — configure it in the node settings")

        workflow_name = context["workflow"]
        await workflow_db_executescript_async(workflow_name, schema)

        payload["db_path"] = str(workflow_db_path(workflow_name))
        return payload
