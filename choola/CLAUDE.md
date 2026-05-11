# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Choola — Workflow Authoring Guide

This file defines the rules for building workflows with Choola. It is the single source of truth for any agent or developer creating or editing workflows.

**Working-directory context.** When Claude Code is launched from inside a `workflows/<name>/` directory, any unqualified reference to "the workflow" in the user's prompt (create, update, add a node, rename, etc.) refers to the workflow rooted at the current working directory. Do not ask which workflow is meant unless the prompt explicitly names a different one.

## Repository Layout

This repo is a **workspace for authoring Choola workflows**, not the engine itself.

- `workflows/` — one subdirectory per workflow. Empty in a fresh checkout.
- `.venv/` — virtualenv with the `choola` engine installed. Activate with `source .venv/bin/activate` before any `choola` command.
- Core node base classes live in the installed package at `.venv/lib/python*/site-packages/choola/core/nodes/` — read them there when you need to know what a base class exposes. Never copy them into a workflow.
- There is no build, lint, or test pipeline in this workspace. Engine-level tests live upstream in `../choola`. Validate node edits with `python -c "from workflows.<name>.nodes.<node> import *"` or `choola list`, then `choola replay` against an existing evaluation.

## Useful CLI additions

In addition to the commands listed under `## CLI` below:

- `choola explain <workflow>` — prints each node's title and description in DAG order. Fastest way to orient yourself in an unfamiliar workflow without opening every node file.

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

## Planning a Node

Before creating a new node — or modifying an existing one in a way that changes its inputs, outputs, `next_nodes`, side-effects, or responsibility — outline its I/O contract in plain prose. Do this in working notes or the plan file, not in code. For body-only edits that don't change the contract (bug fixes, refactors, log tweaks), skip this step and just edit; the "keep the `@choola-node` docstring in sync" rule in **Node Contract** below already covers the after-the-fact check.

1. **One job per node (Single Responsibility).** A node may contain substantial, complex business logic, but it must do exactly *one distinct job*. Split mixed concerns across nodes and wire them via `next_nodes`.
   - **Bad:** one node fetches user data from an external API, runs a risk calculation, and writes the result to the DB.
   - **Good:** an HTTP node fetches, a "Risk Score" node does the math, a DB node writes. Each is independently replayable via `choola replay`.
   - When extending an existing node, apply the same test: if the new behavior is a genuinely distinct job, add a new node downstream rather than growing the current one.
2. **Write the contract first.** Before generating Python, list:
   - the keys the node expects in its input payload (these become `@input-payload` in the docstring),
   - the keys the node guarantees it adds or overwrites in the output payload (these become `@output-payload`).
   If a key is produced by an upstream node, name which one. If it is optional, say so and give the default the node will assume. For modifications, list only what's *changing* versus the current docstring — not the whole contract.

Keeping this step explicit makes the `@choola-node` docstring a transcript of the plan rather than an afterthought, and it exposes split/merge opportunities before any code is written.

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


## Node config at runtime — what actually reaches `self.config`

`self.config` inside `execute()` is populated **only** from the node's `fields`
`default` values. The UI's Configuration tab is currently not a runtime source
— every execution path (`choola run` and the server run endpoints)
instantiates nodes with `cls()` and no config argument.

**Rules this implies for every node:**

1. If a value is required to run, give the field a `default` — not just
   `required: True`. A required field with no default will always crash on
   `choola run`.
2. Never rely on the UI to "fill in" a config value later. If the user must
   supply it per run, take it through the form (`form_data`) or the payload,
   not via a `fields` entry.
3. Use `fields` defaults for fixed settings (model names, timeouts, credential
   *names*, column limits). Use the payload for per-run inputs (file paths,
   sheet IDs, prompts).
4. Stored credentials are looked up at runtime via
   `await self.get_credential(name)` — the *name* should have a `default` so
   the node can resolve the credential with no additional setup.

**Checklist before declaring a node done:** re-read every `fields` entry and
confirm that `choola run <workflow> --payload '{}'` would not trip on a
missing value. The canonical example of this pattern is
`resize-images/nodes/start.py`, which provides `default` values for `path`,
`form_title`, `form_fields`, `submit_label`, and `response_mode` so the
workflow is runnable without any UI-side configuration.


## Core Nodes — Always Extend, Never Instantiate Directly

Core nodes live in the `choola` package and provide reusable base behavior. **You must never reference a core node directly in `topology.json`.** Instead, create a wrapper class in your workflow's `nodes/` directory that extends the core node.


