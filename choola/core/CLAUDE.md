# Choola Core Nodes

Core nodes are the building blocks that workflow nodes extend. They live in `choola/core/nodes/` and are part of the pip-installed package.

## Golden Rule

**Never instantiate a core node directly in a workflow.** Always create a wrapper class in the workflow's `nodes/` directory that extends the core node. The wrapper is what goes in `topology.json`.

This allows each workflow to customize field defaults, override `execute()`, and remain self-contained.

## BaseNode (`choola.core.base_node.BaseNode`)

The abstract base class for ALL nodes. Provides:

- `node_id` — auto-generated UUID hex
- `config` — merged from field defaults + topology config
- `async execute(payload, context)` — MUST be implemented by subclasses
- `async get_global(key)` / `set_global(key, value)` — persistent SQLite globals
- `async get_credential(name)` — retrieve stored credentials
- `ui_metadata()` — returns node metadata for the frontend

**Required class attributes:**
- `node_id` (str) — unique identifier within a workflow (snake_case). Used to wire `next_nodes` edges.
- `name` (str) — human-readable name for the UI
- `category` (str) — sidebar grouping (e.g. "input", "processing", "output")
- `description` (str) — tooltip text
- `fields` (list[dict]) — input field definitions for the UI. Each dict has at minimum `name` and `type`
- `next_nodes` (list[str]) — list of `node_id` values this node passes output to. `[]` for terminal nodes.

## Trigger (`choola.core.nodes.trigger.Trigger`)

**Category:** input
**Purpose:** Abstract base class for all trigger nodes. Every workflow must have exactly one node that inherits from Trigger as its entry point.

**Fields:** none (subclasses define their own)

**Output payload:** adds `triggered_at` (ISO timestamp)

**Notes:**
- WebhookTrigger, FormTrigger, and ManualTrigger all extend this class.
- The engine uses `isinstance(node, Trigger)` to identify the workflow's entry point.
- Do not instantiate `Trigger` directly — use a subclass.

## ManualTrigger (`choola.core.nodes.manual_trigger.ManualTrigger`)

**Category:** input
**Purpose:** Starts a workflow manually via the UI "Run" button or `choola run` CLI command. No external event needed.

**Fields:** none

**Output payload:** adds `triggered_at` (ISO timestamp), `trigger_type` = `"manual"`

## WebhookTrigger (`choola.core.nodes.webhook_trigger.WebhookTrigger`)

**Category:** input
**Purpose:** Starts a workflow when an HTTP request hits a registered endpoint.

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | — | URL path, e.g. `/hooks/my-endpoint` |
| `method` | select | no | `POST` | GET, POST, PUT, DELETE |
| `response_mode` | select | no | `after_workflow` | `immediate` (202) or `after_workflow` (waits) |

**Output payload:** `{ method, headers, query, body }`

## FormTrigger (`choola.core.nodes.form_trigger.FormTrigger`)

**Category:** input
**Purpose:** Serves an HTML form at a URL path; form submission triggers the workflow.

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | — | URL path, e.g. `/forms/contact` |
| `form_title` | string | no | `""` | Heading above the form |
| `form_description` | string | no | `""` | Description below the title |
| `form_fields` | json | no | `[]` | Array of field definitions (see below) |
| `response_mode` | select | no | `after_workflow` | `after_workflow` (JSON) or `redirect` (thank-you page) |
| `submit_label` | string | no | `Submit` | Submit button text |

**form_fields array items:**
- `label` (str), `field_name` (str), `field_type` (text/email/number/password/textarea/dropdown/date/checkbox)
- `required` (bool), `placeholder` (str), `options` (list, dropdown only), `default_value` (str)

**Output payload:** `{ form_data: {field_name: value, ...}, submitted_at: "<ISO>" }`

**Extra methods (used by the server, not by workflows):**
- `render_form()` — returns HTML string
- `render_thank_you()` — returns HTML string

## LLM (`choola.core.nodes.llm.LLM`)

**Category:** processing
**Purpose:** Sends a prompt to an LLM (Claude or Gemini) and returns the response.

**Requires:** A stored credential (`await self.get_credential(name)`)

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `credential_name` | string | yes | — | Name of the stored credential |
| `provider` | select | no | `claude` | `claude` or `gemini` |
| `model` | string | no | auto | Model ID (defaults: `claude-sonnet-4-20250514` / `gemini-2.0-flash`) |
| `prompt` | textarea | yes | — | Prompt template; `{key}` interpolates payload values |
| `system_prompt` | textarea | no | — | Optional system prompt |
| `max_tokens` | number | no | 1024 | Max response tokens |
| `temperature` | number | no | 1.0 | Sampling temperature |

**Output payload:** adds `llm_response`, `llm_model`, `llm_provider` to existing payload

## HTTP (`choola.core.nodes.http.HTTP`)

**Category:** processing
**Purpose:** Makes an HTTP request to an external URL and returns the response. Supports all common HTTP methods, header/query customization, body interpolation, and optional Bearer token auth via stored credentials.

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `method` | select | no | `GET` | GET, POST, PUT, PATCH, DELETE |
| `url` | string | yes | — | Request URL; `{key}` interpolates payload values |
| `headers` | json | no | `{}` | Request headers as a JSON object |
| `query_params` | json | no | `{}` | Query parameters as a JSON object |
| `body` | textarea | no | — | Request body; `{key}` interpolates payload values |
| `credential_name` | string | no | — | Stored credential name — adds `Authorization: Bearer <value>` |
| `timeout` | number | no | `30` | Request timeout in seconds |

**Output payload:** adds `http_status` (int), `http_body` (dict or str), `http_headers` (dict) to existing payload

**Notes:**
- URL and body support `{key}` interpolation from the incoming payload
- Response body is auto-parsed as JSON when possible, otherwise returned as a string
- Body is only sent for POST, PUT, and PATCH methods
- If no `Content-Type` header is set and a body is provided, defaults to `application/json`

## Gmail (`choola.core.nodes.gmail.Gmail`)

**Category:** output
**Purpose:** Sends an email via the Gmail API using OAuth2 credentials.

**Requires:** A stored credential (`await self.get_credential(name)`) with provider `gmail` — set up via the OAuth2 flow in Settings > Credentials.

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `credential_name` | string | yes | — | Name of the stored Gmail OAuth2 credential |
| `to_email` | string | yes | — | Recipient email address |
| `subject` | string | yes | — | Subject template; `{key}` interpolates payload values |
| `body` | textarea | yes | — | Body template; `{key}` interpolates payload values |
| `body_type` | select | no | `plain` | `plain` or `html` |

**Output payload:** adds `email_sent` (bool), `email_to` (str), `email_subject` (str) to existing payload

**Setup:** In Settings > Credentials, select the "Gmail" provider, enter your Google Cloud OAuth2 Client ID and Client Secret (with Gmail API enabled and `gmail.send` scope), then click "Connect with Gmail" to authorize. The sender address is the authenticated Google account.
