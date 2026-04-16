# Copyright 2026 Ivan Grosny
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
server.py — Flask application providing:

  - Dynamic module loading of all BaseNode subclasses from workflows/.
  - REST API for node metadata, workflow listing, topology CRUD.
  - Workflow execution engine with topological sorting.
  - Server-Sent Events (SSE) for live debugging / status streaming.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import queue
import re
import sys
import threading
import traceback
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
from flask import Flask, Response, jsonify, request

from choola.core.base_node import BaseNode
from choola.evaluations import (
    build_evaluation,
    capture_payload,
    make_node_eval,
    save_evaluation,
)
from choola.database import (
    DB_PATH,
    delete_credential,
    get_credential_async,
    get_global_async,
    init_db,
    insert_run_log,
    list_credentials,
    set_global_async,
    upsert_credential,
)

# ------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------
# ROOT = package directory (where this file lives), used for core nodes + static assets.
ROOT = Path(__file__).resolve().parent
# CWD = user's project directory, used for workflows/ and choola.db.
CWD = Path(os.getcwd())
WORKFLOWS_DIR = CWD / "workflows"

# Static files are bundled inside the package at choola/static/
_STATIC_DIR = ROOT / "static"

app = Flask(__name__, static_folder=str(_STATIC_DIR), static_url_path="/")

# Global registries populated at startup
node_registry: dict[str, type[BaseNode]] = {}        # "module.ClassName" -> class
workflow_nodes: dict[str, list[type[BaseNode]]] = {}  # "workflow_name" -> [classes]

# SSE event bus: run_id -> Queue
sse_buses: dict[str, queue.Queue] = {}


# ------------------------------------------------------------------
# Dynamic module loader
# ------------------------------------------------------------------
def _import_nodes_from(directory: Path, *, relative_root: Path, workflow_name: str | None = None) -> None:
    """Import all BaseNode subclasses from .py files under *directory*/nodes/."""
    for py_file in directory.rglob("nodes/*.py"):
        if py_file.name.startswith("_"):
            continue

        relative = py_file.relative_to(relative_root)
        module_name = str(relative.with_suffix("")).replace("/", ".").replace("\\", ".")

        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        wf_name = workflow_name
        if wf_name is None and directory == WORKFLOWS_DIR:
            wf_name = py_file.relative_to(WORKFLOWS_DIR).parts[0]

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseNode)
                and obj is not BaseNode
                and obj.__module__ == module_name
            ):
                fq_name = f"{module_name}.{attr_name}"
                node_registry[fq_name] = obj
                if wf_name:
                    workflow_nodes.setdefault(wf_name, []).append(obj)


def discover_nodes() -> None:
    """Walk core/nodes/ and workflows/**/nodes/*.py, import modules, register BaseNode subclasses."""
    node_registry.clear()
    workflow_nodes.clear()

    # Core nodes (available to all workflows) — live inside the package
    core_dir = ROOT / "core"
    _import_nodes_from(core_dir, relative_root=ROOT)

    # Workflow-specific nodes — live in the user's project directory
    if WORKFLOWS_DIR.exists():
        _import_nodes_from(WORKFLOWS_DIR, relative_root=CWD)


def build_workflow(workflow_name: str) -> dict:
    """Build the workflow DAG from node class attributes (node_id, next_nodes).

    Returns a dict with 'nodes' and 'edges' suitable for topological_sort.
    """
    classes = workflow_nodes.get(workflow_name, [])
    by_id: dict[str, tuple[str, type[BaseNode]]] = {}
    for cls in classes:
        nid = cls.node_id
        if not nid:
            continue
        # Find fq_name from node_registry
        fq_name = next((fq for fq, c in node_registry.items() if c is cls), "")
        if nid in by_id:
            other_fq = by_id[nid][0]
            raise ValueError(f"Duplicate node_id '{nid}': {fq_name} and {other_fq}")
        by_id[nid] = (fq_name, cls)

    if not by_id:
        raise ValueError(f"No nodes with a node_id found in workflow '{workflow_name}'")

    nodes = [{"id": nid, "type": fq, "cls": cls} for nid, (fq, cls) in by_id.items()]
    edges = []
    for nid, (fq, cls) in by_id.items():
        for target in cls.next_nodes:
            if target not in by_id:
                raise ValueError(
                    f"Node '{nid}' references next_node '{target}' which doesn't exist"
                )
            edges.append({"source": nid, "target": target})

    return {"nodes": nodes, "edges": edges}


# ------------------------------------------------------------------
# Topology helpers (UI-only — stores canvas positions and layout)
# ------------------------------------------------------------------
def load_topology(workflow_name: str) -> dict:
    topo_path = WORKFLOWS_DIR / workflow_name / "topology.json"
    if not topo_path.exists():
        return {"nodes": [], "edges": [], "status": "draft"}
    topo = json.loads(topo_path.read_text())
    if "status" not in topo:
        topo["status"] = "draft"
    return topo