**Picking a trigger.** Default to FormTrigger for any workflow that takes runtime input. FormTrigger fields double as positional CLI arguments (choola run <workflow> <value1> <value2>) and render a browser form at the configured path. ManualTrigger accepts neither — it only works via the UI "Run" button or an explicit --payload '{...}' — so reserve it for workflows that genuinely take zero input. Use WebhookTrigger when an external system calls in.

**Picking a classifier.** When a node's job is to pick one label from a fixed/small set (yes/no, category from a list, sentiment, intent), default to extending the core LLML node — not a direct LLM call. LLML caches exact inputs in SQLite and, after `choola dream`, serves repeat patterns from a local XGBoost classifier for free. Reach for a plain LLM loop only when the output is open-ended text or the label set is unbounded.

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
@cost: <free | paid-one-shot | paid-per-item | paid-per-call> — <short description>   # optional, default: free
```

The `@cost` line is optional. When absent, the node is treated as `free` — unless its `execute()` calls `await self.get_credential(...)`, in which case treat it as paid until an explicit `@cost: free` tag is added. See `## Cost Discipline` below for the values and the rules each one triggers.

## How the DAG Works

The workflow DAG is defined entirely in code. Each node declares:
- `node_id` — its unique identity
- `next_nodes` — which node(s) receive its output

The engine scans all node files in `nodes/`, discovers nodes by their `node_id`, and builds the execution graph from `next_nodes`. No topology.json needed.

```
ContactForm (node_id="contact_form", next_nodes=["csv_append"])
    └──> CsvAppend (node_id="csv_append", next_nodes=[])
```

### Branching (Split & Merge)

A node can fan out to multiple downstream nodes by listing them in `next_nodes`. Each branch receives an isolated copy of the parent's output.

```
Trigger (next_nodes=["branch_a", "branch_b"])
    ├──> BranchA (next_nodes=["merge_point"])
    └──> BranchB (next_nodes=["merge_point"])
              └──> MergePoint (next_nodes=[])
```

**Split**: When a node has multiple `next_nodes`, each downstream node gets its own deep copy of the parent's output. Branches are isolated — mutations in one branch don't affect the other.

**Merge**: When multiple branches feed into the same node, their outputs are shallow-merged in topological order (last-writer-wins for duplicate keys). The merge node can also access individual parent outputs via `context["parent_outputs"]` — a dict keyed by parent `node_id`.

### Conditional Routing

Any node can selectively activate only some of its `next_nodes` by returning a special `__active_branches__` key in its output payload. The engine pops this key (downstream nodes never see it) and marks unreachable nodes as `SKIPPED`.

```python
class MyRouter(BaseNode):
    node_id = "router"
    next_nodes = ["high_handler", "low_handler"]

    async def execute(self, payload, context):
        if payload.get("score", 0) >= 80:
            payload["__active_branches__"] = ["high_handler"]
        else:
            payload["__active_branches__"] = ["low_handler"]
        return payload
```

Nodes on inactive branches (and their descendants) receive `SKIPPED` status in evaluations and the UI. A merge-point node is only skipped if ALL of its parents are skipped — so diamond patterns work correctly.

## Available Helpers

Any node can use these (inherited from BaseNode):

- `await self.get_global(key)` — read a persistent global variable (shared across all workflows on the host)
- `await self.set_global(key, value)` — write a persistent global variable
- `await self.get_credential(name)` — retrieve a stored credential (dict with `name`, `provider`, `value`). Returns `None` when the credential does not exist — nodes must raise a clear error in that case (see the core `LLM` and `Gmail` nodes for the pattern).
- `await self.db_query(sql, params)` — run a SELECT against the workflow's own SQLite DB at `files/db.sqlite`; returns `list[dict]` keyed by column name.
- `await self.db_execute(sql, params)` — run INSERT/UPDATE/DELETE against the workflow's DB; returns affected rowcount. Use `?` placeholders — never string-concatenate values into the SQL.
- To use the DB, add the `DB` core node to the workflow and configure its `schema` field with `CREATE TABLE IF NOT EXISTS ...`. Every workflow gets its own isolated SQLite file, so tables can't collide with other workflows.
- `await self.vector_add(collection, ids, documents=None, metadatas=None, embeddings=None)` — upsert items into the workflow's ChromaDB store at `files/chroma/`. Supply `documents` for auto-embedding or `embeddings` for pre-computed vectors.
- `await self.vector_query(collection, query_texts=None, query_embeddings=None, n_results=10, where=None, where_document=None)` — nearest-neighbour search; returns ChromaDB's native result dict.
- `await self.vector_get(collection, ids=None, where=None, limit=None)` / `vector_delete(...)` / `vector_count(collection)` — metadata-filtered fetch, deletion, and size.
- To use the vector store, add the `VectorDB` core node and configure its `collections` field. Each workflow gets its own ChromaDB directory, so collections can't collide with other workflows.
- `self.report_tokens(prompt_tokens, completion_tokens, model="", provider="")` — synchronous helper to tell the engine how many tokens a paid LLM call consumed. Nodes that talk to paid LLM APIs MUST call this after each API call. The engine persists the numbers in `run_logs` and the evaluation JSON, and enforces the `max_tokens_per_run` / `max_tokens_per_hour` globals (circuit breaker — a breach aborts the run with a `TokenLimitExceeded`). Token usage is reported via this sidechannel and is NOT part of the payload.


