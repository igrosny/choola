# Debug a Choola Run

The user is asking why a workflow run failed or misbehaved. Every run auto-saves an evaluation JSON at `workflows/<name>/evaluations/<run_id>.json`. That's your primary evidence — work from it, not from memory. Full format details are in the project `CLAUDE.md` under **Evaluations — Debugging Workflow Runs**.

## Inputs

The user may give you:
- A workflow name — debug its most recent run.
- A workflow name AND a `run_id` — debug that specific run.
- Nothing specific — ask which workflow, or list the workflows via `ls workflows/` if there's only one, use it.

## Steps

1. **Find the evaluation.** `ls -1t workflows/<name>/evaluations/ | head -5` lists the newest first. Pick the one the user specified, or the newest.
2. **Read the evaluation JSON in full.** Note:
   - Top-level `status`: `COMPLETED` vs `ERROR`.
   - `initial_payload` — what the workflow received.
   - `nodes[]` — each node's `status`, `input`, `output`, `error`, `duration_ms`. Nodes are in execution order.
3. **Locate the failure.** Find the first node with `status: ERROR`. Its `error` field contains the full Python traceback.
4. **Do a data-flow diff.** Compare the failing node's `input` against the upstream node's `output` and against the failing node's `@input-payload` docstring. Mismatches between the docstring and reality are the most common root cause.
5. **Propose a concrete fix.** Point to the exact file and line. If the fix is in a specific node, name it.
6. **Recommend replay, not re-run.** After editing, the user should run `choola replay <workflow> <run_id> <node_id>` — it re-executes only the failing node with the saved input. `choola run` is avoided because it may trigger paid upstream nodes again.

## What NOT to do

- Don't guess at the cause without reading the evaluation.
- Don't suggest `choola run` for verification if `choola replay` can do it — replay is free of upstream cost.
- Don't edit anything until you've told the user what's broken and what you propose to change.

$ARGUMENTS
