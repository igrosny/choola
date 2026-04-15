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
@choola-node: Trigger
@category: input
@description: Abstract base for all trigger nodes. Every workflow must have exactly one Trigger as its entry point.
@input-payload:
  - (none — trigger nodes are entry points)
@output-payload:
  - triggered_at (str): ISO timestamp when the workflow was triggered
@config-fields:
  - (none — subclasses define their own)
@example-input: {}
@example-output: {"triggered_at": "2026-04-15T10:30:00Z"}
@side-effects: none
@errors: none
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from choola.core.base_node import BaseNode


class Trigger(BaseNode):
    """Abstract base class for all trigger nodes.

    Every workflow must start with exactly one node that inherits from Trigger.
    Subclasses should override `execute()` to inject trigger-specific data
    (e.g. HTTP request data, form submissions, schedule metadata).
    """

    name = "Trigger"
    category = "input"
    description = "Base trigger node — every workflow starts with one."
    fields: list[dict[str, Any]] = []

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("triggered_at", datetime.now(timezone.utc).isoformat())
        return payload
