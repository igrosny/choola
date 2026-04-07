# Choola Workflow Builder

You are helping the user build workflows in the Choola workflow engine. Follow these rules strictly.

## Project Structure

Workflows live under `workflows/<workflow_name>/` with this layout:

```
workflows/<workflow_name>/
  topology.json        # DAG definition: nodes + edges
  nodes/
    __init__.py
    <node_name>.py     # One file per node — self-contained
```

## How to Use This Skill

The user will describe what they want the workflow to do. Your job:

1. **Understand the goal** — ask clarifying questions if the workflow purpose is unclear.
2. **Design the node chain** — break the workflow into discrete, self-contained steps. Each node does ONE thing.
3. **Create the workflow** — scaffold the folder, write node files, and wire up `topology.json`.

When the user says something like:
- "create a workflow that ..." → create a new workflow from scratch
- "add a node to <workflow> that ..." → add a single node to an existing workflow
- "show me what <workflow> does" → read and explain the workflow

## Node Rules

Every node MUST:

1. **Be self-contained** — all logic lives in a single `.py` file. No cross-node imports.
2. **Inherit from `BaseNode`** — import from `core.base_node`.
3. **Communicate via JSON payloads** — the `execute()` method receives a `payload: dict` and returns a `dict`. That dict is the message to the next node.
4. **Be documented for AI agent discovery** — use the grep-friendly docstring format below.

### Grep-Friendly Node Documentation Format

Every node file MUST start with a docstring block using these exact markers so an AI agent can `grep` for them:

```python
"""
@choola-node: <NodeClassName>
@category: <category>
@description: <what this node does in one sentence>
@input-payload:
  - <key> (type): <description>
@output-payload:
  - <key> (type): <description>
@config-fields:
  - <field_name> (type, default=<val>): <description>
@example-input: {"key": "value"}
@example-output: {"key": "transformed_value"}
@side-effects: <none | describe external calls, DB writes, etc.>
@errors: <describe when this node raises exceptions>
"""
```

These `@choola-node` markers let any AI agent run:
- `grep -r "@choola-node"` to find all available nodes
- `grep -r "@input-payload" workflows/<name>/` to see what data each node expects
- `grep -r "@output-payload" workflows/<name>/` to see what data each node produces
- `grep -r "@category: routing"` to find all routing nodes
- `grep -r "@side-effects"` to find nodes with external dependencies

### Node Class Template

```python
"""
@choola-node: MyNodeName
@category: processing
@description: Does one specific thing to the payload.
@input-payload:
  - some_key (str): Description of expected input
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

from core.base_node import BaseNode


class MyNodeName(BaseNode):
    name = "My Node Name"
    category = "processing"
    description = "Does one specific thing to the payload."
    fields = [
        {"name": "threshold", "type": "number", "default": 10},
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        # Node logic here
        return payload
```

### Categories

Use these standard categories (or create new ones if none fit):
- `input` — entry points, data ingestion
- `processing` — transformation, enrichment, scoring
- `routing` — conditional branching, assignment
- `output` — sending results, notifications, API calls
- `validation` — data checks, guards
- `integration` — external API calls, third-party services

## Topology Format

`topology.json` defines the DAG. Nodes reference their fully-qualified Python class:

```json
{
  "nodes": [
    {
      "id": "<unique_id>",
      "type": "workflows.<workflow_name>.nodes.<file_stem>.<ClassName>",
      "position": {"x": 100, "y": 200},
      "data": {"label": "<Display Name>", "config": {}}
    }
  ],
  "edges": [
    {"id": "e1", "source": "<node_id>", "target": "<node_id>"}
  ]
}
```

- Node `id` values should be descriptive: `ingest_1`, `score_1`, `validate_1`
- Space nodes 300px apart on the x-axis for the UI
- Always wire edges in execution order

## Help Documentation Rule

When the user asks "what does this workflow/node do?", ALWAYS:

1. **Read the actual files** — do NOT describe from memory or guesses.
2. **Show the real `@input-payload` and `@output-payload`** from the docstrings.
3. **Trace the actual data flow** through the topology edges.
4. **Report real config values** from `topology.json`, not defaults.

Never fabricate documentation. If a node is missing docstrings, say so and offer to add them.

## Workflow Creation Checklist

When creating a new workflow:

1. Create `workflows/<name>/nodes/__init__.py` (empty)
2. Create each node file with the full docstring format
3. Create `workflows/<name>/topology.json` wiring all nodes
4. Verify the topology has no cycles (linear chains are simplest)
5. Show the user a summary: node order, what each does, and the payload shape at each step

## Using Global Variables

Nodes can persist data across runs using `self.get_global(key)` and `self.set_global(key, value)`. Use this for:
- Caching expensive results
- Tracking state across workflow runs
- Storing counters or timestamps

## Running Workflows

After creating a workflow, remind the user they can run it with:
```bash
python cli.py run <workflow_name> --payload '{"key": "value"}'
```

Or list available workflows:
```bash
python cli.py list
```
