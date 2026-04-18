# Choola — Workflow Authoring Guide

This file defines the rules for building workflows with Choola. It is the single source of truth for any agent or developer creating or editing workflows.

## Workflow Structure

```
workflows/<name>/
  nodes/
    __init__.py
    <node_name>.py        # One file per node, self-contained
  static/                 # Static assets (templates, schemas, seed data)
  files/                  # Binary/generated files (gitignored, auto-created)
  evaluations/            # Run evaluations — one JSON per run (auto-generated)
```

## Node Contract

Every node file MUST:

1. Start with the `@choola-node` grep-friendly docstring block
2. Inherit from a core node (`choola.core.nodes.*`) or from `choola.core.base_node.BaseNode`
3. Be self-contained — no cross-node imports
4. Communicate exclusively via `payload: dict` passed through `execute()`
5. Declare `node_id`, `name`, `category`, `description`, `fields`, and `next_nodes` class attributes
6. Store static assets in `workflows/<name>/static/` — never inside the .py file
7. Use `workflows/<name>/files/` for binary/generated files — create with `Path(...).mkdir(parents=True, exist_ok=True)`
8. **Never put binary content in the payload** — write binary files (images, PDFs, etc.) to `files/` and put the file path in the payload instead
9. **Keep the `@choola-node` docstring in sync** — after ANY change to a node's fields, payload, next_nodes, side-effects, or error behavior, update the docstring block at the top of the file to match

### Required class attributes

| Attribute | Type | Description |
|---|---|---|
| `node_id` | `str` | Unique ID within the workflow (snake_case). Used to wire edges. |
| `name` | `str` | Human-readable name for the UI |
| `category` | `str` | Sidebar grouping (e.g. "input", "processing", "output") |
| `description` | `str` | Tooltip text |
| `fields` | `list[dict]` | Input field definitions for the UI |
| `next_nodes` | `list[str]` | List of `node_id` values this node passes output to. Empty list `[]` for terminal nodes. |

## Core Nodes — Always Extend, Never Instantiate Directly

Core nodes live in the `choola` package and provide reusable base behavior. **You must never reference a core node directly in `topology.json`.** Instead, create a wrapper class in your workflow's `nodes/` directory that extends the core node.

See `choola/core/CLAUDE.md` for the full reference of available core nodes and their fields.

### Example: Extending a Core Node

```python
"""
@choola-node: MyContactForm
@category: input
@description: Contact form for my workflow
...
"""
from choola.core.nodes.form_trigger import FormTrigger

class MyContactForm(FormTrigger):
    node_id = "contact_form"
    name = "My Contact Form"
    category = "input"
    description = "Custom contact form"
    next_nodes = ["csv_append"]
    fields = [
        {"name": "path", "type": "string", "default": "/forms/contact"},
        {"name": "form_title", "type": "string", "default": "Contact Us"},
        # ... configure form_fields, response_mode, etc.
    ]
```

### Example: Custom Node from BaseNode

```python
"""
@choola-node: CsvAppend
@category: output
@description: Appends payload data to a CSV file
@input-payload:
  - data (dict): Key-value pairs to write as a row
@output-payload:
  - csv_path (str): Path to the CSV file
...
"""
from pathlib import Path
from choola.core.base_node import BaseNode

class CsvAppend(BaseNode):
    node_id = "csv_append"
    name = "CSV Append"
    category = "output"
    description = "Appends a row to a CSV file"
    next_nodes = []
    fields = [
        {"name": "file_path", "type": "string", "required": True},
        {"name": "columns", "type": "json", "default": "[]"},
    ]

    async def execute(self, payload, context):
        # Your logic here
        return payload
```

## The @choola-node Docstring

Every node file must start with this grep-friendly block:

```
@choola-node: <NodeClassName>
@node-id: <unique_snake_case_id>
@category: <category>
@description: <one-line description>
@next-nodes: <comma-separated node_ids, or "none">
@input-payload:
  - <key> (<type>): <description>
@output-payload:
  - <key> (<type>): <description>
@config-fields:
  - <field_name> (<type>, <constraints>): <description>
@example-input: <JSON>
@example-output: <JSON>
@side-effects: <description or "none">
@errors: <description or "none">
```

## How the DAG Works

The workflow DAG is defined entirely in code. Each node declares:
- `node_id` — its unique identity
- `next_nodes` — which node(s) receive its output

The engine scans all node files in `nodes/`, discovers nodes by their `node_id`, and builds the execution graph from `next_nodes`. No topology.json needed.

```
ContactForm (node_id="contact_form", next_nodes=["csv_append"])
    └──> CsvAppend (node_id="csv_append", next_nodes=[])
```

## Available Helpers

Any node can use these (inherited from BaseNode):

- `await self.get_global(key)` — read a persistent global variable
- `await self.set_global(key, value)` — write a persistent global variable
- `await self.get_credential(name)` — retrieve a stored credential (dict with `name`, `provider`, `value`)

