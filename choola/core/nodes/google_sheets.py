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
@choola-node: GoogleSheets
@category: processing
@description: Reads, appends, updates, or clears data in a Google Sheet via the Sheets v4 API.
@input-payload:
  - Any key can be referenced in spreadsheet_id, range, and string leaves of values via {key}.
@output-payload:
  - sheets_operation (str): The operation that was performed
  - sheets_spreadsheet_id (str): Spreadsheet ID that was touched
  - sheets_range (str): The range read or written, as reported by the Sheets API
  - rows (list[dict] | list[list]): On read — rows returned (dicts keyed by header row when rows_as_dicts=true, else raw 2D array)
  - row_count (int): On read — number of returned rows
  - appended_rows (int): On append — number of rows that were appended
  - updated_cells (int): On update — number of cells overwritten
  - (all prior payload keys are preserved)
@config-fields:
  - credential_name (str, required, default=google): Stored Google OAuth2 credential; must include scope `sheets` for write ops or `sheets` / `sheets.readonly` for read
  - operation (select: read, append, update, clear, default=read): What to do
  - spreadsheet_id (str, required): Spreadsheet ID from the sheet URL — `{key}` interpolates payload values
  - range (str, default=Sheet1): A1 notation, e.g. `Sheet1!A1:D10`. Just `Sheet1` reads/writes the whole tab. `{key}` interpolates payload values
  - values (json, default=[]): Append/update only. Either a 2D array of rows OR a list of `{column: value}` dicts (mapped against the sheet's header row). String leaves support `{key}` interpolation.
  - value_input_option (select: USER_ENTERED, RAW, default=USER_ENTERED): How Google parses written values (USER_ENTERED applies formulas/dates; RAW writes the literal string)
  - rows_as_dicts (select: true, false, default=true): On read — treat the first returned row as headers and return remaining rows as dicts
@example-input: {"customer": "Alice", "qty": 3}
@example-output: {"customer": "Alice", "qty": 3, "sheets_operation": "append", "sheets_spreadsheet_id": "1abcXYZ", "sheets_range": "Sheet1!A2:B2", "appended_rows": 1}
@side-effects: Calls the Google Sheets API; may modify the spreadsheet
@errors: Missing credential, credential has wrong provider, credential missing required scope, OAuth2 refresh failure, Sheets API errors (invalid range, permission denied, etc.)
@cost: free
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from choola.core.base_node import BaseNode

SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


class GoogleSheets(BaseNode):
    name = "Google Sheets"
    category = "processing"
    description = "Read, append, update, or clear data in a Google Sheet."
    fields = [
        {
            "name": "credential_name",
            "type": "string",
            "required": True,
            "default": "google",
            "placeholder": "google",
            "description": (
                "Name of the stored Google OAuth2 credential. Write operations need the "
                "`sheets` scope; `read` accepts `sheets` or `sheets.readonly`."
            ),
        },
        {
            "name": "operation",
            "type": "select",
            "options": ["read", "append", "update", "clear"],
            "default": "read",
        },
        {
            "name": "spreadsheet_id",
            "type": "string",
            "required": True,
            "placeholder": "1abcXYZ...  (or {spreadsheet_id} from payload)",
            "description": "Spreadsheet ID from the sheet URL — `{key}` interpolates payload values.",
        },
        {
            "name": "range",
            "type": "string",
            "default": "Sheet1",
            "placeholder": "Sheet1!A1:D10",
            "description": "A1 range — `{key}` interpolates payload values.",
        },
        {
            "name": "values",
            "type": "json",
            "default": "[]",
            "description": (
                "Append/update only. 2D array of rows OR list of {column: value} dicts. "
                "String leaves support `{key}` interpolation from the payload."
            ),
        },
        {
            "name": "value_input_option",
            "type": "select",
            "options": ["USER_ENTERED", "RAW"],
            "default": "USER_ENTERED",
            "description": "USER_ENTERED parses formulas/dates; RAW writes literal strings.",
        },
        {
            "name": "rows_as_dicts",
            "type": "select",
            "options": ["true", "false"],
            "default": "true",
            "description": "On read: treat first row as headers and return list of dicts.",
        },
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        credential_name = (self.config.get("credential_name") or "").strip()
        if not credential_name:
            raise ValueError("credential_name is required — configure it in the node settings")

        cred = await self.get_credential(credential_name)
        if cred is None:
            raise ValueError(
                f"Credential '{credential_name}' not found. "
                "Add it via Settings > Credentials with the Google provider (select the 'sheets' scope)."
            )
        if cred.get("provider") != "google":
            raise ValueError(
                f"Credential '{credential_name}' has provider '{cred.get('provider')}', "
                "but Google Sheets requires a 'google' OAuth2 credential."
            )

        tokens = json.loads(cred["value"])
        granted = set(tokens.get("scopes") or [])

        operation = (self.config.get("operation") or "read").strip()
        if operation not in ("read", "append", "update", "clear"):
            raise ValueError(f"Unknown operation '{operation}' — must be read, append, update, or clear")

        if operation == "read":
            if not (granted & {"sheets", "sheets.readonly"}):
                raise ValueError(
                    f"Credential '{credential_name}' is missing the 'sheets' or 'sheets.readonly' scope. "
                    "Re-authorize it via Settings > Credentials."
                )
        else:
            if "sheets" not in granted:
                raise ValueError(
                    f"Credential '{credential_name}' is missing the 'sheets' scope (required for "
                    f"'{operation}'). Re-authorize it via Settings > Credentials with the 'sheets' scope ticked."
                )

        spreadsheet_id_template = self.config.get("spreadsheet_id") or ""
        if not spreadsheet_id_template:
            raise ValueError("spreadsheet_id is required")
        try:
            spreadsheet_id = spreadsheet_id_template.format(**payload).strip()
        except KeyError as exc:
            raise ValueError(f"spreadsheet_id template references missing payload key: {exc}") from exc
        if not spreadsheet_id:
            raise ValueError("spreadsheet_id resolved to an empty string after interpolation")

        range_template = self.config.get("range") or "Sheet1"
        try:
            range_str = range_template.format(**payload)
        except KeyError as exc:
            raise ValueError(f"range template references missing payload key: {exc}") from exc

        access_token = await self._get_access_token(tokens)

        if operation == "read":
            return await self._do_read(payload, access_token, spreadsheet_id, range_str)
        if operation == "clear":
            return await self._do_clear(payload, access_token, spreadsheet_id, range_str)

        # append / update share value handling
        raw_values = self.config.get("values", [])
        values_2d = await self._resolve_values(
            raw_values, payload, access_token, spreadsheet_id, range_str, operation
        )
        value_input_option = (self.config.get("value_input_option") or "USER_ENTERED").strip()

        if operation == "append":
            return await self._do_append(
                payload, access_token, spreadsheet_id, range_str, values_2d, value_input_option
            )
        return await self._do_update(
            payload, access_token, spreadsheet_id, range_str, values_2d, value_input_option
        )

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    async def _do_read(
        self,
        payload: dict[str, Any],
        access_token: str,
        spreadsheet_id: str,
        range_str: str,
    ) -> dict[str, Any]:
        url = f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{_quote_range(range_str)}"
        resp = await asyncio.to_thread(
            _http_request, "GET", url, {"Authorization": f"Bearer {access_token}"}, None
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Sheets API read error ({resp.status_code}): {resp.text}")
        data = resp.json()
        raw_values: list[list[Any]] = data.get("values", []) or []

        as_dicts = (self.config.get("rows_as_dicts") or "true").strip().lower() == "true"
        if as_dicts and raw_values:
            headers = [str(h) for h in raw_values[0]]
            rows: list[Any] = [
                {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
                for row in raw_values[1:]
            ]
        else:
            rows = raw_values if not as_dicts else []

        payload["sheets_operation"] = "read"
        payload["sheets_spreadsheet_id"] = spreadsheet_id
        payload["sheets_range"] = data.get("range", range_str)
        payload["rows"] = rows
        payload["row_count"] = len(rows)
        return payload

    async def _do_append(
        self,
        payload: dict[str, Any],
        access_token: str,
        spreadsheet_id: str,
        range_str: str,
        values_2d: list[list[Any]],
        value_input_option: str,
    ) -> dict[str, Any]:
        if not values_2d:
            raise ValueError("append requires at least one row in `values`")
        url = (
            f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{_quote_range(range_str)}:append"
            f"?valueInputOption={value_input_option}&insertDataOption=INSERT_ROWS"
        )
        resp = await asyncio.to_thread(
            _http_request,
            "POST",
            url,
            {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json.dumps({"values": values_2d}),
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Sheets API append error ({resp.status_code}): {resp.text}")
        data = resp.json()
        updates = data.get("updates", {}) or {}
        payload["sheets_operation"] = "append"
        payload["sheets_spreadsheet_id"] = spreadsheet_id
        payload["sheets_range"] = updates.get("updatedRange", range_str)
        payload["appended_rows"] = int(updates.get("updatedRows") or 0)
        return payload

    async def _do_update(
        self,
        payload: dict[str, Any],
        access_token: str,
        spreadsheet_id: str,
        range_str: str,
        values_2d: list[list[Any]],
        value_input_option: str,
    ) -> dict[str, Any]:
        if not values_2d:
            raise ValueError("update requires at least one row in `values`")
        url = (
            f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{_quote_range(range_str)}"
            f"?valueInputOption={value_input_option}"
        )
        resp = await asyncio.to_thread(
            _http_request,
            "PUT",
            url,
            {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json.dumps({"values": values_2d}),
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Sheets API update error ({resp.status_code}): {resp.text}")
        data = resp.json()
        payload["sheets_operation"] = "update"
        payload["sheets_spreadsheet_id"] = spreadsheet_id
        payload["sheets_range"] = data.get("updatedRange", range_str)
        payload["updated_cells"] = int(data.get("updatedCells") or 0)
        return payload

    async def _do_clear(
        self,
        payload: dict[str, Any],
        access_token: str,
        spreadsheet_id: str,
        range_str: str,
    ) -> dict[str, Any]:
        url = f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{_quote_range(range_str)}:clear"
        resp = await asyncio.to_thread(
            _http_request,
            "POST",
            url,
            {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            "{}",
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Sheets API clear error ({resp.status_code}): {resp.text}")
        data = resp.json()
        payload["sheets_operation"] = "clear"
        payload["sheets_spreadsheet_id"] = spreadsheet_id
        payload["sheets_range"] = data.get("clearedRange", range_str)
        return payload

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _resolve_values(
        self,
        raw_values: Any,
        payload: dict[str, Any],
        access_token: str,
        spreadsheet_id: str,
        range_str: str,
        operation: str,
    ) -> list[list[Any]]:
        """Parse `values`, interpolate leaves, and map dict rows against header row when needed."""
        if isinstance(raw_values, str):
            text = raw_values.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"values must be valid JSON: {exc}") from exc
        else:
            parsed = raw_values

        if parsed is None:
            return []
        if not isinstance(parsed, list):
            raise ValueError("values must be a JSON array (list of rows or list of dicts)")

        parsed = _interpolate_leaves(parsed, payload)

        if not parsed:
            return []

        if all(isinstance(row, list) for row in parsed):
            return [list(row) for row in parsed]

        if all(isinstance(row, dict) for row in parsed):
            headers = await self._fetch_header_row(access_token, spreadsheet_id, range_str)
            if not headers:
                raise ValueError(
                    "values is a list of dicts but the sheet's header row is empty. "
                    "Add a header row to row 1 of the range, or pass a 2D array."
                )
            return [
                [row.get(h, "") for h in headers]
                for row in parsed
            ]

        raise ValueError(
            "values must be uniformly a list of arrays OR a list of dicts (got a mix or unsupported types)"
        )

    async def _fetch_header_row(
        self, access_token: str, spreadsheet_id: str, range_str: str
    ) -> list[str]:
        """Fetch row 1 of the sheet referenced by `range_str` so dict rows can be mapped."""
        sheet_name = _sheet_name_from_range(range_str)
        header_range = f"{sheet_name}!1:1" if sheet_name else "1:1"
        url = f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{_quote_range(header_range)}"
        resp = await asyncio.to_thread(
            _http_request, "GET", url, {"Authorization": f"Bearer {access_token}"}, None
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Sheets API header lookup error ({resp.status_code}): {resp.text}"
            )
        values = resp.json().get("values", []) or []
        if not values:
            return []
        return [str(h) for h in values[0]]

    async def _get_access_token(self, tokens: dict) -> str:
        """Return a valid access token, refreshing via the refresh_token if Google rejects it."""
        import requests as http_requests

        access_token = tokens.get("access_token")
        if access_token:
            test = await asyncio.to_thread(
                http_requests.get,
                "https://www.googleapis.com/oauth2/v3/tokeninfo",
                {"access_token": access_token},
            )
            if test.status_code == 200:
                return access_token

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise ValueError(
                "Access token expired and no refresh token is available. "
                "Re-authorize via Settings > Credentials."
            )

        resp = await asyncio.to_thread(
            http_requests.post,
            tokens["token_uri"],
            data={
                "client_id": tokens["client_id"],
                "client_secret": tokens["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to refresh Google token: {resp.text}")
        return resp.json()["access_token"]


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------
def _http_request(method: str, url: str, headers: dict, body: str | None):
    import requests as http_requests

    return http_requests.request(method=method, url=url, headers=headers, data=body, timeout=30)


def _quote_range(range_str: str) -> str:
    """URL-quote an A1 range so `!` and spaces survive."""
    from urllib.parse import quote

    return quote(range_str, safe="")


def _sheet_name_from_range(range_str: str) -> str:
    """Extract the sheet/tab name from an A1 range. `Sheet1!A1:B2` → `Sheet1`; `Sheet1` → `Sheet1`."""
    if not range_str:
        return ""
    if "!" in range_str:
        return range_str.split("!", 1)[0]
    return range_str


def _interpolate_leaves(value: Any, payload: dict[str, Any]) -> Any:
    """Recursively apply `{key}` interpolation to string leaves, leaving other types untouched."""
    if isinstance(value, str):
        try:
            return value.format(**payload)
        except (KeyError, IndexError):
            return value
    if isinstance(value, list):
        return [_interpolate_leaves(v, payload) for v in value]
    if isinstance(value, dict):
        return {k: _interpolate_leaves(v, payload) for k, v in value.items()}
    return value
