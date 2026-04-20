# Add a Choola Node

You are adding a single new node to an existing Choola workflow. The authoritative rules live in `CLAUDE.md` at the project root — re-read the **Node Contract**, **Planning a Node**, and **Core Nodes** sections before writing code.

## What the user provides

- The workflow it belongs to (e.g. `bank-statement`). If missing, ask.
- What the node should do.
- Optionally: input/output payload shape, config fields, external deps.

## Steps

1. **Clarify the contract, not just the behavior.** Before any code, list in plain prose: input-payload keys (where they come from upstream), output-payload keys this node adds/overwrites, any side effects. See **Planning a Node** in `CLAUDE.md`.
2. **Read the existing workflow.** Check every file in `workflows/<name>/nodes/` so you know the current DAG (via each node's `node_id` + `next_nodes`) and the payload shape where your new node fits.
3. **Decide the insertion point.** The new node's `node_id` is unique snake_case. Pick which existing node(s) will list it in their `next_nodes`, and what this node's `next_nodes` should be.
4. **Write the node file** at `workflows/<workflow_name>/nodes/<node_name>.py`.
   - Start with the full `@choola-node` docstring block (see `CLAUDE.md` → **The @choola-node Docstring**).
   - Inherit from `choola.core.base_node.BaseNode` or a core node like `choola.core.nodes.form_trigger.FormTrigger`. **Never** reference a core node directly from a workflow — always subclass.
   - Declare `node_id`, `name`, `category`, `description`, `fields`, `next_nodes`.
   - Every `fields` entry that the node requires to run MUST have a `default` — `self.config` is populated from defaults only.
   - Binary data (images, PDFs, etc.) goes to `workflows/<name>/files/`, never the payload.
5. **Wire it into the DAG.** Edit the upstream node's `next_nodes` to include your new node's `node_id`. No `topology.json` — the engine builds the graph from these attributes.
6. **Validate by import, not execution.** Run `choola list` or `python -c "import workflows.<name>.nodes.<node>"` to catch syntax / import errors. Do NOT run `choola run` — it executes the whole chain and may hit paid APIs. Ask the user before any paid run.
7. **Summarize:** what the node does, its `node_id`, which nodes feed it, which nodes it feeds, the payload shape before/after.

## After creation

If the user needs to iterate on the node, use `choola replay <workflow> <run_id> <node_id>` — it re-executes just this node against a saved evaluation's input, avoiding upstream costs.

$ARGUMENTS
