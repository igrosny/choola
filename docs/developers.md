# Developing Choola

This guide is for engineers extending the Choola framework itself — adding new core nodes, new triggers, new engine features, or improving the editor. If your goal is to *use* Choola to build a workflow, read the main [README](../README.md) and the workflow-authoring guide at [`choola/CLAUDE.md`](../choola/CLAUDE.md) instead.

---

## 1. Prerequisites

| Requirement | Why |
|---|---|
| Python 3.10+ | Async / type-hint syntax used throughout `choola/` |
| Node.js 18+ and npm | Required to build the React editor (`frontend/`) |
| `pip install build twine` | Only needed when cutting a release |
| A Claude or Gemini API key | Optional — only required if you want to exercise the `LLM` / `LLML` nodes locally |

You do **not** need Docker, a database server, or any external service. The engine ships with SQLite (via the stdlib) and ChromaDB (pip-installed). Everything is local.

---

## 2. Clone, install, and build the UI

```bash
git clone https://github.com/igrosny/choola.git
cd choola

# Backend — editable install so changes to choola/ are picked up immediately
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -e .

# Frontend — build the React editor once so `choola start` can serve it
cd frontend
npm install
npm run build
cd ..
```

The `pip install -e .` step registers the `choola` CLI on your PATH and points it at your working tree, so editing `choola/server.py` or any node file under `choola/core/nodes/` takes effect on the next `choola start`.

---

## 3. The two-terminal dev loop

The engine and the editor are developed side by side. Run them in two terminals so you get Flask hot-reload on the backend and Vite HMR on the frontend.

```bash
# Terminal 1 — Flask backend (auto-reloads on .py changes)
choola start --debug

# Terminal 2 — Vite dev server (HMR on .jsx/.css changes)
cd frontend && npm run dev
```

Open `http://localhost:5173`. Vite proxies all `/api/*` calls to Flask on port `5000`, so the React UI and the Python engine talk to each other exactly as they will in production — only faster, with HMR.

If you only need to validate a backend change and don't care about the UI, `choola start` (without `--debug`) serves the pre-built UI from `choola/static/dist/` on `:5000` directly. No Vite needed.

---

## 4. Package layout

```
choola/                       # THE pip-installable package
├── __init__.py               # __version__ lives here — bump on every release
├── cli.py                    # `choola` CLI: init, start, create, list, run,
│                             #   replay, explain, nodes, credential, dream
├── server.py                 # Flask API + execution engine + serves static UI
├── database.py               # SQLite tables: globals, run_logs, credentials
├── evaluations.py            # Per-run JSON traces (one file per run_id)
├── mcp.py                    # MCP JSON-RPC dispatch + tool-shape generation
├── _dream.py                 # `choola dream` internals — XGBoost training loop
├── CLAUDE.md                 # Workflow-authoring guide (copied on `choola init`)
├── _claude/                  # Claude Code template — leading underscore prevents
│   │                         #   Claude Code from loading it in this repo
│   ├── settings.json         # Pre-approved permissions for end-user projects
│   └── commands/             # Slash commands shipped to end users
│       ├── node.md           # /node     — scaffold or edit a single node
│       ├── workflow.md       # /workflow — scaffold a full workflow
│       ├── debug.md          # /debug    — read evals, find the failing node
│       └── replay.md         # /replay   — re-run one node from a saved input
├── core/
│   ├── base_node.py          # BaseNode — every node inherits from this
│   ├── CLAUDE.md             # Core node API reference
│   └── nodes/                # Built-in core nodes
│       ├── trigger.py        # Abstract Trigger base
│       ├── manual_trigger.py
│       ├── webhook_trigger.py
│       ├── form_trigger.py
│       ├── llm.py            # Claude + Gemini, with token reporting
│       ├── llml.py           # Cached + locally-inferable LLM (XGBoost fallback)
│       ├── gmail.py          # Send mail via OAuth2
│       ├── http.py           # Generic HTTP requester
│       ├── db.py             # Per-workflow SQLite
│       └── vectordb.py       # Per-workflow ChromaDB
└── static/dist/              # Pre-built React UI — rebuilt before every release

frontend/                     # React + XyFlow editor source (Vite)
└── src/
workflows/                    # Dev/test workflows — gitignored
docs/                         # Long-form docs (this file lives here)
pyproject.toml                # Version + build config
```

