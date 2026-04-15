# Choola — Workflow Authoring Guide

This file defines the rules for building workflows with Choola. It is the single source of truth for any agent or developer creating or editing workflows.

## Workflow Structure

```
workflows/<name>/
  topology.json           # DAG: nodes + edges
  nodes/
    __init__.py
    <node_name>.py        # One file per node, self-contained
  static/                 # Static assets (templates, schemas, seed data)
  tmp/                    # Runtime temp files (gitignored, auto-created)
```

## Node Contract

Every node file MUST:

1. Start with the `@choola-node` grep-friendly docstring block
2. Inherit from a core node (`choola.core.nodes.*`) or from `choola.core.base_node.BaseNode`
3. Be self-contained — no cross-node imports
4. Communicate exclusively via `payload: dict` passed through `execute()`
5. Declare `name`, `category`, `description`, and `fields` class attributes
6. Store static assets in `workflows/<name>/static/` — never inside the .py file
7. Use `workflows/<name>/tmp/` for temp files — create with `Path(...).mkdir(parents=True, exist_ok=True)`

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
    name = "My Contact Form"
    category = "input"
    description = "Custom contact form"
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
    name = "CSV Append"
    category = "output"
    description = "Appends a row to a CSV file"
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
@category: <category>
@description: <one-line description>
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

## topology.json

Defines the workflow DAG. Each node entry references a type string matching the Python module path:

```json
{
  "nodes": [
    {
      "id": "node_1",
      "type": "workflows.my_workflow.nodes.my_form.MyContactForm",
      "data": { "config": { "path": "/forms/contact" } }
    }
  ],
  "edges": [
    { "source": "node_1", "target": "node_2" }
  ]
}
```

## Available Helpers

Any node can use these (inherited from BaseNode):

- `await self.get_global(key)` — read a persistent global variable
- `await self.set_global(key, value)` — write a persistent global variable
- `await self.get_credential(name)` — retrieve a stored credential (dict with `name`, `provider`, `value`)

## CLI

```bash
choola init                              # Set up a new project
choola start                             # Start server at http://localhost:5000
choola create <workflow_name>            # Scaffold a new workflow
choola list                              # List all workflows
choola run <workflow_name> --payload '{}' # Run headlessly
choola nodes                             # List core node types
```