def save_topology(workflow_name: str, data: dict) -> None:
    topo_path = WORKFLOWS_DIR / workflow_name / "topology.json"
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text(json.dumps(data, indent=2))


def topological_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Return node IDs in execution order (Kahn's algorithm)."""
    id_set = {n["id"] for n in nodes}
    in_degree: dict[str, int] = {nid: 0 for nid in id_set}
    adjacency: dict[str, list[str]] = defaultdict(list)

    for edge in edges:
        src, tgt = edge["source"], edge["target"]
        if src in id_set and tgt in id_set:
            adjacency[src].append(tgt)
            in_degree[tgt] += 1

    q: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    order: list[str] = []

    while q:
        nid = q.popleft()
        order.append(nid)
        for neighbour in adjacency[nid]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                q.append(neighbour)

    if len(order) != len(id_set):
        raise ValueError("Cycle detected in workflow topology")

    return order


# ------------------------------------------------------------------
# Execution engine
# ------------------------------------------------------------------
def _emit(run_id: str, event: str, data: dict) -> None:
    """Push an SSE event onto the bus for the given run."""
    bus = sse_buses.get(run_id)
    if bus:
        bus.put(f"event: {event}\ndata: {json.dumps(data)}\n\n")


def run_workflow(workflow_name: str, payload: dict[str, Any], run_id: str | None = None) -> dict:
    """Execute a workflow synchronously (uses asyncio.run internally)."""
    run_id = run_id or uuid.uuid4().hex[:12]
    return asyncio.run(_run_workflow_async(workflow_name, payload, run_id))


async def _run_workflow_async(workflow_name: str, payload: dict[str, Any], run_id: str) -> dict:
    wf = build_workflow(workflow_name)
    sorted_ids = topological_sort(wf["nodes"], wf["edges"])
    node_lookup = {n["id"]: n for n in wf["nodes"]}

    context: dict[str, Any] = {
        "workflow": workflow_name,
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    results: dict[str, Any] = {}
    initial_payload = capture_payload(payload)
    node_evals: list[dict] = []

    for node_id in sorted_ids:
        node_entry = node_lookup[node_id]
        node_type = node_entry["type"]
        cls = node_entry["cls"]

        instance = cls()
        instance._db_get_global = get_global_async
        instance._db_set_global = set_global_async
        instance._db_get_credential = get_credential_async

        now = datetime.now(timezone.utc).isoformat()
        payload_before = capture_payload(payload)
        _emit(run_id, "node_status", {"node_id": node_id, "status": "RUNNING", "payload": payload})
        insert_run_log(run_id, workflow_name, node_id, node_type, "RUNNING", payload_in=payload_before, started_at=now)

        try:
            payload = await instance.execute(payload, context)
            finished = datetime.now(timezone.utc).isoformat()
            _emit(run_id, "node_status", {"node_id": node_id, "status": "COMPLETED", "payload": payload})
            insert_run_log(run_id, workflow_name, node_id, node_type, "COMPLETED",
                           payload_in=payload_before, payload_out=payload, started_at=now, finished_at=finished)
            node_evals.append(make_node_eval(node_id, node_type, "COMPLETED", now, finished, payload_before, capture_payload(payload)))
            results[node_id] = payload
        except Exception as exc:
            finished = datetime.now(timezone.utc).isoformat()
            tb = traceback.format_exc()
            _emit(run_id, "node_status", {"node_id": node_id, "status": "ERROR", "error": str(exc)})
            insert_run_log(run_id, workflow_name, node_id, node_type, "ERROR",
                           payload_in=payload_before, error=tb, started_at=now, finished_at=finished)
            node_evals.append(make_node_eval(node_id, node_type, "ERROR", now, finished, payload_before, error=tb))
            evaluation = build_evaluation(run_id, workflow_name, context["started_at"], initial_payload, node_evals, "ERROR", error=tb)
            save_evaluation(workflow_name, evaluation)
            _emit(run_id, "run_complete", {"status": "ERROR", "error": str(exc)})
            raise

    evaluation = build_evaluation(run_id, workflow_name, context["started_at"], initial_payload, node_evals, "COMPLETED", payload)
    save_evaluation(workflow_name, evaluation)
    _emit(run_id, "run_complete", {"status": "COMPLETED", "payload": payload})
    return {"status": "COMPLETED", "payload": payload, "run_id": run_id}


# ------------------------------------------------------------------
# REST API
# ------------------------------------------------------------------
@app.route("/api/nodes")
def api_nodes():
    """Return UI metadata for all registered node classes."""
    return jsonify([cls.ui_metadata() for cls in node_registry.values()])


@app.route("/api/workflows")
def api_workflows():
    """List all discovered workflow folders."""
    if not WORKFLOWS_DIR.exists():
        return jsonify([])
    result = []
    for d in sorted(WORKFLOWS_DIR.iterdir()):
        if not d.is_dir():
            continue
        nodes_dir = d / "nodes"
        node_count = 0
        if nodes_dir.exists():
            node_count = sum(1 for f in nodes_dir.glob("*.py") if not f.name.startswith("_"))
        result.append({
            "name": d.name,
            "nodes": node_count,
        })
    return jsonify(result)


@app.route("/api/workflows", methods=["POST"])
def api_create_workflow():
    """Create a new empty workflow folder with topology.json and nodes/ dir."""
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Workflow name is required"}), 400
    if not all(c.isalnum() or c in ("_", "-") for c in name):
        return jsonify({"error": "Name must be alphanumeric (underscores/hyphens allowed)"}), 400

    workflow_dir = WORKFLOWS_DIR / name
    if workflow_dir.exists():
        return jsonify({"error": f"Workflow '{name}' already exists"}), 409

    nodes_dir = workflow_dir / "nodes"
    nodes_dir.mkdir(parents=True)
    (nodes_dir / "__init__.py").write_text("")

    return jsonify({"ok": True, "name": name}), 201


@app.route("/api/workflows/<name>/topology", methods=["GET", "PUT"])
def api_topology(name: str):
    """UI-only: stores canvas positions and layout. The real DAG comes from node classes."""
    if request.method == "GET":
        # Merge node-declared DAG with UI positions from topology.json
        ui_data = load_topology(name)
        try:
            wf = build_workflow(name)
            positions = {n.get("id"): n.get("position", {}) for n in ui_data.get("nodes", [])}
            nodes = []
            for node in wf["nodes"]:
                nid = node["id"]
                cls = node["cls"]
                nodes.append({
                    "id": nid,
                    "type": node["type"],
                    "position": positions.get(nid, {"x": 250, "y": 250}),
                    "data": {"label": cls.name, "config": {}},
                })
            return jsonify({"nodes": nodes, "edges": wf["edges"]})
        except ValueError:
            return jsonify({"nodes": [], "edges": []})
    # PUT — save UI positions only
    data = request.get_json(force=True)
    save_topology(name, data)
    return jsonify({"ok": True})


@app.route("/api/workflows/<name>/refresh", methods=["POST"])
def api_refresh_workflow(name: str):
    """Hard refresh: re-discover nodes from Python files."""
    workflow_dir = WORKFLOWS_DIR / name
    if not workflow_dir.exists():
        return jsonify({"error": f"Workflow '{name}' not found"}), 404

    discover_nodes()
    register_webhooks()

    try:
        wf = build_workflow(name)
        return jsonify({"nodes": [{"id": n["id"], "type": n["type"]} for n in wf["nodes"]], "edges": wf["edges"]})
    except ValueError as e:
        return jsonify({"nodes": [], "edges": [], "warning": str(e)})


@app.route("/api/nodes/<path:node_type>/source", methods=["GET", "PUT"])
def api_node_source(node_type: str):
    """Read or update the source code of a node file."""
    parts = node_type.rsplit(".", 1)
    if len(parts) != 2:
        return jsonify({"error": "Invalid node type"}), 400
    module_path = parts[0]

    # Core nodes live inside the package; workflow nodes live in the user's CWD.
    if module_path.startswith("core."):
        file_path = ROOT / module_path.replace(".", "/")
        display_root = ROOT
    else:
        file_path = CWD / module_path.replace(".", "/")
        display_root = CWD
    file_path = file_path.with_suffix(".py")

    if not file_path.exists():
        return jsonify({"error": f"Source file not found: {file_path}"}), 404

    if request.method == "GET":
        return jsonify({"source": file_path.read_text(), "path": str(file_path.relative_to(display_root))})

    # PUT — save updated source
    data = request.get_json(force=True)
    source = data.get("source")
    if source is None:
        return jsonify({"error": "source field is required"}), 400
    file_path.write_text(source)
    discover_nodes()
    return jsonify({"ok": True, "path": str(file_path.relative_to(display_root))})


@app.route("/api/nodes/<path:node_type>/fields")
def api_node_fields(node_type: str):
    """Return the fields metadata for a node type."""
    cls = node_registry.get(node_type)
    if cls is None:
        return jsonify({"error": f"Unknown node type: {node_type}"}), 404
    return jsonify({"fields": cls.fields})


@app.route("/api/workflows/<name>/run", methods=["POST"])
def api_run_workflow(name: str):
    """Execute a workflow and return the result."""
    body = request.get_json(force=True) if request.data else {}
    payload = body.get("payload", {})
    run_id = body.get("run_id") or uuid.uuid4().hex[:12]

    sse_buses.setdefault(run_id, queue.Queue())

    try:
        result = run_workflow(name, payload, run_id=run_id)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"status": "ERROR", "error": str(exc), "run_id": run_id}), 500


