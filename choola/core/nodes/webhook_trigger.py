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
@choola-node: WebhookTrigger
@category: input
@description: Starts a workflow when an HTTP webhook is called. Registers a dynamic endpoint at the configured path.
@input-payload:
  - (none — this is a trigger node; payload comes from the HTTP request body)
@output-payload:
  - method (str): HTTP method used by the caller
  - headers (dict): Request headers
  - query (dict): Query string parameters
  - body (dict|str): Parsed JSON body, or raw body string if not JSON
@config-fields:
  - path (str, required): URL path for the webhook, e.g. "/hooks/my-lead"
  - method (str, default="POST"): HTTP method to listen on (GET, POST, PUT, DELETE)
  - response_mode (str, default="after_workflow"): "immediate" returns 202 right away; "after_workflow" waits and returns the final payload
@example-input: {}
@example-output: {"method": "POST", "headers": {}, "query": {}, "body": {"lead": "Acme"}}
@side-effects: Registers an HTTP route on the server
@errors: none
"""

from typing import Any

from choola.core.base_node import BaseNode


class WebhookTrigger(BaseNode):
    name = "Webhook Trigger"
    category = "input"
    description = "Starts a workflow when an HTTP webhook is called."
    fields = [
        {"name": "path", "type": "string", "required": True, "placeholder": "/hooks/my-endpoint"},
        {
            "name": "method",
            "type": "select",
            "options": ["GET", "POST", "PUT", "DELETE"],
            "default": "POST",
        },
        {
            "name": "response_mode",
            "type": "select",
            "options": ["immediate", "after_workflow"],
            "default": "after_workflow",
        },
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        # When triggered via webhook, the server injects request data into the payload.
        # When triggered manually (CLI / UI), just pass through whatever payload was given.
        return payload
