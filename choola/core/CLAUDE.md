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
- `async get_global(key)` / `set_global(key, value)` — persistent SQLite globals (shared across workflows)
- `async get_credential(name)` — retrieve stored credentials
- `async db_query(sql, params)` / `db_execute(sql, params)` — read/write the workflow's own SQLite DB at `files/db.sqlite` (provision the schema with the `DB` core node)
- `async vector_add / vector_query / vector_get / vector_delete / vector_count` — upsert and search the workflow's own ChromaDB store at `files/chroma/` (provision collections with the `VectorDB` core node)
- `report_tokens(prompt_tokens, completion_tokens, model, provider)` — synchronous sidechannel for paid-LLM token telemetry; feeds the engine's `max_tokens_per_run` / `max_tokens_per_hour` circuit breakers and persists into `run_logs` and evaluation JSON
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

## LLML (`choola.core.nodes.llml.LLML`)

**Category:** processing
**Purpose:** LLM with a 3-layer fallthrough (exact-match cache → local XGBoost classifier → real LLM). For yes/no and small-label classification tasks where identical inputs should never pay twice and enough examples eventually retire the LLM entirely.

**Requires:** A stored credential (inherited from LLM). A trained XGBoost model appears only after `choola dream` runs on collected examples.

**Fields:** (inherits all LLM fields — `credential_name`, `provider`, `model`, `prompt`, `system_prompt`, `max_tokens`, `temperature`) plus:

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `parameter_keys` | json | no | `[]` | JSON list of payload keys whose values form the cache key and XGBoost feature input |
| `confidence_threshold` | number | no | `0.85` | Min XGBoost top-class probability (0.0–1.0) required to skip the LLM |

**Output payload:** adds `llm_response`, `llm_model`, `llm_provider`, `llml_source` (`"llm"` or `"xgboost"`), `llml_confidence` (float or null), `llml_cached` (bool).

**Side effects:** auto-creates `llml_<node_id>` SQLite table on first run in the workflow's `files/db.sqlite`; upserts into ChromaDB collection `llml_<node_id>` in the workflow's `files/chroma/` only when the real LLM is called (keeps training data free of self-predictions).

**Training via `choola dream`:** walks every workflow, finds LLML-subclass nodes, and — for each — trains `files/llml/<node_id>/model.bin` (+ `labels.json`, `meta.json`) from rows where `source='llm'`. XGBoost-inferred rows are intentionally excluded so the model never learns from its own predictions.

**Notes:**
- `node_id` must match `^[a-z0-9_]+$` because it's interpolated into the table name.
- The LLM is still called whenever the cache misses AND either no model exists yet OR its top-class probability is below `confidence_threshold` — so the node stays correct even with zero training and degrades gracefully if a trained model is deleted.
- Raise `confidence_threshold` toward 1.0 to use XGBoost only when very sure; lower it to shift more traffic to the local model.

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

## DB (`choola.core.nodes.db.DB`)

**Category:** processing
**Purpose:** Provisions the workflow's own SQLite database at `workflows/<name>/files/db.sqlite` — tables, indexes, etc. Put this node early in the graph; downstream nodes read/write via `await self.db_query(...)` and `await self.db_execute(...)`.

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `schema` | textarea | yes | — | Idempotent SQL DDL. Runs on every execution. |

**Output payload:** adds `db_path` (str — absolute path to the SQLite file).

**Notes:**
- The DB file and `files/` directory are auto-created on first use.
- Every workflow gets its own isolated DB — two workflows can have identically-named tables without conflict.
- Schema must be idempotent: use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, etc. Running the node twice is a no-op.
- For non-trivial migrations, prefer adding new `CREATE TABLE`s / columns (via `ALTER TABLE`) in new schema statements rather than mutating existing ones destructively.

**Using the data from other nodes:**
```python
# In any node extending BaseNode:
await self.db_execute("INSERT INTO items (name) VALUES (?)", ("widget",))
rows = await self.db_query("SELECT * FROM items WHERE name = ?", ("widget",))
# rows is a list[dict], each keyed by column name
```

## VectorDB (`choola.core.nodes.vectordb.VectorDB`)

**Category:** processing
**Purpose:** Provisions the workflow's own persistent ChromaDB store at `workflows/<name>/files/chroma/` — creates the configured collections. Put this node early in the graph; downstream nodes read/write via `await self.vector_add(...)`, `self.vector_query(...)`, and friends.

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `collections` | json | yes | `["documents"]` | Either a list of collection names (strings) or a list of `{name, metadata}` dicts. Collections are created with `get_or_create_collection` so the node is idempotent. |

