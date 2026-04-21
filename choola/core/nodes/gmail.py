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
@choola-node: Gmail
@category: output
@description: Sends an email via the Gmail API using a Google OAuth2 credential that includes the gmail.send scope.
@input-payload:
  - (any prior payload keys are preserved)
@output-payload:
  - email_sent (bool): Whether the email was sent successfully
  - email_to (str): Recipient address
  - email_subject (str): Subject line that was sent
  - (all prior payload keys are preserved)
@config-fields:
  - credential_name (str, required): Name of the stored Google OAuth2 credential (must include scope `gmail.send`)
  - to_email (str, required): Recipient email address
  - subject (str, required): Email subject — use {key} to interpolate payload values
  - body (textarea, required): Email body — use {key} to interpolate payload values
  - body_type (select: plain, html): Content type (default: plain)
@example-input: {"files": ["a.txt", "b.txt"], "file_count": 2}
@example-output: {"email_sent": true, "email_to": "user@example.com", "email_subject": "Files Report", "files": ["a.txt", "b.txt"], "file_count": 2}
@side-effects: Sends an email via the Gmail API
@errors: Missing credential, credential missing gmail.send scope, OAuth2 token refresh failure, Gmail API errors
"""

import base64
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from choola.core.base_node import BaseNode


class Gmail(BaseNode):
    name = "Gmail"
    category = "output"
    description = "Sends an email via the Gmail API using OAuth2 credentials."
    fields = [
        {
            "name": "credential_name",
            "type": "string",
            "required": True,
            "placeholder": "google",
            "description": "Name of the stored Google OAuth2 credential — must include the gmail.send scope (Settings > Credentials > Google)",
        },
        {
            "name": "to_email",
            "type": "string",
            "required": True,
            "placeholder": "recipient@example.com",
            "description": "Recipient email address",
        },
        {
            "name": "subject",
            "type": "string",
            "required": True,
            "placeholder": "Report: {file_count} files found",
            "description": "Subject template — use {key} to interpolate payload values",
        },
        {
            "name": "body",
            "type": "textarea",
            "required": True,
            "placeholder": "Hello,\n\nHere are the results:\n{files}",
            "description": "Body template — use {key} to interpolate payload values",
        },
        {
            "name": "body_type",
            "type": "select",
            "options": ["plain", "html"],
            "default": "plain",
        },
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        credential_name = self.config.get("credential_name", "")
        if not credential_name:
            raise ValueError("credential_name is required — configure it in the node settings")

        cred = await self.get_credential(credential_name)
        if cred is None:
            raise ValueError(
                f"Credential '{credential_name}' not found. "
                "Add it via Settings > Credentials with the Google provider (select the gmail.send scope)."
            )
        if cred.get("provider") != "google":
            raise ValueError(
                f"Credential '{credential_name}' has provider '{cred.get('provider')}', "
                "but Gmail requires a 'google' OAuth2 credential."
            )

        tokens = json.loads(cred["value"])
        granted_scopes = tokens.get("scopes") or []
        if "gmail.send" not in granted_scopes:
            raise ValueError(
                f"Credential '{credential_name}' is missing the 'gmail.send' scope. "
                "Re-authorize it via Settings > Credentials and select the gmail.send scope."
            )

        to_email = self.config.get("to_email", "")

        if not to_email:
            raise ValueError("to_email is required")

        # Interpolate payload values into subject and body
        subject_template = self.config.get("subject", "")
        body_template = self.config.get("body", "")

        try:
            subject = subject_template.format(**payload)
        except KeyError as exc:
            raise ValueError(f"Subject template references missing payload key: {exc}") from exc

        try:
            body = body_template.format(**payload)
        except KeyError as exc:
            raise ValueError(f"Body template references missing payload key: {exc}") from exc

        # Get a valid access token (refresh if needed)
        access_token = await self._get_access_token(tokens)

        # Build the MIME message
        body_type = self.config.get("body_type", "plain")
        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, body_type))

        # Encode and send via Gmail API
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

        import requests as http_requests
        resp = http_requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"raw": raw_message},
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Gmail API error ({resp.status_code}): {resp.text}")

        payload["email_sent"] = True
        payload["email_to"] = to_email
        payload["email_subject"] = subject
        return payload

    async def _get_access_token(self, tokens: dict) -> str:
        """Return a valid access token, refreshing if necessary."""
        import requests as http_requests

        # Try the existing access token first
        test = http_requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if test.status_code == 200:
            return tokens["access_token"]

        # Token expired — refresh it
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise ValueError("Access token expired and no refresh token available. Re-authorize via Settings > Credentials.")

        resp = http_requests.post(tokens["token_uri"], data={
            "client_id": tokens["client_id"],
            "client_secret": tokens["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })

        if resp.status_code != 200:
            raise RuntimeError(f"Failed to refresh Gmail token: {resp.text}")

        new_tokens = resp.json()
        return new_tokens["access_token"]