@app.route("/api/workflows/<name>/stream/<run_id>")
def api_stream(name: str, run_id: str):
    """SSE endpoint — clients connect here BEFORE triggering a run."""
    bus = sse_buses.setdefault(run_id, queue.Queue())

    def generate():
        while True:
            try:
                msg = bus.get(timeout=30)
                yield msg
                if '"run_complete"' in msg or "run_complete" in msg:
                    break
            except queue.Empty:
                yield ": keepalive\n\n"

    return Response(generate(), mimetype="text/event-stream")


# ------------------------------------------------------------------
# Credentials API
# ------------------------------------------------------------------
@app.route("/api/credentials")
def api_list_credentials():
    creds = list_credentials()
    for c in creds:
        c.pop("value", None)
    return jsonify(creds)


@app.route("/api/credentials", methods=["POST"])
def api_upsert_credential():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    provider = data.get("provider", "").strip()
    value = data.get("value", "").strip()
    if not name or not provider or not value:
        return jsonify({"error": "name, provider, and value are required"}), 400
    if not all(c.isalnum() or c in ("_", "-") for c in name):
        return jsonify({"error": "name must be alphanumeric (underscores/hyphens allowed)"}), 400
    upsert_credential(name, provider, value)
    return jsonify({"ok": True, "name": name}), 201