**Output payload:** adds `vectordb_path` (str — absolute path to the Chroma directory) and `collections` (list of ensured collection names).

**Notes:**
- The Chroma directory and `files/` parent are auto-created on first use.
- Every workflow gets its own isolated store — two workflows can reuse the same collection name without conflict.
- Re-running the node is a no-op when the collections already exist.
- Chroma's default embedding function downloads `all-MiniLM-L6-v2` on first use (~80 MB, cached under `~/.cache/chroma`). Supply pre-computed `embeddings` in `vector_add` to skip the default embedder entirely.
- Pass Chroma index tuning (e.g. `{"hnsw:space": "cosine"}`) via the per-collection `metadata` dict when provisioning.

**Using the data from other nodes:**
```python
# In any node extending BaseNode:
await self.vector_add(
    "documents",
    ids=["doc-1", "doc-2"],
    documents=["the quick brown fox", "a lazy dog"],
    metadatas=[{"source": "rss"}, {"source": "rss"}],
)

result = await self.vector_query(
    "documents", query_texts=["fox"], n_results=3, where={"source": "rss"}
)
# result["ids"], result["documents"], result["distances"] are lists-of-lists,
# keyed per input query_text.
```

## Gmail (`choola.core.nodes.gmail.Gmail`)

**Category:** output
**Purpose:** Sends an email via the Gmail API using OAuth2 credentials.

**Requires:** A stored credential (`await self.get_credential(name)`) with provider `google` whose granted scopes include `gmail.send`.

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `credential_name` | string | yes | — | Name of the stored Google OAuth2 credential (must include scope `gmail.send`) |
| `to_email` | string | yes | — | Recipient email address |
| `subject` | string | yes | — | Subject template; `{key}` interpolates payload values |
| `body` | textarea | yes | — | Body template; `{key}` interpolates payload values |
| `body_type` | select | no | `plain` | `plain` or `html` |

**Output payload:** adds `email_sent` (bool), `email_to` (str), `email_subject` (str) to existing payload

**Setup:** In Settings > Credentials, select the "Google (OAuth2)" provider, enter your Google Cloud OAuth2 Client ID and Client Secret (with Gmail API enabled), tick the `gmail.send` scope, then click "Connect with Google". If the credential already exists you can re-authorize with additional scopes checked — the flow extends the same credential rather than creating a new one. The sender address is the authenticated Google account.

## GoogleSheets (`choola.core.nodes.google_sheets.GoogleSheets`)

**Category:** processing
**Purpose:** Read, append, update, or clear ranges in a Google Sheet via the Sheets v4 API.

