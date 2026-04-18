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
@choola-node: HTTP
@category: processing
@description: Makes an HTTP request to an external URL and returns the response.
@input-payload:
  - Any key can be referenced in the URL and body templates via {key} placeholders.
@output-payload:
  - http_status (int): Response status code
  - http_body (dict | str): Response body, auto-parsed as JSON when possible
  - http_headers (dict): Response headers
  - (all prior payload keys are preserved)
@config-fields:
  - method (select: GET, POST, PUT, PATCH, DELETE): HTTP method
  - url (str, required): Request URL — use {key} to interpolate payload values
  - headers (json, default={}): Request headers as a JSON object
  - query_params (json, default={}): Query parameters as a JSON object
  - body (str, optional): Request body — use {key} to interpolate payload values
  - credential_name (str, optional): Stored credential name. Adds Authorization: Bearer <value> header.
  - timeout (number, default=30): Request timeout in seconds
@example-input: {"user_id": "42"}
@example-output: {"user_id": "42", "http_status": 200, "http_body": {"id": 42, "name": "Alice"}, "http_headers": {"content-type": "application/json"}}
@side-effects: Makes an HTTP request to an external service
@errors: Missing URL, credential not found, request timeout, connection error
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import requests

from choola.core.base_node import BaseNode


class HTTP(BaseNode):
    name = "HTTP"
    category = "processing"
    description = "Makes an HTTP request to an external URL and returns the response."
    fields = [
        {
            "name": "method",
            "type": "select",
            "options": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            "default": "GET",
        },
        {
            "name": "url",
            "type": "string",
            "required": True,
            "placeholder": "https://api.example.com/users/{user_id}",
            "description": "Request URL — use {key} to interpolate payload values",
        },
        {
            "name": "headers",
            "type": "json",
            "default": "{}",
            "description": "Request headers as a JSON object",
        },
        {
            "name": "query_params",
            "type": "json",
            "default": "{}",
            "description": "Query parameters as a JSON object",
        },
        {
            "name": "body",
            "type": "textarea",
            "placeholder": '{"name": "{name}", "email": "{email}"}',
            "description": "Request body — use {key} to interpolate payload values",
        },
        {
            "name": "credential_name",
            "type": "string",
            "placeholder": "my-api-key",
            "description": "Optional credential for Bearer token auth",
        },
        {
            "name": "timeout",
            "type": "number",
            "default": 30,
            "description": "Request timeout in seconds",
        },
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        url_template = self.config.get("url", "")
        if not url_template:
            raise ValueError("url is required — configure it in the node settings")

        method = self.config.get("method", "GET").upper()
        timeout = int(self.config.get("timeout", 30))

        # Interpolate URL from payload
        try:
            url = url_template.format(**payload)
        except KeyError as exc:
            raise ValueError(f"URL template references missing payload key: {exc}") from exc

        # Parse headers
        headers = self._parse_json_field("headers")

        # Parse query params
        params = self._parse_json_field("query_params")

        # Credential → Bearer token
        credential_name = self.config.get("credential_name", "").strip()
        if credential_name:
            cred = await self.get_credential(credential_name)
            if cred is None:
                raise ValueError(
                    f"Credential '{credential_name}' not found. "
                    "Add it via Settings > Credentials."
                )
            headers.setdefault("Authorization", f"Bearer {cred['value']}")

        # Interpolate body from payload
        body = None
        body_template = self.config.get("body", "").strip()
        if body_template and method in ("POST", "PUT", "PATCH"):
            try:
                body = body_template.format(**payload)
            except KeyError as exc:
                raise ValueError(f"Body template references missing payload key: {exc}") from exc
            # Default Content-Type to application/json if not set
            headers.setdefault("Content-Type", "application/json")

        # Make the request in a thread to avoid blocking the event loop
        response = await asyncio.to_thread(
            self._do_request, method, url, headers, params, body, timeout
        )

        # Parse response body
        try:
            response_body = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            response_body = response.text

        payload["http_status"] = response.status_code
        payload["http_body"] = response_body
        payload["http_headers"] = dict(response.headers)
        return payload

    def _parse_json_field(self, field_name: str) -> dict:
        raw = self.config.get(field_name, "{}")
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{field_name} must be valid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"{field_name} must be a JSON object, not {type(parsed).__name__}")
            return parsed
        return {}

    @staticmethod
    def _do_request(
        method: str, url: str, headers: dict, params: dict, body: str | None, timeout: int
    ) -> requests.Response:
        return requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params or None,
            data=body,
            timeout=timeout,
        )
