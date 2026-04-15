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
@choola-node: ManualTrigger
@category: input
@description: Starts a workflow manually via the UI or CLI. No external event needed.
@input-payload:
  - (none — this is a trigger node; payload is provided by the caller or empty)
@output-payload:
  - triggered_at (str): ISO timestamp when the workflow was triggered
  - trigger_type (str): Always "manual"
@config-fields:
  - (none)
@example-input: {}
@example-output: {"triggered_at": "2026-04-15T10:30:00Z", "trigger_type": "manual"}
@side-effects: none
@errors: none
"""

from typing import Any

from choola.core.nodes.trigger import Trigger


class ManualTrigger(Trigger):
    """Trigger node for workflows that are started manually.

    Use this when the workflow doesn't need an external event (webhook, form,
    schedule) to start. The user clicks "Run" in the UI or uses `choola run`
    from the CLI.
    """

    name = "Manual Trigger"
    category = "input"
    description = "Starts a workflow manually via the UI or CLI."
    fields: list[dict[str, Any]] = []

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload = await super().execute(payload, context)
        payload["trigger_type"] = "manual"
        return payload
