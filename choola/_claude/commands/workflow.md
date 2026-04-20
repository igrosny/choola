# Build a Choola Workflow

You are building a new Choola workflow end-to-end (or explaining an existing one). The authoritative rules live in `CLAUDE.md` at the project root — **read it in full** before writing code. This file gives you the process, not the rules.

## What the user provides

- What the workflow should do.
- Optionally: the trigger (form, webhook, manual), external services it must call, the final output.

Ask only what's actually ambiguous — don't interview.

## If the user says…

- "create a workflow that …" → build a new workflow from scratch (steps below).
- "add a node to <workflow> that …" → use the `/node` command instead.
- "show me what <workflow> does" → **read the files**, don't guess. Report each node's real `@input-payload` / `@output-payload` and trace the DAG by following `next_nodes`. Never fabricate docs — if a node lacks docstrings, say so and offer to add them.

## Building a new workflow

1. **Design on paper first.** List the node chain:
   - What each node does (one job per node — see **Planning a Node** in `CLAUDE.md`).
   - The payload shape at each step (`@input-payload` / `@output-payload`).
   - Which node is the trigger. Default to `FormTrigger` — its fields double as CLI positional args and it renders a browser form. Use `ManualTrigger` only for zero-input workflows, `WebhookTrigger` when an external system calls in.
2. **Scaffold the folder.** `choola create <workflow_name>` creates `workflows/<name>/` with `nodes/__init__.py`. Do NOT create a `topology.json` — the DAG lives in the node class attributes.
3. **Write each node file.**
   - Start with the full `@choola-node` docstring block.
   - Subclass `choola.core.base_node.BaseNode` or a core node (`choola.core.nodes.form_trigger.FormTrigger`, etc.). **Never** reference a core node directly — always subclass so the workflow can set `node_id`, `next_nodes`, and defaults.
   - Declare `node_id`, `name`, `category`, `description`, `fields`, `next_nodes`. Use the first node's `next_nodes` to wire to the second node's `node_id`, and so on. Terminal nodes have `next_nodes = []`.
   - Every `fields` entry needed at runtime MUST have a `default` — `self.config` is populated from defaults, not from the UI.
   - Branching: a node can list multiple `next_nodes`; each branch gets an isolated copy of the payload. Merge nodes can read individual parents via `context["parent_outputs"]`. Conditional routing: return `__active_branches__: [...]` in the payload.
   - Binary data goes to `workflows/<name>/files/`. Static assets (templates, schemas) go to `workflows/<name>/static/`.
4. **Cost discipline.** Tag any node hitting paid APIs with `@cost: paid-one-shot | paid-per-item | paid-per-call`. Loop nodes MUST expose `max_items` (default 20) and `max_consecutive_errors` (default 3). Any LLM call must invoke `self.report_tokens(...)`. See **Cost Discipline** in `CLAUDE.md`.
5. **Validate without running.** `choola list` confirms the workflow is discoverable. `python -c "import workflows.<name>.nodes.<node>"` catches import errors. Do NOT run `choola run` during scaffolding — ask the user first, and only after required credentials are in place.
6. **Summarize.** List each node in execution order, its one-line job, and the payload shape at each step.

## Credentials

If a node needs a credential, declare the credential *name* as a field default (not the value), and fetch it at runtime with `await self.get_credential(name)`. Tell the user which credentials they need to create via `choola credential <name>`.

$ARGUMENTS
