# Choola — Development Guide

## The two roles this repo plays

When you work in this repo you are always doing one of two things:

| Role | What you edit | Where data lives |
|---|---|---|
| **Developing Choola itself** (the engine) | `choola/` package files | `workflows/` + `choola.db` at repo root |
| **Using Choola** as an end-user | `workflows/` only | same folder you ran `choola init` in |

Everything below is about the first role — developing the engine.

---

## Starting for development (two terminals)

Since you'll mostly be editing the frontend, use both servers together:

**Terminal 1 — Flask backend:**
```bash
choola start --debug
# Runs at http://localhost:5000
```

**Terminal 2 — Vite frontend:**
```bash
cd frontend
npm install        # first time only
npm run dev
# Runs at http://localhost:5173
```

**Open `http://localhost:5173` in your browser.** Vite proxies all API, webhook, and dev-route calls to Flask at port 5000, so everything works. You get instant hot-reload on every save in `frontend/src/`.

---

## Committing frontend changes

When your UI changes are ready, rebuild and commit the static bundle:

```bash
cd frontend && npm run build && cp -r dist ../choola/static/
```

Then commit both `frontend/src/` changes and `choola/static/`. The static bundle is in `.gitignore` by default — remove that line if you want to commit it, or keep it out and always rebuild on deploy.

---

## Which files are actually used?

The repo root has been cleaned up. Here is the authoritative source for everything:

```
choola/                 ← THE package. This is what pip installs.
│
├── cli.py              ← `choola` command lives here
├── server.py           ← Flask app + execution engine
├── database.py         ← SQLite (choola.db in your cwd)
│
├── core/
│   ├── base_node.py    ← BaseNode — the class every node inherits from
│   └── nodes/
│       ├── form_trigger.py
│       ├── webhook_trigger.py
│       └── llm.py
│
├── static/             ← pre-built React UI (not in git, rebuilt before release)
└── CLAUDE.md           ← spec bundled with the package
```

**Old files that no longer exist:** `server.py`, `cli.py`, `database.py`, `core/` at the repo root have been deleted. They were dead code.

---

## Which CLAUDE.md does the server use?

`choola/CLAUDE.md` — the one inside the package.

The server reads it at startup to build the AI chat assistant's system prompt. It is also the file that gets copied into a user's project when they run `choola init`.

The root-level `CLAUDE.md` is what Claude Code reads when you work in this repo (it is in `.claude`'s project root scan path). **Both files should always say the same thing.** When you update one, update the other. The easiest way:

```bash
cp choola/CLAUDE.md CLAUDE.md
# or
cp CLAUDE.md choola/CLAUDE.md
```

---

## Which core nodes are active?

`choola/core/nodes/` — these three:

| File | Node type string | Purpose |
|---|---|---|
| `form_trigger.py` | `core.nodes.form_trigger.FormTrigger` | Serves an HTML form, triggers workflow on submit |
| `webhook_trigger.py` | `core.nodes.webhook_trigger.WebhookTrigger` | Triggers workflow on HTTP request |
| `llm.py` | `core.nodes.llm.LLM` | Calls Claude or Gemini |

All workflow nodes inherit from `choola.core.base_node.BaseNode`.

---

## Folder reference

```
choola/             ← edit this to change the engine
  cli.py
  server.py
  database.py
  core/             ← edit this to change or add core nodes
  static/           ← do NOT edit directly; rebuild from frontend/

frontend/           ← edit this to change the UI
  src/              ← React source

workflows/          ← dev/example workflows (also what the server loads during dev)

CLAUDE.md           ← keep in sync with choola/CLAUDE.md
pyproject.toml      ← bump version here before a release
```

---

## Making a release

```bash
# 1. Rebuild the UI
cd frontend && npm run build && cp -r dist ../choola/static/ && cd ..

# 2. Bump the version in both places
#    - choola/__init__.py  →  __version__ = "0.x.y"
#    - pyproject.toml      →  version = "0.x.y"

# 3. Build
python -m build

# 4. Publish
twine upload dist/*

pip install twine
python -m twine upload dist/*
```

---

## Running on a server

```bash
pip install choola
mkdir ~/my-project && cd ~/my-project
choola init
choola start --host 0.0.0.0 --port 5000
```

To keep it running after SSH disconnect, use tmux:

```bash
tmux new -s choola
choola start --host 0.0.0.0
# Ctrl+B then D to detach
```

Or create a systemd service (see below for the unit file template):

```ini
[Unit]
Description=Choola Workflow Server
After=network.target

[Service]
User=your-user
WorkingDirectory=/home/your-user/my-project
ExecStart=/home/your-user/.local/bin/choola start --host 0.0.0.0 --port 5000
Restart=always
Environment=ANTHROPIC_API_KEY=sk-ant-...

[Install]
WantedBy=multi-user.target
```
