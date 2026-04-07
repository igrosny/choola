# Build a Choola Node

You are helping the user create a single new node for an existing (or new) Choola workflow.

## What the user provides

The user will describe what the node should do. They may also specify:
- Which workflow it belongs to (e.g. `encrypt_vocals`)
- The input/output payload shape
- Config fields
- External dependencies

If the workflow name is missing, ask for it.

## Steps

1. **Understand what the node does** — ask clarifying questions if the purpose is ambiguous.
2. **Check existing nodes** in the target workflow (`workflows/<name>/nodes/`) to understand the current payload shape and where this node fits in the chain.
3. **Create the node file** at `workflows/<workflow_name>/nodes/<node_name>.py` following ALL rules below.
4. **Update `topology.json`** to wire the new node into the DAG at the correct position.
5. **Show a summary**: what the node does, its position in the chain, and the payload shape before/after.

## Node file rules

Every node file MUST start with the grep-friendly docstring:

```python
"""
@choola-node: <ClassName>
@category: <input|processing|routing|output|validation|integration>
@description: <one sentence>
@input-payload:
  - <key> (type): <description>
@output-payload:
  - <key> (type): <description>
@config-fields:
  - <field> (type, default=<val>): <description>   # or "none"
@example-input: {"key": "value"}
@example-output: {"key": "transformed"}
@side-effects: <none | description>
@errors: <when this node raises>
"""
```

Then the class:

```python
from typing import Any

from core.base_node import BaseNode


class ClassName(BaseNode):
    name = "Human Readable Name"
    category = "processing"
    description = "Same as @description above."
    fields = [
        {"name": "field_name", "type": "string", "default": "value"},
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        # logic here
        return payload
```

## Topology wiring

When adding to `topology.json`, use this format for the new node entry:

```json
{
  "id": "<descriptive_id>",
  "type": "workflows.<workflow>. nodes.<file_stem>.<ClassName>",
  "position": {"x": <previous_x + 300>, "y": <same_y>},
  "data": {"label": "<Display Name>", "config": {}}
}
```

Add an edge from the previous node to this one and from this one to the next (if any).

## Global variables

If the node needs to persist state across runs, use `await self.get_global(key)` and `await self.set_global(key, value)`. These are backed by SQLite and injected by the engine.

## After creation

Remind the user they can test with:
```bash
python cli.py run <workflow_name> --payload '{"key": "value"}'
```

$ARGUMENTS