The two directories most contributors touch are `choola/core/nodes/` (when adding or changing a built-in node) and `frontend/src/` (when changing the editor).

---

## 5. The three CLAUDE.md files

Choola's framework rules live in three CLAUDE.md files. Keep them aligned with the code in the same commit that changes the code — they are the agent-facing spec, and the whole framework's value depends on them being accurate.

| File | Audience | When to edit |
|---|---|---|
| `/CLAUDE.md` | Engineers working on the engine itself | Package layout changes, dev workflow changes, release process |
| `/choola/CLAUDE.md` | End-user agents authoring workflows (copied to user projects on `choola init`) | Node contract changes, new core nodes, new workflow rules |
| `/choola/core/CLAUDE.md` | End-user agents looking up a core node's API | Adding, removing, or changing a core node's fields, payload shape, or behavior |

---

## 6. The two `.claude/` directories

| Path | Scope | Notes |
|---|---|---|
| `/.claude/` (repo root) | Framework-dev only — your own Claude Code setup | Not shipped to end users. Edit freely. |
| `/choola/_claude/` | Template copied to end-user projects as `.claude/` on `choola init` | The leading underscore prevents Claude Code from picking it up *here*. When you change anything in this directory, bump the version and re-release so end users get the update. |

`choola init` skips the copy if `.claude/` already exists in the target directory, so end-user customizations are preserved across upgrades.

---

## 7. Adding or changing a core node

1. Edit or create the file in [`choola/core/nodes/`](../choola/core/nodes/).
2. The class **must** inherit from `BaseNode` and include the `@choola-node` docstring contract — this is what `grep` and the agent slash commands key off of.
3. Update [`choola/core/CLAUDE.md`](../choola/core/CLAUDE.md) with the node's full API reference.
4. Update [`choola/CLAUDE.md`](../choola/CLAUDE.md) if the node contract or workflow rules changed (e.g. you added a new helper on `BaseNode`).
5. If `choola/cli.py` lists node types manually in the `nodes` command, register the new module there.
6. Add a workflow under `workflows/` that exercises the node end-to-end. This is the closest thing the project has to integration tests today.

The full node contract — `@choola-node` docstring, fields list, `execute(payload, context)` signature, and the helpers available on `BaseNode` (`get_credential`, `db_query`, `vector_add`, `report_tokens`, etc.) — lives in [`choola/core/CLAUDE.md`](../choola/core/CLAUDE.md). Use that as the source of truth.

---

## 8. Editing the editor

The editor is a React + XyFlow app under [`frontend/src/`](../frontend/src/). The Flask backend serves it from `choola/static/dist/` in production, so any visual change has to be rebuilt and copied before it ships.

```bash
# Dev — instant feedback via Vite HMR
cd frontend && npm run dev

# Ship — rebuild and copy the bundle into the package
cd frontend
npm run build
rm -rf ../choola/static/dist
cp -r dist ../choola/static/dist
```

Commit *both* `frontend/src/` and `choola/static/dist/` in the same commit. Reviewers should be able to `pip install -e .` and immediately see the new UI without running `npm` themselves.

---

## 9. Cutting a release

Releases are PyPI uploads. There is no separate tag-and-CI pipeline — the version bump is the release.

```bash
# 1. Rebuild the UI so the bundle on PyPI matches the source
cd frontend && npm run build && rm -rf ../choola/static/dist && cp -r dist ../choola/static/dist && cd ..

# 2. Bump the version in BOTH places (must match exactly)
#    choola/__init__.py  ->  __version__ = "0.x.y"
#    pyproject.toml      ->  version      = "0.x.y"

# 3. Update CHANGELOG.md — move "Unreleased" entries under the new version + date

# 4. Build the wheel + sdist and upload
python -m build
python -m twine upload dist/*
```

