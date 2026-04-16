# Choola

A workflow automation engine that bridges the determinism of Python with the power of agentic AI programming — built so developers who are just getting started can wire together LLM-powered pipelines without giving up predictability or control.

The idea is simple: you build workflows from self-contained Python nodes, connect them in a visual editor, and let AI agents (Claude, Gemini) do the heavy lifting inside those nodes — while the overall flow remains explicit, inspectable, and reproducible.

---

> **⚠️ Early-Stage Project — Not for Production**
>
> Choola is under active development. Core node classes, the payload contract, and internal APIs **may change drastically between versions** without backward compatibility. We do not recommend using Choola in production systems at this time. It is intended as an exploration platform and learning tool.

---

## What It's For

Choola was built for beginner developers who want to:

- Build multi-step automations that include AI without writing orchestration from scratch
- See exactly what data flows through each step (no black boxes)
- Mix deterministic Python logic with LLM calls in a single workflow
- Use a visual editor to prototype, then inspect the underlying code to learn

It is not trying to be n8n or Airflow. It's trying to be the simplest possible on-ramp to agentic programming for someone who knows a bit of Python.

---

## How It Works

A **workflow** is a folder containing:

- `topology.json` — a DAG (directed acyclic graph) of nodes and the edges between them
- `nodes/*.py` — one Python file per node

Each node receives a `payload` dict, does one thing, and returns the (possibly modified) payload to the next node. The engine topologically sorts the nodes and executes them in order.

```
workflows/my_workflow/
├── topology.json
└── nodes/
    ├── __init__.py
    ├── fetch_data.py
    ├── summarize.py
    └── send_email.py
```

---

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm

---

## Installation

```bash
# Clone the repository
git clone https://github.com/igrosny/choola.git
cd choola

# Create a virtual environment and install the package
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -e .

# Build the frontend
cd frontend
npm install
npm run build
cd ..
```

---

## Quick Start

```bash
# Initialize a project (creates choola.db)
choola init

# Start the server
choola start
# → http://localhost:5000
```