@app.route("/api/credentials/<name>", methods=["DELETE"])
def api_delete_credential(name: str):
    if delete_credential(name):
        return jsonify({"ok": True})
    return jsonify({"error": "Credential not found"}), 404


# ------------------------------------------------------------------
# Google OAuth2 flow
# ------------------------------------------------------------------
_oauth2_pending: dict[str, dict] = {}

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_SCOPES = "https://www.googleapis.com/auth/drive.file"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


@app.route("/api/oauth2/google/start", methods=["POST"])
def api_oauth2_google_start():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    client_id = data.get("client_id", "").strip()
    client_secret = data.get("client_secret", "").strip()

    if not name or not client_id or not client_secret:
        return jsonify({"error": "name, client_id, and client_secret are required"}), 400
    if not all(c.isalnum() or c in ("_", "-") for c in name):
        return jsonify({"error": "name must be alphanumeric (underscores/hyphens allowed)"}), 400

    state = uuid.uuid4().hex
    _oauth2_pending[state] = {
        "name": name,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    callback_url = request.host_url.rstrip("/") + "/api/oauth2/google/callback"
    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": GOOGLE_DRIVE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    from urllib.parse import urlencode
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return jsonify({"auth_url": auth_url})


@app.route("/api/oauth2/google/callback")
def api_oauth2_google_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return f"<h2>OAuth2 Error</h2><p>{error}</p>", 400

    if not code or not state or state not in _oauth2_pending:
        return "<h2>Invalid OAuth2 callback</h2><p>Missing or expired state.</p>", 400

    pending = _oauth2_pending.pop(state)
    callback_url = request.host_url.rstrip("/") + "/api/oauth2/google/callback"

    import requests as http_requests
    token_resp = http_requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": pending["client_id"],
        "client_secret": pending["client_secret"],
        "redirect_uri": callback_url,
        "grant_type": "authorization_code",
    })

    if token_resp.status_code != 200:
        return f"<h2>Token exchange failed</h2><pre>{token_resp.text}</pre>", 400

    tokens = token_resp.json()
    credential_value = json.dumps({
        "client_id": pending["client_id"],
        "client_secret": pending["client_secret"],
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_uri": GOOGLE_TOKEN_URL,
    })

    upsert_credential(pending["name"], "google_oauth2", credential_value)

    return """
    <html><body style="background:#1a1a2e;color:#eee;font-family:sans-serif;display:flex;
    align-items:center;justify-content:center;height:100vh;margin:0">
    <div style="text-align:center">
      <h2 style="color:#4ade80">Connected to Google</h2>
      <p>Credential saved. You can close this tab.</p>
      <script>if(window.opener){window.opener.postMessage('oauth2_done','*')}</script>
    </div></body></html>
    """


# ------------------------------------------------------------------
# Gmail OAuth2
# ------------------------------------------------------------------

@app.route("/api/oauth2/gmail/start", methods=["POST"])
def api_oauth2_gmail_start():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    client_id = data.get("client_id", "").strip()
    client_secret = data.get("client_secret", "").strip()

    if not name or not client_id or not client_secret:
        return jsonify({"error": "name, client_id, and client_secret are required"}), 400
    if not all(c.isalnum() or c in ("_", "-") for c in name):
        return jsonify({"error": "name must be alphanumeric (underscores/hyphens allowed)"}), 400

    state = uuid.uuid4().hex
    _oauth2_pending[state] = {
        "name": name,
        "client_id": client_id,
        "client_secret": client_secret,
        "provider": "gmail",
    }

    callback_url = request.host_url.rstrip("/") + "/api/oauth2/gmail/callback"
    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": GMAIL_SEND_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    from urllib.parse import urlencode
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return jsonify({"auth_url": auth_url})


