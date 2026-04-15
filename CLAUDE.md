# Choola — Development Environment

This is the development repo for the Choola workflow engine. The `choola/` directory IS the pip package. The `workflows/` directory holds dev/test workflows.

## Two Roles, Two Scopes

| You are... | You edit... | CLAUDE.md that applies |
|---|---|---|
| Developing the engine | `choola/`, `frontend/` | This file (root) |
| Building a workflow | `workflows/<name>/` only | `choola/CLAUDE.md` (the one copied to user projects) |

If your task is purely about creating or editing a workflow, follow `choola/CLAUDE.md` — it has the node contract and workflow rules. This file is about the engine itself.

## Package Layout

```
choola/                 <- THE pip package
  __init__.py           <- __version__ lives here
  cli.py                <- `choola` CLI entry point
  server.py             <- Flask app + execution engine
  database.py           <- SQLite (choola.db in user's cwd)
  evaluations.py        <- Evaluation storage (one JSON per run)
  CLAUDE.md             <- Workflow authoring guide (copied on `choola init`)
  core/
    base_node.py        <- BaseNode — every node inherits from this
    CLAUDE.md           <- Core node reference
    nodes/
      form_trigger.py
      webhook_trigger.py
      llm.py
  static/dist/          <- Pre-built React UI (rebuilt before release)

frontend/               <- React source (Vite)
  src/
workflows/              <- Dev/test workflows (gitignored)
  <name>/
    nodes/              <- Workflow node files
    files/              <- Binary/generated files (auto-created)
    evaluations/        <- Run evaluations (auto-generated, one JSON per run)
pyproject.toml          <- Version + build config
```

## Dev Workflow (Two Terminals)

**Terminal 1 — Flask backend:**
```bash
choola start --debug
```

**Terminal 2 — Vite frontend:**
```bash
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`. Vite proxies API calls to Flask at 5000.

## The Three CLAUDE.md Files

| File | Purpose | When to edit |
|---|---|---|
| `/CLAUDE.md` (this file) | Dev environment guide for agents working on the engine | When you change the package structure, dev workflow, or release process |
| `/choola/CLAUDE.md` | Workflow authoring guide — copied to user projects on `choola init` | When you change the node contract, add core nodes, or change workflow rules |
| `/choola/core/CLAUDE.md` | Core node reference — documents every core node's API | When you add, remove, or change a core node's fields/behavior |

## Adding or Changing a Core Node

1. Edit or create the node file in `choola/core/nodes/`
2. It MUST inherit from `BaseNode` and include the `@choola-node` docstring
3. Update `choola/core/CLAUDE.md` with the node's full API reference
4. Update `choola/CLAUDE.md` if the node contract or workflow rules changed
5. If the `choola nodes` CLI command lists nodes manually, update `choola/cli.py`

## Committing Frontend Changes

```bash
cd frontend && npm run build && cp -r dist ../choola/static/dist
```

Commit both `frontend/src/` and `choola/static/dist/`.

## Making a Release

```bash
# 1. Rebuild the UI
cd frontend && npm run build && cp -r dist ../choola/static/dist && cd ..

# 2. Bump version in both places:
#    choola/__init__.py  ->  __version__ = "0.x.y"
#    pyproject.toml      ->  version = "0.x.y"

# 3. Build + publish
python -m build
python -m twine upload dist/*
```

## Credentials

Stored in SQLite (`credentials` table). Nodes access them via `await self.get_credential(name)`.

- `GET /api/credentials` — list (values masked)
- `POST /api/credentials` — create/update: `{ name, provider, value }`
- `DELETE /api/credentials/<name>` — delete