**Requires:** A stored credential (`await self.get_credential(name)`) with provider `google`. Read operations accept `sheets` or `sheets.readonly`; write operations (`append`, `update`, `clear`) require the `sheets` scope.

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `credential_name` | string | yes | `google` | Stored Google OAuth2 credential. Read accepts `sheets` or `sheets.readonly`; writes need `sheets`. |
| `operation` | select | no | `read` | `read`, `append`, `update`, `clear` |
| `spreadsheet_id` | string | yes | — | Spreadsheet ID from the sheet URL; `{key}` interpolates payload values |
| `range` | string | no | `Sheet1` | A1 notation, e.g. `Sheet1!A1:D10`; `{key}` interpolates payload values |
| `values` | json | no | `[]` | Append/update only — 2D array of rows OR list of `{column: value}` dicts (mapped against the sheet's header row). String leaves support `{key}` interpolation. |
| `value_input_option` | select | no | `USER_ENTERED` | `USER_ENTERED` (parses formulas/dates) or `RAW` |
| `rows_as_dicts` | select | no | `true` | On read: treat row 1 as headers and return list of dicts |

**Output payload:** adds `sheets_operation` (str), `sheets_spreadsheet_id` (str), `sheets_range` (str). Per-operation:
- `read`: `rows` (list of dicts when `rows_as_dicts=true`, else raw 2D array), `row_count` (int)
- `append`: `appended_rows` (int)
- `update`: `updated_cells` (int)
- `clear`: no extra keys

**Setup:** In Settings > Credentials, select the "Google (OAuth2)" provider, enable the Google Sheets API on your Google Cloud project, then tick the `sheets` scope (or `sheets.readonly` for read-only nodes) and click "Connect with Google". The same credential can hold additional scopes (Gmail, Drive, etc.) — re-authorizing extends it.

**Notes:**
- The credential's `provider` must be `google` and its stored `scopes` must include `sheets` (or `sheets.readonly` for read).
- `range` quirks: bare `Sheet1` reads/writes the whole tab; `Sheet1!A:A` is a whole column; `Sheet1!A1` is a single cell. The Sheets API determines the actual touched range and returns it in `sheets_range`.
- For dict-keyed `values`, the node first fetches row 1 of the target sheet to learn the column order, then maps each dict by header. Missing keys become empty strings.
- The access token is validated against Google's `tokeninfo` endpoint and refreshed via the stored `refresh_token` if expired.

## Router (`choola.core.nodes.router.Router`)

**Category:** routing
**Purpose:** Activate exactly one of N downstream branches by matching a single payload key against a value map. The declarative way to express the classifier-then-dispatch pattern in the DAG instead of writing custom `execute()` code that sets `__active_branches__` by hand.

**Fields:**
| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `match_key` | string | yes | — | Payload key whose value selects the branch. |
| `branches` | json | yes | `{}` | Mapping of value -> target node_id, e.g. `{"chase": "chase_parser"}`. Keys are stringified for comparison. |
| `default` | string | no | `""` | node_id to activate when no branch matches. Empty = skip all branches. |

**Output payload:** adds `router_matched` (str or null — the value that matched, `"__default__"` when the default branch fired, or `None` when no branch matched) and the engine-magic `__active_branches__` (popped by the engine before downstream nodes see it).

**Wrapper contract:**
- The wrapper's `next_nodes` MUST be the full set of possible targets — every value in `branches` plus the `default` if set. The engine uses this list to compute which siblings to SKIP. The Router raises `ValueError` at runtime if a resolved target isn't in `next_nodes`.
- Match is value-equality with stringification: `str(payload[match_key])` is looked up in `branches`. That means routing on a bool uses `{"True": ..., "False": ...}` as branch keys. For range/threshold routing, do the bucketing in an upstream classifier node that sets a discrete key (e.g. `payload["bucket"] = "high"`), then route on that key.
- For routing logic that doesn't fit value-equality, write a custom node that sets `payload["__active_branches__"]` directly — the Router is a convenience, not the only path.

**Example wrapper:**

```python
from choola.core.nodes.router import Router

class BankRouter(Router):
    node_id = "bank_router"
    name = "Route by bank"
    next_nodes = ["chase_parser", "wells_fargo_parser", "generic_parser"]
    fields = [
        {"name": "match_key", "type": "string", "default": "bank"},
        {"name": "branches", "type": "json",
         "default": {"chase": "chase_parser", "wells_fargo": "wells_fargo_parser"}},
        {"name": "default", "type": "string", "default": "generic_parser"},
    ]
```

## Branching & Merging (Engine Features)

These are engine-level capabilities available to any node, not a separate core node class. Independent branches run **concurrently** — see the Parallel Execution subsection in `choola/CLAUDE.md` for details.

### Conditional Routing (`__active_branches__`)

Any node can return `__active_branches__` in its payload to choose which `next_nodes` to activate. The engine pops this key before passing the payload downstream. For the common "match one key, pick one branch" case, prefer the `Router` core node above — it's a declarative wrapper around this same mechanism.

```python
async def execute(self, payload, context):
    if payload.get("priority") == "high":
        payload["__active_branches__"] = ["urgent_handler"]
    else:
        payload["__active_branches__"] = ["normal_handler"]
    return payload
```

Nodes on inactive branches (and their descendants) get `SKIPPED` status. A merge-point node is only skipped if ALL of its parents are skipped.

### Merge-Point Input (`context["parent_outputs"]`)

When a node has multiple parents (merge point), the engine shallow-merges all active parents' outputs in topological order as the node's input payload. For nodes that need to distinguish which parent produced which data, the individual parent outputs are available in `context["parent_outputs"]` — a dict keyed by parent `node_id`. With the concurrent scheduler, this is a per-task snapshot taken at spawn time; concurrent tasks don't share `context["parent_outputs"]` state.

```python
async def execute(self, payload, context):
    # payload has the shallow-merged result from all parents
    # context["parent_outputs"] has per-parent dicts if you need them
    branch_a_data = context["parent_outputs"].get("branch_a", {})
    branch_b_data = context["parent_outputs"].get("branch_b", {})
    return payload
```
