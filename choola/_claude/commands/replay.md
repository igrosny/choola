# Replay a Single Node

`choola replay <workflow> <run_id> <node_id>` re-executes ONE node against its saved input from a previous run. Use it to iterate on a failing node without re-running upstream (and possibly paid) nodes. Full details in the project `CLAUDE.md` under **Replaying a single node**.

## Inputs

The user may provide:
- All three: `<workflow> <run_id> <node_id>` — just run it.
- Workflow + node_id — infer `run_id` from the newest evaluation in `workflows/<workflow>/evaluations/`.
- Nothing specific — ask, or infer from context (e.g. the node file they're currently editing).

## Steps

1. **Confirm the node has actually changed.** If the user hasn't edited the node since the failing run, replay will just reproduce the same failure. Check git status or the file's mtime.
2. **Run the replay.** `choola replay <workflow> <run_id> <node_id>` — the output is printed to stdout. By default a diff against the saved output is shown.
3. **Interpret the diff.** If the output changed: confirm the new shape matches the node's `@output-payload` docstring. If it didn't change: the edit didn't land, or didn't reach the failing codepath.
4. **Test edge cases.** If the user wants to probe the node with a different input: `choola replay <workflow> <run_id> <node_id> --payload '{"key": "value"}'`.

## Warnings to surface to the user

- **Side effects happen again.** Replay re-executes the node's code live. File writes, API calls, DB changes all fire. If this node writes to a paid API, you're paying again.
- **Credentials come from the current DB**, not the evaluation.

$ARGUMENTS