If you forget to rebuild the frontend before publishing, end users will see the *old* UI even after upgrading. There is no runtime check for bundle freshness — be disciplined about step 1.

---

## 10. Credentials

Credentials are stored encrypted in the SQLite `credentials` table created in the user's CWD as `choola.db`. Nodes never see plaintext secrets except via `await self.get_credential(name)` at execution time.

| Method | Path | Description |
|---|---|---|
| GET | `/api/credentials` | List all credentials with values masked |
| POST | `/api/credentials` | Create or update: `{ name, provider, value }` |
| DELETE | `/api/credentials/<name>` | Delete a credential |

For OAuth2 providers (Gmail, Google), use the dedicated flow:

| Method | Path | Description |
|---|---|---|
| POST | `/api/oauth2/gmail/start` | Initiate the OAuth2 flow — returns a redirect URL |
| GET | `/api/oauth2/gmail/callback` | Callback that exchanges the code for tokens and stores them |

The `choola credential <name>` CLI command provides an interactive prompt for both static keys and OAuth2 flows, so contributors don't have to hit the HTTP API by hand during development.

---

## 11. HTTP API reference

The full set of endpoints exposed by `choola/server.py`:

### Nodes

| Method | Path | Description |
|---|---|---|
| GET | `/api/nodes` | List all registered node types |
| GET | `/api/nodes/<node_type>/fields` | Field definitions for a node type |
| GET | `/api/nodes/<node_type>/source` | Read a node's source code |
| PUT | `/api/nodes/<node_type>/source` | Update a node's source code |

### Workflows

| Method | Path | Description |
|---|---|---|
| GET | `/api/workflows` | List all workflows |
| POST | `/api/workflows` | Create a new workflow |
| GET | `/api/workflows/<name>/topology` | Get workflow topology (canvas layout + per-instance config) |
| PUT | `/api/workflows/<name>/topology` | Update workflow topology |
| POST | `/api/workflows/<name>/run` | Execute a workflow |
| GET | `/api/workflows/<name>/stream/<run_id>` | SSE stream for live run status |
| POST | `/api/workflows/<name>/refresh` | Re-discover nodes from disk |
| POST | `/api/workflows/<name>/chat` | Chat with Claude about the workflow (SSE) |
| GET | `/api/workflows/<name>/trigger-info` | Get trigger type and config |

### Evaluations

| Method | Path | Description |
|---|---|---|
| GET | `/api/workflows/<name>/evaluations` | Paginated run summaries (status, duration, tokens) |
| GET | `/api/workflows/<name>/evaluations/<run_id>` | Full per-node JSON for a single run |

### VectorDB

| Method | Path | Description |
|---|---|---|
| GET | `/api/workflows/<name>/vectordb/schema` | List collections and their schema |
| POST | `/api/workflows/<name>/vectordb/query` | Run a similarity search against a collection |

### Credentials & OAuth2

| Method | Path | Description |
|---|---|---|
| GET | `/api/credentials` | List all (values masked) |
| POST | `/api/credentials` | Create or update a credential |
| DELETE | `/api/credentials/<name>` | Delete a credential |
| POST | `/api/oauth2/gmail/start` | Begin the Gmail OAuth2 flow |
| GET | `/api/oauth2/gmail/callback` | OAuth2 callback handler |

### MCP

| Method | Path | Description |
|---|---|---|
| POST | `/mcp` | JSON-RPC 2.0 endpoint that exposes every workflow as a callable tool. Optional bearer-token auth via the `mcp_token` global; empty/unset means open. See [`choola/mcp.py`](../choola/mcp.py) for the implemented method set. |

---

## 12. Where to ask questions

- File an issue at [github.com/igrosny/choola/issues](https://github.com/igrosny/choola/issues) for bugs, design questions, or RFC-style proposals.
- For workflow-authoring questions (as opposed to engine questions), point people at the [README](../README.md) and [`choola/CLAUDE.md`](../choola/CLAUDE.md) — those are the user-facing surfaces.