## Evaluations — Debugging Workflow Runs

Every workflow run automatically saves an evaluation file at `workflows/<name>/evaluations/<run_id>.json`. This is the primary way to debug workflows.

### Running a workflow and checking the evaluation

```bash
choola run <workflow_name> --payload '{}'
# Output includes: [choola] Evaluation saved: workflows/<name>/evaluations/<run_id>.json
```

Then read the evaluation file to inspect what happened.

### Evaluation file structure

Each evaluation JSON contains the full execution trace:

```json
{
  "run_id": "a1b2c3d4e5f6",
  "workflow": "my-workflow",
  "status": "COMPLETED",
  "started_at": "2026-04-15T10:00:00+00:00",
  "finished_at": "2026-04-15T10:00:03+00:00",
  "duration_ms": 3021,
  "initial_payload": {},
  "nodes": [
    {
      "node_id": "start",
      "node_type": "workflows.my-workflow.nodes.start.Start",
      "status": "COMPLETED",
      "started_at": "...",
      "finished_at": "...",
      "duration_ms": 12,
      "input": {},
      "output": {"triggered_at": "...", "trigger_type": "manual"},
      "error": null
    },
    {
      "node_id": "process",
      "node_type": "workflows.my-workflow.nodes.process.Process",
      "status": "ERROR",
      "started_at": "...",
      "finished_at": "...",
      "duration_ms": 45,
      "input": {"triggered_at": "...", "trigger_type": "manual"},
      "output": null,
      "error": "Traceback (most recent call last):\n  File ..."
    }
  ],
  "final_payload": null,
  "error": "Traceback (most recent call last):\n  File ..."
}
```

### How to debug a workflow

1. **Run the workflow**: `choola run <name> --payload '{}'`
2. **Read the evaluation file**: the path is printed at the end of the run. Evaluations are also saved on errors.
3. **Check the top-level `status`**: `"COMPLETED"` or `"ERROR"`
4. **Find the failing node**: look for the node entry where `"status": "ERROR"` — its `"error"` field contains the full Python traceback
5. **Trace data flow**: nodes are listed in execution order. Each node's `input` is exactly what it received, and `output` is what it returned. Compare a node's `output` with the next node's `input` to verify data is flowing correctly.
6. **Check `initial_payload`**: confirms what the workflow received at the start
7. **Check `final_payload`**: the output of the last successful node (or `null` on error)

### Key debugging patterns

- **Node received wrong data**: compare the previous node's `output` with the failing node's `input`
- **Node produced wrong data**: check the node's `output` and compare with `@output-payload` in its docstring
- **Node crashed**: read the `error` field for the full traceback — fix the node's `execute()` method
- **Workflow succeeded but wrong result**: check `final_payload` and trace backward through nodes to find where the data diverged

### Replaying a single node

Instead of re-running the entire workflow to test a fix, use `choola replay` to execute one node in isolation using the exact input it received in a previous run.

**Basic usage — replay a node with its saved input:**

```bash
# 1. Find the run_id and node_id from a previous evaluation
cat workflows/my-workflow/evaluations/a1b2c3d4e5f6.json | jq '.nodes[] | {node_id, status}'

# 2. Replay that node
choola replay my-workflow a1b2c3d4e5f6 process
```

This loads the evaluation, extracts the `input` that `process` received during run `a1b2c3d4e5f6`, and re-executes the node's current code against that input. The output is printed to stdout.

**Override the input payload:**

```bash
choola replay my-workflow a1b2c3d4e5f6 process --payload '{"key": "new_value"}'
```

Use `--payload` to test the node with modified input without editing the evaluation file.

**Suppress the diff:**

```bash
choola replay my-workflow a1b2c3d4e5f6 process --no-diff
```

By default, if the original run produced output for this node, `replay` shows what changed between the saved output and the new output. Use `--no-diff` to suppress this.

**When to use replay:**

- **Node crashed** — fix the `execute()` method, then replay to verify the fix without re-running upstream nodes
- **Node produced wrong data** — edit the node logic, replay with the same input, check the new output
- **Test edge cases** — use `--payload` to feed the node unusual input and verify it handles it correctly
- **Expensive upstream nodes** — avoid re-running LLM calls, API requests, or form submissions just to test a downstream node

**Important:** Replay re-executes the node's code live. Side effects (file writes, API calls, database changes) will happen again. Credentials are fetched from the current database, not from the evaluation.

## CLI

```bash
choola init                              # Set up a new project
choola start                             # Start server at http://localhost:5000
choola create <workflow_name>            # Scaffold a new workflow
choola list                              # List all workflows
choola run <workflow_name> --payload '{}' # Run headlessly
choola replay <workflow> <run_id> <node_id>  # Re-run one node with saved input
choola nodes                             # List core node types
```
