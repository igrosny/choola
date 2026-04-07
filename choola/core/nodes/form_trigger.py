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
@choola-node: FormTrigger
@category: input
@description: Starts a workflow by showing a web form. Visitors fill out the form and the submission triggers the workflow.
@input-payload:
  - (none — this is a trigger node; payload comes from form submission)
@output-payload:
  - form_data (dict): All submitted field values keyed by field name
  - submitted_at (str): ISO timestamp of when the form was submitted
@config-fields:
  - path (str, required): URL path for the form, e.g. "/forms/contact"
  - form_title (str, default=""): Heading displayed above the form
  - form_description (str, default=""): Description text shown below the title
  - form_fields (list[dict]): Form elements to render. Each dict has:
      - label (str): Display label
      - field_name (str): Key in the output payload
      - field_type (str): One of text, email, number, password, textarea, dropdown, date, checkbox
      - required (bool, default=False)
      - placeholder (str, default="")
      - options (list[str]): Only for dropdown type
      - default_value (str, default="")
  - response_mode (str, default="after_workflow"): "redirect" shows a thank-you page; "after_workflow" returns the workflow result as JSON
  - submit_label (str, default="Submit"): Text on the submit button
@example-input: {}
@example-output: {"form_data": {"name": "Alice", "email": "alice@example.com"}, "submitted_at": "2026-04-06T12:00:00+00:00"}
@side-effects: Registers HTTP routes on the server (GET for form, POST for submission)
@errors: none
"""

import html
import json
from datetime import datetime, timezone
from typing import Any

from choola.core.base_node import BaseNode


class FormTrigger(BaseNode):
    name = "Form Trigger"
    category = "input"
    description = "Starts a workflow by showing a web form to collect user input."
    fields = [
        {"name": "path", "type": "string", "required": True, "placeholder": "/forms/contact"},
        {"name": "form_title", "type": "string", "default": ""},
        {"name": "form_description", "type": "string", "default": ""},
        {
            "name": "form_fields",
            "type": "json",
            "default": "[]",
            "description": "JSON array of form field definitions",
        },
        {
            "name": "response_mode",
            "type": "select",
            "options": ["after_workflow", "redirect"],
            "default": "after_workflow",
        },
        {"name": "submit_label", "type": "string", "default": "Submit"},
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        # When triggered via form submission, the server injects form_data into the payload.
        # When triggered manually (CLI / UI), just pass through whatever payload was given.
        return payload

    # ------------------------------------------------------------------
    # HTML form rendering (called by the server, not by execute)
    # ------------------------------------------------------------------
    def render_form(self) -> str:
        """Generate a self-contained HTML page with the configured form."""
        title = html.escape(self.config.get("form_title", "") or "Form")
        description = html.escape(self.config.get("form_description", "") or "")
        submit_label = html.escape(self.config.get("submit_label", "") or "Submit")
        path = self.config.get("path", "/")

        raw_fields = self.config.get("form_fields", "[]")
        if isinstance(raw_fields, str):
            try:
                form_fields = json.loads(raw_fields)
            except json.JSONDecodeError:
                form_fields = []
        else:
            form_fields = raw_fields

        fields_html = []
        for f in form_fields:
            label = html.escape(f.get("label", f.get("field_name", "")))
            name = html.escape(f.get("field_name", ""))
            ftype = f.get("field_type", "text")
            required = "required" if f.get("required") else ""
            placeholder = html.escape(f.get("placeholder", ""))
            default = html.escape(str(f.get("default_value", "")))

            if ftype == "textarea":
                fields_html.append(
                    f'<div class="field">'
                    f'<label for="{name}">{label}</label>'
                    f'<textarea id="{name}" name="{name}" placeholder="{placeholder}" {required}>{default}</textarea>'
                    f'</div>'
                )
            elif ftype == "dropdown":
                options = f.get("options", [])
                opts_html = '<option value="">-- Select --</option>'
                for opt in options:
                    escaped = html.escape(str(opt))
                    selected = "selected" if str(opt) == str(f.get("default_value", "")) else ""
                    opts_html += f'<option value="{escaped}" {selected}>{escaped}</option>'
                fields_html.append(
                    f'<div class="field">'
                    f'<label for="{name}">{label}</label>'
                    f'<select id="{name}" name="{name}" {required}>{opts_html}</select>'
                    f'</div>'
                )
            elif ftype == "checkbox":
                checked = "checked" if default.lower() in ("true", "1", "yes", "on") else ""
                fields_html.append(
                    f'<div class="field checkbox">'
                    f'<label><input type="checkbox" name="{name}" value="true" {checked} {required}> {label}</label>'
                    f'</div>'
                )
            else:
                # text, email, number, password, date
                input_type = ftype if ftype in ("email", "number", "password", "date") else "text"
                step = 'step="any"' if ftype == "number" else ""
                fields_html.append(
                    f'<div class="field">'
                    f'<label for="{name}">{label}</label>'
                    f'<input type="{input_type}" id="{name}" name="{name}" '
                    f'placeholder="{placeholder}" value="{default}" {step} {required}>'
                    f'</div>'
                )

        form_action = f"/webhook{path}" if not path.startswith("/") else f"/webhook{path}"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5; color: #333; margin: 0; padding: 2rem;
    display: flex; justify-content: center;
  }}
  .container {{ background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    padding: 2.5rem; max-width: 560px; width: 100%; }}
  h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; }}
  .desc {{ color: #666; margin: 0 0 1.5rem; font-size: 0.95rem; }}
  .field {{ margin-bottom: 1.25rem; }}
  label {{ display: block; font-weight: 600; margin-bottom: 0.35rem; font-size: 0.9rem; }}
  input, textarea, select {{
    width: 100%; padding: 0.6rem 0.75rem; border: 1px solid #ddd; border-radius: 6px;
    font-size: 0.95rem; transition: border-color 0.15s;
  }}
  input:focus, textarea:focus, select:focus {{ outline: none; border-color: #4f46e5; }}
  textarea {{ min-height: 100px; resize: vertical; }}
  .checkbox label {{ font-weight: 400; display: flex; align-items: center; gap: 0.5rem; }}
  .checkbox input {{ width: auto; }}
  button {{
    background: #4f46e5; color: #fff; border: none; border-radius: 6px;
    padding: 0.7rem 2rem; font-size: 1rem; font-weight: 600; cursor: pointer;
    transition: background 0.15s; width: 100%; margin-top: 0.5rem;
  }}
  button:hover {{ background: #4338ca; }}
</style>
</head>
<body>
<div class="container">
  <h1>{title}</h1>
  {"<p class='desc'>" + description + "</p>" if description else ""}
  <form method="POST" action="{form_action}">
    {"".join(fields_html)}
    <button type="submit">{submit_label}</button>
  </form>
</div>
</body>
</html>"""

    def render_thank_you(self) -> str:
        """Generate a simple thank-you / success page."""
        title = html.escape(self.config.get("form_title", "") or "Form")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Submitted</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5; color: #333; margin: 0; padding: 2rem;
    display: flex; justify-content: center; align-items: center; min-height: 80vh;
  }}
  .container {{ background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    padding: 2.5rem; max-width: 480px; width: 100%; text-align: center; }}
  .check {{ font-size: 3rem; margin-bottom: 1rem; }}
  h1 {{ margin: 0 0 0.5rem; font-size: 1.3rem; }}
  p {{ color: #666; }}
</style>
</head>
<body>
<div class="container">
  <div class="check">&#10003;</div>
  <h1>Form Submitted</h1>
  <p>Your response has been recorded. Thank you!</p>
</div>
</body>
</html>"""