## Cost Discipline

Workflows regularly touch paid APIs (LLMs, third-party data providers). These rules keep an agent from burning money while creating, testing, or debugging.

1. **Identifying paid nodes.** If a node declares `@cost:` in its docstring, trust it. If the tag is absent, the node is `free` by default — **unless** its `execute()` calls `await self.get_credential(...)`, in which case treat it as paid until the author adds an explicit `@cost: free` tag. Allowed tag values:
   - `free` — no paid external dependency.
   - `paid-one-shot` — one paid call per run regardless of payload size.
   - `paid-per-item` — paid call inside a loop over a payload list.
   - `paid-per-call` — paid with variable call count (retries, streaming, fan-out).

2. **Cap fan-out loops.** Any node tagged `paid-per-item` or `paid-per-call` MUST expose a `max_items` field (small default, e.g. 20) and stop once the cap is reached. Report `processed_count` and `skipped_due_to_cap` in the output so the operator can decide whether to bump the cap.

3. **Circuit-break consecutive failures.** Paid loop nodes MUST expose `max_consecutive_errors` (default 3). On exceed, abort the loop, return partial results, and include `abort_reason` in the output. One bad API key shouldn't burn through 100 calls.

4. **Replay, don't re-run.** When iterating on a downstream node, default to `choola replay <workflow> <run_id> <node_id>` against an existing evaluation. Use `choola run` only for the first happy-path test or when upstream data has genuinely changed.

5. **No live calls during scaffolding.** While creating or editing a workflow, stop at writing nodes and import-checking them (`python -c "import ..."` or `choola list`). Before suggesting `choola run`, verify the required credentials exist with `choola credentials` (lists names + providers, never values) — don't ask the user "do you have credential X?" when you can check yourself. Still get the user's approval for the spend before the first live invocation.

6. **Cheapest model by default.** Classification and filter loops default to Haiku or Gemini Flash. Escalate to Sonnet/Opus only when the user asks.

7. **Pre-filter before paying.** Inside a paid loop, skip items with empty/missing inputs before the API call. Empty inputs go to `skipped`, not `errored` — errored slots count against the circuit breaker.

8. **Report token usage.** Any node that calls a paid LLM API MUST call `self.report_tokens(prompt, completion, model=..., provider=...)` after each call. This feeds the engine's global circuit breaker (`max_tokens_per_run`, `max_tokens_per_hour` — set via `await self.set_global(...)` or the `globals` table; `0`/absent = disabled) and populates `run_logs` + evaluation JSON for cost debugging. The core `LLM` node already does this; custom nodes must match the pattern.

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
choola dream                             # Train XGBoost classifiers for LLML nodes
choola credential <name>                 # Store a credential interactively
choola credentials                       # List stored credentials (names + providers, never values)
```

## MCP — every workflow as an AI tool

While `choola start` is running, an MCP (Model Context Protocol) server is exposed at `POST /mcp`. Every workflow on disk becomes one tool; the tool's input schema is derived from the trigger:

- **FormTrigger**: one JSON property per configured `form_fields` entry (`text`/`email`/`textarea`/`date`/`password` → string, `number` → number, `checkbox` → boolean, `dropdown` → string + `enum`). `required: true` fields become required.
- **WebhookTrigger**: `{body, method?, headers?, query?}`.
- **ManualTrigger**: `{payload?}` — arbitrary pass-through.

Tool name format: `run__<workflow_name>` (hyphens become underscores, e.g. `bank-statement` → `run__bank_statement`).

Point any MCP-capable client at the endpoint:

```json
{"mcpServers": {"choola": {"type": "http", "url": "http://localhost:5000/mcp"}}}
```

**Auth.** The endpoint is open by default (localhost-only in dev). To require a bearer token, set the `mcp_token` global. The simplest path is a one-liner from the project root:

```bash
python -c "from choola.database import set_global_sync; set_global_sync('mcp_token', '<random hex>')"
```

Clients then send `Authorization: Bearer <random hex>`. Set the value back to the empty string to turn auth off again. The startup banner reports the current state (`auth: enabled` / `auth: disabled`).