@app.route("/api/oauth2/gmail/callback")
def api_oauth2_gmail_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return f"<h2>OAuth2 Error</h2><p>{error}</p>", 400

    if not code or not state or state not in _oauth2_pending:
        return "<h2>Invalid OAuth2 callback</h2><p>Missing or expired state.</p>", 400

    pending = _oauth2_pending.pop(state)
    callback_url = request.host_url.rstrip("/") + "/api/oauth2/gmail/callback"

    import requests as http_requests
    token_resp = http_requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": pending["client_id"],
        "client_secret": pending["client_secret"],
        "redirect_uri": callback_url,
        "grant_type": "authorization_code",
    })

    if token_resp.status_code != 200:
        return f"<h2>Token exchange failed</h2><pre>{token_resp.text}</pre>", 400

    tokens = token_resp.json()
    credential_value = json.dumps({
        "client_id": pending["client_id"],
        "client_secret": pending["client_secret"],
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_uri": GOOGLE_TOKEN_URL,
    })

    upsert_credential(pending["name"], "gmail", credential_value)

    return """
    <html><body style="background:#1a1a2e;color:#eee;font-family:sans-serif;display:flex;
    align-items:center;justify-content:center;height:100vh;margin:0">
    <div style="text-align:center">
      <h2 style="color:#4ade80">Connected to Gmail</h2>
      <p>Credential saved. You can close this tab.</p>
      <script>if(window.opener){window.opener.postMessage('oauth2_done','*')}</script>
    </div></body></html>
    """


# ------------------------------------------------------------------
# Chat with Claude — per-workflow AI assistant
# ------------------------------------------------------------------
CHAT_TOOLS = [
    {
        "name": "create_node",
        "description": "Create a new node Python file in the workflow's nodes/ directory. Always generate the full @choola-node docstring and class.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Python filename, e.g. fetch_api.py (snake_case, no path)",
                },
                "source": {
                    "type": "string",
                    "description": "Complete Python source code for the node file",
                },
            },
            "required": ["filename", "source"],
        },
    },
    {
        "name": "edit_node",
        "description": "Overwrite an existing node file with new source code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Existing Python filename to overwrite",
                },
                "source": {
                    "type": "string",
                    "description": "New complete Python source code",
                },
            },
            "required": ["filename", "source"],
        },
    },
]

# Read project specification — prefer the one in the user's project, fall back to the bundled copy.
_CLAUDE_MD = ""
_claude_md_path = CWD / "CLAUDE.md"
if not _claude_md_path.exists():
    _claude_md_path = ROOT / "CLAUDE.md"
if _claude_md_path.exists():
    _CLAUDE_MD = _claude_md_path.read_text()

# Read base_node.py from the package
_BASE_NODE_SOURCE = (ROOT / "core" / "base_node.py").read_text()

# Read an example node from the user's project (if any)
_EXAMPLE_NODE = ""
if WORKFLOWS_DIR.exists():
    for _example in WORKFLOWS_DIR.rglob("nodes/*.py"):
        if not _example.name.startswith("_"):
            _EXAMPLE_NODE = _example.read_text()
            break