Open [http://localhost:5000](http://localhost:5000) in your browser. You'll see the visual workflow editor where you can:

- Create new workflows
- Add nodes and configure them
- Connect nodes by dragging edges
- Run workflows and watch execution stream live

### CLI usage

```bash
choola init                               # Set up a new project
choola start                              # Start the server (localhost:5000)
choola start --host 0.0.0.0 --port 8080  # Bind to all interfaces
choola create <workflow_name>             # Scaffold a new workflow
choola list                               # List all workflows
choola run <workflow_name> --payload '{"key": "value"}'  # Run headlessly
choola nodes                              # List available core node types
```

---

## Writing a Node

Every node is a single `.py` file in `workflows/<name>/nodes/`. The `@choola-node` docstring makes it discoverable — do not remove it.

```python
"""
@choola-node: MyNodeName
@category: processing
@description: Does one specific thing to the payload.
@input-payload:
  - some_key (str): What this node expects
@output-payload:
  - some_key (str): Same or transformed
  - new_key (int): Something this node adds
@config-fields:
  - threshold (int, default=10): Controls the threshold
@example-input: {"some_key": "hello"}
@example-output: {"some_key": "hello", "new_key": 42}
@side-effects: none
@errors: Raises ValueError if some_key is missing
"""

from typing import Any
from choola.core.base_node import BaseNode


class MyNodeName(BaseNode):
    name = "My Node Name"
    category = "processing"
    description = "Does one specific thing to the payload."
    fields = [
        {"name": "threshold", "type": "number", "default": 10},
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        # Your logic here
        return payload
```

### Node rules

- **Self-contained** — all logic in one file, no cross-node imports
- **JSON in, JSON out** — communicate only through the `payload` dict
- **Docstring required** — the `@choola-node` markers make nodes grep-discoverable

### Node categories

| Category | Use for |
|---|---|
| `input` | Entry points — webhooks, forms, file reads |
| `processing` | Transformation, enrichment, LLM calls |
| `routing` | Conditional branching, filtering |
| `output` | Sending results, notifications, writes |
| `validation` | Data checks, guards |
| `integration` | External API calls |

### Persisting state across runs

```python
value = await self.get_global("my_key")
await self.set_global("my_key", "new_value")
```

---

## Core Nodes

Core nodes are built into the `choola` package. **Never reference them directly in `topology.json`** — instead, create a thin wrapper class in your workflow's `nodes/` directory that extends the core node.

Every workflow must have exactly one trigger node as its entry point.

### ManualTrigger

Starts a workflow manually via the UI or CLI. No external event needed — use this when the workflow doesn't need a webhook or form to kick it off.

```python
from choola.core.nodes.manual_trigger import ManualTrigger

class Start(ManualTrigger):
    pass
```

No configuration fields.

**Output payload:** `{ triggered_at: "<ISO timestamp>", trigger_type: "manual" }`

---

### WebhookTrigger

Starts a workflow when an HTTP request hits a registered endpoint.

```python
from choola.core.nodes.webhook_trigger import WebhookTrigger

class MyWebhook(WebhookTrigger):
    pass
```

| Field | Type | Description |
|---|---|---|
| `path` | str | URL path, e.g. `/hooks/my-endpoint` |
| `method` | select | GET / POST / PUT / DELETE (default: POST) |
| `response_mode` | select | `immediate` (returns 202 at once) or `after_workflow` (waits for result) |

**Output payload:** `{ method, headers, query, body }`

---

### FormTrigger

Serves an HTML form at a URL; submission triggers the workflow.

```python
from choola.core.nodes.form_trigger import FormTrigger

class MyForm(FormTrigger):
    pass
```

| Field | Type | Description |
|---|---|---|
| `path` | str | URL path, e.g. `/forms/contact` |
| `form_title` | str | Heading above the form |
| `form_description` | str | Description below the title |
| `form_fields` | json | Array of field definitions (see below) |
| `response_mode` | select | `after_workflow` (returns JSON) or `redirect` (shows thank-you page) |
| `submit_label` | str | Button label (default: Submit) |

Each item in `form_fields`:
```json
{
  "label": "Email",
  "field_name": "email",
  "field_type": "email",
  "required": true,
  "placeholder": "you@example.com"
}
```

Supported `field_type` values: `text`, `email`, `number`, `password`, `textarea`, `dropdown`, `date`, `checkbox`

**Output payload:** `{ form_data: { field_name: value, ... }, submitted_at: "<ISO timestamp>" }`

---

### LLM

Sends a prompt to an LLM and returns the response. Supports Claude and Gemini.

```python
from choola.core.nodes.llm import LLM

class Summarize(LLM):
    pass
```

| Field | Type | Description |
|---|---|---|
| `credential_name` | str | Name of the stored credential to use |
| `provider` | select | `claude` or `gemini` |
| `model` | str | Model ID (defaults: `claude-sonnet-4-20250514` / `gemini-2.0-flash`) |
| `prompt` | textarea | Prompt template; use `{key}` to interpolate payload values |
| `system_prompt` | textarea | Optional system prompt |
| `max_tokens` | number | Default: 1024 |
| `temperature` | number | Default: 1.0 |

**Output payload:** adds `llm_response`, `llm_model`, `llm_provider` to the existing payload

---

### Gmail

Sends an email via the Gmail API using OAuth2 credentials.

```python
from choola.core.nodes.gmail import Gmail

class SendEmail(Gmail):
    pass
```

| Field | Type | Description |
|---|---|---|
| `credential_name` | str | Name of the stored Gmail OAuth2 credential |
| `to_email` | str | Recipient email address |
| `subject` | str | Subject template; use `{key}` to interpolate payload values |
| `body` | textarea | Body template; use `{key}` to interpolate payload values |
| `body_type` | select | `plain` or `html` (default: plain) |

**Output payload:** adds `email_sent`, `email_to`, `email_subject` to the existing payload

**Setup:** Gmail requires OAuth2. Go to Settings > Credentials, add a Gmail credential, and complete the OAuth2 flow. The server handles the flow at `/api/oauth2/gmail/start` and `/api/oauth2/gmail/callback`.

---

## Credentials

API keys and OAuth tokens are stored encrypted in the SQLite database and never hardcoded.

### Managing credentials

```bash
# Via the UI: Settings > Credentials

# Via API:
GET    /api/credentials          # List all (values masked)
POST   /api/credentials          # Create/update: { name, provider, value }
DELETE /api/credentials/<name>   # Delete
```

### Using credentials in a node

```python
cred = await self.get_credential("my-anthropic-key")
api_key = cred["value"]
```

---

## API Reference

| Method | Path | Description |
|---|---|---|
| GET | `/api/nodes` | List all registered node types |
| GET | `/api/nodes/<node_type>/fields` | Get field definitions for a node |
| GET | `/api/nodes/<node_type>/source` | Read node source code |
| PUT | `/api/nodes/<node_type>/source` | Update node source code |
| GET | `/api/workflows` | List all workflows |
| POST | `/api/workflows` | Create a new workflow |
| GET | `/api/workflows/<name>/topology` | Get workflow topology |
| PUT | `/api/workflows/<name>/topology` | Update workflow topology |
| POST | `/api/workflows/<name>/run` | Execute a workflow |
| GET | `/api/workflows/<name>/stream/<run_id>` | SSE stream for live run status |
| POST | `/api/workflows/<name>/refresh` | Re-discover nodes from disk |
| POST | `/api/workflows/<name>/chat` | Chat with Claude about the workflow (SSE) |
| GET | `/api/workflows/<name>/trigger-info` | Get trigger type and config |
| GET | `/api/credentials` | List all credentials (values masked) |
| POST | `/api/credentials` | Create/update credential |
| DELETE | `/api/credentials/<name>` | Delete credential |
| POST | `/api/oauth2/gmail/start` | Initiate Gmail OAuth2 flow |
| GET | `/api/oauth2/gmail/callback` | Gmail OAuth2 callback |

---

## Evaluations

Every workflow run automatically saves an evaluation file for debugging:

```
workflows/<name>/evaluations/<run_id>.json
```

Each evaluation captures the full execution trace: initial and final payloads, per-node timing, inputs, outputs, and any errors. Use these to inspect exactly what happened at each step.

---

## Project Structure

```
choola/                        # The pip-installable package
├── cli.py                     # CLI entry point
├── server.py                  # Flask API + serves the React frontend
├── database.py                # SQLite store (globals + run logs + credentials)
├── evaluations.py             # Run evaluation storage (one JSON per run)
├── core/
│   ├── base_node.py           # Abstract base class for all nodes
│   └── nodes/                 # Built-in core nodes
│       ├── trigger.py         # Base Trigger class
│       ├── manual_trigger.py
│       ├── webhook_trigger.py
│       ├── form_trigger.py
│       ├── llm.py
│       └── gmail.py
└── static/                    # Built frontend (generated — not in source)

frontend/                      # React + XyFlow visual editor (Vite)

workflows/                     # Your workflows live here (created by choola create)
└── <workflow_name>/
    ├── topology.json
    ├── nodes/
    │   ├── __init__.py
    │   └── <node>.py
    ├── evaluations/           # Auto-generated run traces
    └── files/                 # Binary/generated files
```

---

## Using with Claude Code

If you use [Claude Code](https://claude.ai/code), this project ships with slash commands that let you build workflows by describing what you want:

- **`/choola`** — describe a workflow and Claude scaffolds the full thing (nodes + topology)
- **`/node`** — add a single node to an existing workflow

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
