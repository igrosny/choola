# Choola — Workflow Engine

## Project Structure

```
workflows/<name>/
  topology.json           # DAG: nodes + edges
  nodes/
    __init__.py
    <node_name>.py        # One file per node, self-contained
choola.db                 # SQLite store (auto-created on first run)
```

The `choola` package is installed separately via pip. Core infrastructure lives there.

## Node Contract

Every node file MUST:

1. Start with the `@choola-node` grep-friendly docstring (see any file in `workflows/*/nodes/`)
2. Inherit from `choola.core.base_node.BaseNode`
3. Be self-contained — no cross-node imports
4. Communicate exclusively via `payload: dict` passed through `execute()`
5. Declare `name`, `category`, `description`, and `fields` class attributes

## Core Nodes

These live inside the `choola` package and are available to all workflows.

**Rule:** Core nodes must NEVER be instantiated directly in a workflow. Instead, create a new class inside the workflow's `nodes/` directory that extends the core node. This wrapper class is what gets referenced in `topology.json`.

### WebhookTrigger (`core.nodes.webhook_trigger.WebhookTrigger`)
- **Category:** input
- **Purpose:** Starts a workflow when an HTTP request hits a registered endpoint.
- **Config fields:**
  - `path` (str, required) — URL path, e.g. `/hooks/my-endpoint`
  - `method` (select: GET/POST/PUT/DELETE, default `POST`)
  - `response_mode` (select: `immediate` returns 202 right away, `after_workflow` waits for result)
- **Output payload:** `{ method, headers, query, body }`

### FormTrigger (`core.nodes.form_trigger.FormTrigger`)
- **Category:** input
- **Purpose:** Serves an HTML form at a URL path; form submission triggers the workflow.
- **Config fields:**
  - `path` (str, required) — URL path, e.g. `/forms/contact`
  - `form_title` (str) — heading above the form
  - `form_description` (str) — description text below the title
  - `form_fields` (json) — array of field definitions, each with:
    - `label`, `field_name`, `field_type` (text/email/number/password/textarea/dropdown/date/checkbox)
    - `required` (bool), `placeholder` (str), `options` (list, dropdown only), `default_value` (str)
  - `response_mode` (select: `after_workflow` returns JSON, `redirect` shows thank-you page)
  - `submit_label` (str, default `Submit`)
- **Output payload:** `{ form_data: {field_name: value, ...}, submitted_at: "<ISO timestamp>" }`

### LLM (`core.nodes.llm.LLM`)
- **Category:** processing
- **Purpose:** Sends a prompt to an LLM (Claude or Gemini) and returns the response.
- **Requires:** A stored credential (managed via Settings > Credentials or `POST /api/credentials`)
- **Config fields:**
  - `credential_name` (str, required) — name of the stored credential to use
  - `provider` (select: `claude`, `gemini`) — which LLM provider
  - `model` (str) — model ID; defaults to `claude-sonnet-4-20250514` / `gemini-2.0-flash`
  - `prompt` (textarea, required) — prompt template; use `{key}` to interpolate payload values
  - `system_prompt` (textarea) — optional system prompt
  - `max_tokens` (number, default 1024)
  - `temperature` (number, default 1.0)
- **Output payload:** adds `llm_response`, `llm_model`, `llm_provider` to existing payload

## Credentials

Credentials are stored in the SQLite database (`credentials` table) and accessed by nodes at runtime via `self.get_credential(name)`.

### API
- `GET /api/credentials` — list all credentials (values masked)
- `POST /api/credentials` — create/update: `{ name, provider, value }`
- `DELETE /api/credentials/<name>` — delete a credential

### Node access
Any node can call `await self.get_credential("my-key")` to retrieve a credential dict with keys: `name`, `provider`, `value`, `created_at`, `updated_at`.

## CLI

```bash
choola init                              # Set up a new project (run once)
choola start                             # Start the server at http://localhost:5000
choola start --host 0.0.0.0 --port 8080 # Bind to all interfaces
choola create <workflow_name>            # Scaffold a new workflow
choola list                              # List all workflows
choola run <workflow_name> --payload '{"key": "value"}'  # Run headlessly
choola nodes                             # List core node types
```