def _gather_core_nodes() -> str:
    """Collect @choola-node docstrings from all core/nodes/*.py files."""
    core_nodes_dir = ROOT / "core" / "nodes"
    if not core_nodes_dir.exists():
        return "(no core nodes)"
    parts = []
    for py_file in sorted(core_nodes_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        source = py_file.read_text()
        parts.append(f"--- {py_file.name} ---\n{source}")
    return "\n\n".join(parts) if parts else "(no core nodes)"


def _build_chat_system(workflow_name: str) -> list[dict]:
    """Build the system prompt as content blocks with prompt caching."""
    workflow_dir = WORKFLOWS_DIR / workflow_name

    node_sources = {}
    nodes_dir = workflow_dir / "nodes"
    if nodes_dir.exists():
        for py_file in sorted(nodes_dir.glob("*.py")):
            if not py_file.name.startswith("_"):
                node_sources[py_file.name] = py_file.read_text()

    node_listing = ""
    if node_sources:
        parts = []
        for fname, src in node_sources.items():
            parts.append(f"--- {fname} ---\n{src}")
        node_listing = "\n\n".join(parts)
    else:
        node_listing = "(no nodes yet)"

    core_nodes_listing = _gather_core_nodes()

    registered_nodes_info = []
    for fq_name, cls in node_registry.items():
        registered_nodes_info.append(
            f"  - {cls.name} ({fq_name}): {cls.description} [category: {cls.category}]"
        )
    registered_listing = "\n".join(registered_nodes_info) if registered_nodes_info else "  (none)"

    static_block = f"""You are an AI assistant that helps users build workflow nodes for Choola, a Python workflow engine.

## Project Specification (CLAUDE.md)
{_CLAUDE_MD}

## Core nodes (available to all workflows)
{core_nodes_listing}

## BaseNode contract (core/base_node.py)
{_BASE_NODE_SOURCE}

## Example node file
{_EXAMPLE_NODE}

## Rules
- Every node file MUST start with the @choola-node docstring block.
- Every node MUST inherit from `choola.core.base_node.BaseNode`.
- Nodes must be self-contained — no cross-node imports.
- The `execute` method is async and receives (payload: dict, context: dict) -> dict.
- Declare class attributes: name, category, description, fields.
- Valid categories: input, processing, routing, output, general.
- Use `create_node` to make new node files. Use `edit_node` to modify existing node files.
- Every node must declare a `node_id` class attribute (unique within the workflow).
- Use `next_nodes` class attribute (list of node_id strings) to define the DAG edges.
- No topology.json needed — the DAG is built from node class attributes.
- Keep nodes simple and focused on a single task.
- Be concise in your responses."""

    try:
        wf = build_workflow(workflow_name)
        wf_summary = json.dumps(
            {"nodes": [{"id": n["id"], "type": n["type"]} for n in wf["nodes"]], "edges": wf["edges"]},
            indent=2,
        )
    except ValueError:
        wf_summary = "(no nodes with node_id found yet)"

    dynamic_block = f"""## Current workflow: {workflow_name}

## Current DAG (derived from node classes)
{wf_summary}

## All registered node types
{registered_listing}

## Existing nodes in this workflow
{node_listing}"""

    return [
        {
            "type": "text",
            "text": static_block,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": dynamic_block,
        },
    ]


def _handle_tool_call(workflow_name: str, tool_name: str, tool_input: dict) -> dict:
    """Execute a tool call and return the result."""
    workflow_dir = WORKFLOWS_DIR / workflow_name
    nodes_dir = workflow_dir / "nodes"

    if tool_name == "create_node":
        filename = tool_input["filename"]
        source = tool_input["source"]
        if not re.match(r"^[a-z][a-z0-9_]*\.py$", filename):
            return {"error": f"Invalid filename: {filename}. Use snake_case.py"}
        filepath = nodes_dir / filename
        if filepath.exists():
            return {"error": f"{filename} already exists. Use edit_node to modify it."}
        nodes_dir.mkdir(parents=True, exist_ok=True)
        init_file = nodes_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")
        filepath.write_text(source)
        discover_nodes()
        return {"ok": True, "path": str(filepath.relative_to(CWD))}

    elif tool_name == "edit_node":
        filename = tool_input["filename"]
        source = tool_input["source"]
        if not re.match(r"^[a-z][a-z0-9_]*\.py$", filename):
            return {"error": f"Invalid filename: {filename}"}
        filepath = nodes_dir / filename
        if not filepath.exists():
            return {"error": f"{filename} not found. Use create_node for new files."}
        filepath.write_text(source)
        discover_nodes()
        return {"ok": True, "path": str(filepath.relative_to(CWD))}

    return {"error": f"Unknown tool: {tool_name}"}


@app.route("/api/workflows/<name>/chat", methods=["POST"])
def api_chat(name: str):
    """Chat with Claude about this workflow. Returns SSE stream."""
    workflow_dir = WORKFLOWS_DIR / name
    if not workflow_dir.exists():
        return jsonify({"error": f"Workflow '{name}' not found"}), 404

    body = request.get_json(force=True)
    user_messages = body.get("messages", [])
    if not user_messages:
        return jsonify({"error": "No messages provided"}), 400

    system_prompt = _build_chat_system(name)

    api_messages = []
    for m in user_messages:
        api_messages.append({"role": m["role"], "content": m["content"]})

    client = anthropic.Anthropic()

    def generate():
        current_messages = list(api_messages)

        while True:
            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=CHAT_TOOLS,
                    messages=current_messages,
                )
            except anthropic.APIError as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                return

            text_parts = []
            tool_uses = []
            assistant_content = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            if text_parts:
                yield f"data: {json.dumps({'type': 'text', 'content': ''.join(text_parts)})}\n\n"

            if response.stop_reason != "tool_use":
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            tool_results = []
            for tu in tool_uses:
                yield f"data: {json.dumps({'type': 'tool_call', 'tool': tu.name, 'input': tu.input})}\n\n"
                result = _handle_tool_call(name, tu.name, tu.input)
                yield f"data: {json.dumps({'type': 'tool_result', 'tool': tu.name, 'result': result})}\n\n"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result),
                })

            current_messages.append({"role": "assistant", "content": assistant_content})
            current_messages.append({"role": "user", "content": tool_results})

    return Response(generate(), mimetype="text/event-stream")


# ------------------------------------------------------------------
# Webhook trigger routes
# ------------------------------------------------------------------
_webhook_routes: dict[tuple[str, str], tuple[str, str]] = {}
_form_routes: dict[str, tuple[str, dict]] = {}


def _resolve_node_class(node_type: str) -> type[BaseNode] | None:
    return node_registry.get(node_type)


def _is_form_trigger(node_type: str) -> bool:
    from choola.core.nodes.form_trigger import FormTrigger
    cls = _resolve_node_class(node_type)
    return cls is not None and issubclass(cls, FormTrigger)


def _is_webhook_trigger(node_type: str) -> bool:
    from choola.core.nodes.webhook_trigger import WebhookTrigger
    cls = _resolve_node_class(node_type)
    return cls is not None and issubclass(cls, WebhookTrigger)


def _is_manual_trigger(node_type: str) -> bool:
    from choola.core.nodes.manual_trigger import ManualTrigger
    cls = _resolve_node_class(node_type)
    return cls is not None and issubclass(cls, ManualTrigger)


def register_webhooks() -> None:
    """Scan workflows for WebhookTrigger and FormTrigger nodes."""
    _webhook_routes.clear()
    _form_routes.clear()
    if not WORKFLOWS_DIR.exists():
        return

    for workflow_dir in sorted(WORKFLOWS_DIR.iterdir()):
        if not workflow_dir.is_dir():
            continue
        try:
            wf = build_workflow(workflow_dir.name)
        except ValueError:
            continue
        for node in wf.get("nodes", []):
            node_type = node.get("type", "")
            cls = node["cls"]

            if _is_webhook_trigger(node_type):
                instance = cls()
                path = instance.config.get("path", "").strip()
                method = instance.config.get("method", "POST").upper()
                response_mode = instance.config.get("response_mode", "after_workflow")
                if not path:
                    continue
                if not path.startswith("/"):
                    path = "/" + path
                path = path.rstrip("/")
                _webhook_routes[(path, method)] = (workflow_dir.name, response_mode)

            elif _is_form_trigger(node_type):
                instance = cls()
                path = instance.config.get("path", "").strip()
                if not path:
                    continue
                if not path.startswith("/"):
                    path = "/" + path
                path = path.rstrip("/")
                _form_routes[path] = (workflow_dir.name, node_type)


# ------------------------------------------------------------------
# Dev test routes
# ------------------------------------------------------------------
_dev_test_sessions: dict[str, str] = {}


def _find_trigger(workflow_name: str) -> tuple[str | None, dict, str | None]:
    try:
        wf = build_workflow(workflow_name)
    except ValueError:
        return None, {}, None
    for node in wf.get("nodes", []):
        node_type = node.get("type", "")
        if _is_webhook_trigger(node_type):
            cls = node["cls"]
            instance = cls()
            return "webhook", instance.config, node_type
        elif _is_form_trigger(node_type):
            cls = node["cls"]
            instance = cls()
            return "form", instance.config, node_type
        elif _is_manual_trigger(node_type):
            cls = node["cls"]
            instance = cls()
            return "manual", instance.config, node_type
    return None, {}, None


@app.route("/api/workflows/<name>/trigger-info")
def api_trigger_info(name: str):
    trigger_type, config, node_type_str = _find_trigger(name)
    return jsonify({
        "trigger_type": trigger_type,
        "config": config,
    })


@app.route("/dev/<name>/form", methods=["GET", "POST"])
def dev_form_handler(name: str):
    trigger_type, config, node_type_str = _find_trigger(name)
    if trigger_type != "form":
        return jsonify({"error": "No FormTrigger found in this workflow"}), 404

    from choola.core.nodes.form_trigger import FormTrigger
    cls = _resolve_node_class(node_type_str) or FormTrigger

    if request.method == "GET":
        run_id = request.args.get("run_id", "")
        instance = cls(config=config)
        html = instance.render_form()
        path = instance.config.get("path", "/")
        if not path.startswith("/"):
            path = "/" + path
        original_action = f"/webhook{path}"
        dev_action = f"/dev/{name}/form?run_id={run_id}"
        html = html.replace(f'action="{original_action}"', f'action="{dev_action}"')
        return Response(html, mimetype="text/html")

    run_id = request.args.get("run_id", uuid.uuid4().hex[:12])
    form_data = dict(request.form)
    payload = {
        "form_data": form_data,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }

    sse_buses.setdefault(run_id, queue.Queue())

    try:
        result = run_workflow(name, payload, run_id=run_id)
        result_json = json.dumps(result.get("payload", {}), indent=2)
        html = f"""<!DOCTYPE html>
<html><head><title>Test Complete</title>
<style>body{{font-family:system-ui;background:#1a1a2e;color:#eee;padding:40px;}}
pre{{background:#0d1117;padding:20px;border-radius:8px;overflow:auto;}}
h2{{color:#22c55e;}}</style></head>
<body><h2>Workflow completed successfully</h2>
<p>You can close this window.</p>
<pre>{result_json}</pre>
<script>window.opener && window.opener.postMessage({{type:'choola-test-done',run_id:'{run_id}',status:'COMPLETED'}},'*');</script>
</body></html>"""
        return Response(html, mimetype="text/html")
    except Exception as exc:
        html = f"""<!DOCTYPE html>
<html><head><title>Test Error</title>
<style>body{{font-family:system-ui;background:#1a1a2e;color:#eee;padding:40px;}}
pre{{background:#0d1117;padding:20px;border-radius:8px;color:#ef4444;}}
h2{{color:#ef4444;}}</style></head>
<body><h2>Workflow Error</h2><pre>{str(exc)}</pre>
<script>window.opener && window.opener.postMessage({{type:'choola-test-done',run_id:'{run_id}',status:'ERROR'}},'*');</script>
</body></html>"""
        return Response(html, mimetype="text/html", status=500)


@app.route("/dev/<name>/webhook", methods=["GET", "POST", "PUT", "DELETE"])
def dev_webhook_handler(name: str):
    trigger_type, config, node_type_str = _find_trigger(name)
    if trigger_type != "webhook":
        return jsonify({"error": "No WebhookTrigger found in this workflow"}), 404

    run_id = request.args.get("run_id", uuid.uuid4().hex[:12])
    method = request.method.upper()

    body: Any = {}
    if request.is_json:
        body = request.get_json(silent=True) or {}
    elif request.data:
        body = request.data.decode("utf-8", errors="replace")

    payload = {
        "method": method,
        "headers": dict(request.headers),
        "query": dict(request.args),
        "body": body,
    }

    sse_buses.setdefault(run_id, queue.Queue())

    try:
        result = run_workflow(name, payload, run_id=run_id)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"status": "ERROR", "error": str(exc), "run_id": run_id}), 500


@app.route("/webhook/<path:webhook_path>", methods=["GET", "POST", "PUT", "DELETE"])
def webhook_handler(webhook_path: str):
    """Catch-all handler for registered webhook and form triggers."""
    path = "/" + webhook_path.strip("/")
    method = request.method.upper()

    if path in _form_routes:
        workflow_name, node_type_str = _form_routes[path]
        from choola.core.nodes.form_trigger import FormTrigger
        cls = _resolve_node_class(node_type_str) or FormTrigger
        instance = cls()

        if method == "GET":
            return Response(instance.render_form(), mimetype="text/html")

        if method == "POST":
            form_data = dict(request.form)
            response_mode = instance.config.get("response_mode", "after_workflow")

            payload = {
                "form_data": form_data,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }

            run_id = uuid.uuid4().hex[:12]
            sse_buses[run_id] = queue.Queue()

            if response_mode == "redirect":
                thread = threading.Thread(
                    target=run_workflow,
                    args=(workflow_name, payload),
                    kwargs={"run_id": run_id},
                    daemon=True,
                )
                thread.start()
                return Response(instance.render_thank_you(), mimetype="text/html")
            else:
                try:
                    result = run_workflow(workflow_name, payload, run_id=run_id)
                    return jsonify(result)
                except Exception as exc:
                    return jsonify({"status": "ERROR", "error": str(exc), "run_id": run_id}), 500

    route_key = (path, method)
    if route_key not in _webhook_routes:
        return jsonify({"error": "No webhook registered for this path/method"}), 404

    workflow_name, response_mode = _webhook_routes[route_key]

    body: Any = {}
    if request.is_json:
        body = request.get_json(silent=True) or {}
    elif request.data:
        body = request.data.decode("utf-8", errors="replace")

    payload = {
        "method": method,
        "headers": dict(request.headers),
        "query": dict(request.args),
        "body": body,
    }

    run_id = uuid.uuid4().hex[:12]
    sse_buses[run_id] = queue.Queue()

    if response_mode == "immediate":
        thread = threading.Thread(
            target=run_workflow,
            args=(workflow_name, payload),
            kwargs={"run_id": run_id},
            daemon=True,
        )
        thread.start()
        return jsonify({"status": "ACCEPTED", "run_id": run_id}), 202
    else:
        try:
            result = run_workflow(workflow_name, payload, run_id=run_id)
            return jsonify(result)
        except Exception as exc:
            return jsonify({"status": "ERROR", "error": str(exc), "run_id": run_id}), 500


# ------------------------------------------------------------------
# Serve React frontend (production build)
# ------------------------------------------------------------------
@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.errorhandler(404)
def fallback(e):
    """SPA fallback — serve index.html for client-side routing."""
    try:
        return app.send_static_file("index.html")
    except Exception:
        return jsonify({"error": "Not found"}), 404


# ------------------------------------------------------------------
# Startup
# ------------------------------------------------------------------
def create_app() -> Flask:
    init_db()
    discover_nodes()
    register_webhooks()
    print(f"[choola] Workflows directory: {WORKFLOWS_DIR}")
    print(f"[choola] Database: {DB_PATH}")
    print(f"[choola] Registered {len(node_registry)} node type(s) from {len(workflow_nodes)} workflow(s)")
    for fq, cls in node_registry.items():
        print(f"  - {cls.name} ({fq})")
    if _webhook_routes:
        print(f"[choola] Registered {len(_webhook_routes)} webhook(s):")
        for (path, method), (wf, mode) in _webhook_routes.items():
            print(f"  - {method} /webhook{path} -> {wf} ({mode})")
    if _form_routes:
        print(f"[choola] Registered {len(_form_routes)} form(s):")
        for path, (wf, _cfg) in _form_routes.items():
            print(f"  - GET+POST /webhook{path} -> {wf}")
    return app
