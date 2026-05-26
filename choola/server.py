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
import functools
import hmac
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request
from flask_sock import Sock
from werkzeug.middleware.proxy_fix import ProxyFix

from choola import engine
from choola.core.base_node import BaseNode
from choola.engine import topological_sort  # re-exported for backward compatibility
from choola.database import (
    DB_PATH,
    delete_credential,
    get_credential,
    get_global_sync,
    init_db,
    list_credentials,
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
_STATIC_DIR = ROOT / "static" / "dist"

app = Flask(__name__, static_folder=str(_STATIC_DIR), static_url_path="/")
# Trust X-Forwarded-Proto / X-Forwarded-Host from a single trusted reverse proxy
# (e.g. cloudflared) so request.host_url yields the public https://... URL used
# as the OAuth redirect_uri instead of http://127.0.0.1:5000/.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
sock = Sock(app)

# Global registries populated at startup
node_registry: dict[str, type[BaseNode]] = {}        # "module.ClassName" -> class
workflow_nodes: dict[str, list[type[BaseNode]]] = {}  # "workflow_name" -> [classes]

# SSE event bus: run_id -> Queue
sse_buses: dict[str, queue.Queue] = {}


# ------------------------------------------------------------------
# /api/* bearer-token auth (opt-in via the `api_token` global)
# ------------------------------------------------------------------
# Paths under /api/ that must remain open even when api_token is set.
# - Google's OAuth2 redirect lands on /api/oauth2/google/callback and is signed
#   via the state parameter, so it doesn't need (and can't have) a bearer token.
_API_AUTH_EXEMPT_PREFIXES = ("/api/oauth2/google/callback",)


@app.before_request
def _require_api_token():
    path = request.path or ""
    if not path.startswith("/api/"):
        return None
    if any(path.startswith(p) for p in _API_AUTH_EXEMPT_PREFIXES):
        return None

    expected = get_global_sync("api_token") or ""
    if not expected:
        return None  # auth disabled

    # Browsers' EventSource can't set headers — accept ?token=... for SSE only.
    supplied = ""
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if header.startswith(prefix):
        supplied = header[len(prefix):]
    elif "/stream/" in path:
        supplied = request.args.get("token", "")

    if not supplied or not hmac.compare_digest(str(expected), supplied):
        return jsonify({"error": "Unauthorized"}), 401
    return None


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
            edges.append({"id": f"{nid}-{target}", "source": nid, "target": target})

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


# ------------------------------------------------------------------
# Execution engine — delegates to choola.engine, supplying an SSE emit callback
# ------------------------------------------------------------------
def _sse_emit(run_id: str, event: str, data: dict) -> None:
    """Push an SSE event onto the bus for the given run."""
    bus = sse_buses.get(run_id)
    if bus:
        bus.put(f"event: {event}\ndata: {json.dumps(data)}\n\n")


# Back-compat alias for code that imported the old private emitter.
def _emit(run_id: str, event: str, data: dict) -> None:
    _sse_emit(run_id, event, data)


def run_workflow(workflow_name: str, payload: dict[str, Any], run_id: str | None = None) -> dict:
    """Execute a workflow synchronously (uses asyncio.run internally)."""
    run_id = run_id or engine.make_run_id()
    return asyncio.run(_run_workflow_async(workflow_name, payload, run_id))


async def _run_workflow_async(workflow_name: str, payload: dict[str, Any], run_id: str) -> dict:
    wf = build_workflow(workflow_name)
    emit = functools.partial(_sse_emit, run_id)
    return await engine.execute_dag(workflow_name, wf, payload, run_id, emit=emit)


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

            # Auto-layout: walk DAG in topological order so unsaved nodes get spaced out
            edges = wf["edges"]
            children = {}
            has_parent = set()
            for e in edges:
                children.setdefault(e["source"], []).append(e["target"])
                has_parent.add(e["target"])
            roots = [n["id"] for n in wf["nodes"] if n["id"] not in has_parent]
            ordered = []
            visited = set()
            queue = list(roots)
            while queue:
                nid = queue.pop(0)
                if nid in visited:
                    continue
                visited.add(nid)
                ordered.append(nid)
                for child in children.get(nid, []):
                    queue.append(child)
            # Assign default positions spaced vertically
            auto_positions = {}
            for i, nid in enumerate(ordered):
                auto_positions[nid] = {"x": 250, "y": 80 + i * 150}
            # Include any nodes not reached by the walk
            for node in wf["nodes"]:
                if node["id"] not in auto_positions:
                    auto_positions[node["id"]] = {"x": 250, "y": 80 + len(auto_positions) * 150}

            nodes = []
            for node in wf["nodes"]:
                nid = node["id"]
                cls = node["cls"]
                nodes.append({
                    "id": nid,
                    "type": node["type"],
                    "position": positions.get(nid, auto_positions.get(nid, {"x": 250, "y": 250})),
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
        # Preserve existing positions from topology.json
        ui_data = load_topology(name)
        positions = {n.get("id"): n.get("position", {}) for n in ui_data.get("nodes", [])}

        # Auto-layout for nodes without saved positions
        edges = wf["edges"]
        children = {}
        has_parent = set()
        for e in edges:
            children.setdefault(e["source"], []).append(e["target"])
            has_parent.add(e["target"])
        roots = [n["id"] for n in wf["nodes"] if n["id"] not in has_parent]
        ordered = []
        visited = set()
        queue = list(roots)
        while queue:
            nid = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            ordered.append(nid)
            for child in children.get(nid, []):
                queue.append(child)
        auto_positions = {}
        for i, nid in enumerate(ordered):
            auto_positions[nid] = {"x": 250, "y": 80 + i * 150}
        for node in wf["nodes"]:
            if node["id"] not in auto_positions:
                auto_positions[node["id"]] = {"x": 250, "y": 80 + len(auto_positions) * 150}

        nodes = []
        for n in wf["nodes"]:
            nid = n["id"]
            cls = n["cls"]
            nodes.append({
                "id": nid,
                "type": n["type"],
                "position": positions.get(nid, auto_positions.get(nid, {"x": 250, "y": 250})),
                "data": {"label": cls.name, "config": {}},
            })
        return jsonify({"nodes": nodes, "edges": wf["edges"]})
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


@app.route("/api/workflows/<name>/db/schema", methods=["GET"])
def api_workflow_db_schema(name: str):
    """Introspect the workflow's SQLite DB — tables and their columns."""
    import sqlite3

    db_file = WORKFLOWS_DIR / name / "files" / "db.sqlite"
    if not db_file.exists():
        return jsonify({"exists": False, "tables": []})

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        tables = [
            dict(r) for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
        ]
        for t in tables:
            cols = conn.execute(f"PRAGMA table_info(\"{t['name']}\")").fetchall()
            t["columns"] = [
                {
                    "name": c["name"],
                    "type": c["type"] or "",
                    "notnull": bool(c["notnull"]),
                    "pk": bool(c["pk"]),
                    "default": c["dflt_value"],
                }
                for c in cols
            ]
            row_count = conn.execute(f"SELECT COUNT(*) AS n FROM \"{t['name']}\"").fetchone()
            t["row_count"] = row_count["n"] if row_count else 0
        return jsonify({"exists": True, "tables": tables, "path": str(db_file)})
    finally:
        conn.close()


@app.route("/api/workflows/<name>/db/query", methods=["POST"])
def api_workflow_db_query(name: str):
    """Run a SQL statement against the workflow's SQLite DB and return rows."""
    import sqlite3
    import time

    db_file = WORKFLOWS_DIR / name / "files" / "db.sqlite"
    if not db_file.exists():
        return jsonify({"error": "Database does not exist for this workflow."}), 404

    data = request.get_json(silent=True) or {}
    sql = (data.get("sql") or "").strip()
    if not sql:
        return jsonify({"error": "sql is required"}), 400

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        start = time.time()
        cursor = conn.execute(sql)
        duration_ms = int((time.time() - start) * 1000)
        if cursor.description is not None:
            columns = [c[0] for c in cursor.description]
            rows = [[r[c] for c in columns] for r in cursor.fetchall()]
            return jsonify({
                "columns": columns,
                "rows": rows,
                "rowcount": len(rows),
                "duration_ms": duration_ms,
            })
        conn.commit()
        return jsonify({
            "columns": [],
            "rows": [],
            "rowcount": cursor.rowcount,
            "duration_ms": duration_ms,
        })
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/api/workflows/<name>/vectordb/schema", methods=["GET"])
def api_workflow_vectordb_schema(name: str):
    """List the workflow's ChromaDB collections with their item counts."""
    chroma_dir = WORKFLOWS_DIR / name / "files" / "chroma"
    if not chroma_dir.exists():
        return jsonify({"exists": False, "collections": []})

    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(chroma_dir))
        cols = []
        for col in client.list_collections():
            try:
                instance = client.get_collection(name=col.name)
                count = instance.count()
            except Exception:
                count = None
            cols.append({
                "name": col.name,
                "metadata": dict(col.metadata or {}),
                "count": count,
            })
        return jsonify({"exists": True, "collections": cols, "path": str(chroma_dir)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/workflows/<name>/vectordb/query", methods=["POST"])
def api_workflow_vectordb_query(name: str):
    """Similarity-search a collection in the workflow's ChromaDB.

    Body: { collection, query, n_results? }
    """
    import time

    chroma_dir = WORKFLOWS_DIR / name / "files" / "chroma"
    if not chroma_dir.exists():
        return jsonify({"error": "Vector store does not exist for this workflow."}), 404

    data = request.get_json(silent=True) or {}
    collection = (data.get("collection") or "").strip()
    query_text = (data.get("query") or "").strip()
    n_results = int(data.get("n_results") or 10)

    if not collection:
        return jsonify({"error": "collection is required"}), 400
    if not query_text:
        return jsonify({"error": "query is required"}), 400

    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(chroma_dir))
        col = client.get_collection(name=collection)
        start = time.time()
        result = col.query(query_texts=[query_text], n_results=max(1, min(n_results, 100)))
        duration_ms = int((time.time() - start) * 1000)
        # ChromaDB returns keys as lists-of-lists (one per input query). Flatten.
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits = [
            {
                "id": i,
                "document": d,
                "metadata": m or {},
                "distance": dist,
            }
            for i, d, m, dist in zip(ids, documents, metadatas, distances)
        ]
        return jsonify({
            "collection": collection,
            "query": query_text,
            "hits": hits,
            "duration_ms": duration_ms,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/workflows/<name>/evaluations", methods=["GET"])
def api_list_evaluations(name: str):
    """Paginated list of evaluations (summaries only, newest first).

    Each file can be hundreds of KB, so we read the JSON to pluck the
    header fields and skip nested payloads. Sorted by started_at desc.
    """
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = max(1, min(100, int(request.args.get("page_size", 20))))
    except ValueError:
        page_size = 20

    eval_dir = WORKFLOWS_DIR / name / "evaluations"
    if not eval_dir.exists():
        return jsonify({"evaluations": [], "total": 0, "page": page, "page_size": page_size})

    files = list(eval_dir.glob("*.json"))
    summaries = []
    for f in files:
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        nodes = data.get("nodes") or []
        tokens = data.get("tokens") or {}
        summaries.append({
            "run_id": data.get("run_id") or f.stem,
            "status": data.get("status"),
            "started_at": data.get("started_at"),
            "finished_at": data.get("finished_at"),
            "duration_ms": data.get("duration_ms"),
            "node_count": len(nodes),
            "error_count": sum(1 for n in nodes if n.get("status") == "ERROR"),
            "total_tokens": (tokens.get("total_tokens") if isinstance(tokens, dict) else 0) or 0,
            "has_error": bool(data.get("error")),
        })

    summaries.sort(key=lambda s: s.get("started_at") or "", reverse=True)
    total = len(summaries)
    start = (page - 1) * page_size
    paged = summaries[start:start + page_size]

    return jsonify({
        "evaluations": paged,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@app.route("/api/workflows/<name>/evaluations/<run_id>", methods=["GET"])
def api_get_evaluation(name: str, run_id: str):
    """Return the full evaluation JSON for a single run."""
    if not re.match(r"^[A-Za-z0-9_\-]+$", run_id):
        return jsonify({"error": "Invalid run_id"}), 400
    path = WORKFLOWS_DIR / name / "evaluations" / f"{run_id}.json"
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return Response(path.read_text(), content_type="application/json")


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


# ------------------------------------------------------------------
# MCP endpoint — one JSON-RPC surface that exposes every workflow as a tool
# ------------------------------------------------------------------
@app.route("/mcp", methods=["POST"])
def api_mcp():
    """JSON-RPC 2.0 endpoint implementing the minimum MCP methods."""
    from choola import mcp as mcp_module

    # Bearer-token auth: opt-in via the `mcp_token` global. Empty/unset = open.
    expected = get_global_sync("mcp_token") or ""
    if expected:
        header = request.headers.get("Authorization", "")
        prefix = "Bearer "
        supplied = header[len(prefix):] if header.startswith(prefix) else ""
        if not supplied or not hmac.compare_digest(str(expected), supplied):
            return jsonify({"error": "Unauthorized"}), 401

    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        return jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": mcp_module.PARSE_ERROR, "message": "Invalid JSON"},
        }), 400

    if not isinstance(body, dict):
        return jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": mcp_module.INVALID_REQUEST, "message": "Expected a JSON object"},
        }), 400

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if not isinstance(method, str) or not method:
        return jsonify({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": mcp_module.INVALID_REQUEST, "message": "Missing 'method'"},
        }), 400

    try:
        result, error = mcp_module.dispatch(method, params if isinstance(params, dict) else {})
    except Exception as exc:
        tb = traceback.format_exc()
        return jsonify({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": mcp_module.INTERNAL_ERROR,
                "message": str(exc),
                "data": {"traceback": tb},
            },
        }), 200

    # Notifications carry no id → no response body expected.
    if req_id is None and result is None and error is None:
        return ("", 204)

    if error is not None:
        return jsonify({"jsonrpc": "2.0", "id": req_id, "error": error}), 200
    return jsonify({"jsonrpc": "2.0", "id": req_id, "result": result}), 200


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

# Catalog of Google API scopes the UI offers. Key is the short id used in the
# frontend checklist; value is (full scope URL, human label).
GOOGLE_SCOPE_CATALOG: dict[str, tuple[str, str]] = {
    "gmail.send":       ("https://www.googleapis.com/auth/gmail.send",       "Gmail — send"),
    "gmail.readonly":   ("https://www.googleapis.com/auth/gmail.readonly",   "Gmail — read"),
    "gmail.modify":     ("https://www.googleapis.com/auth/gmail.modify",     "Gmail — modify"),
    "drive.file":       ("https://www.googleapis.com/auth/drive.file",       "Drive — files created by this app"),
    "drive.readonly":   ("https://www.googleapis.com/auth/drive.readonly",   "Drive — read all"),
    "drive":            ("https://www.googleapis.com/auth/drive",            "Drive — full access"),
    "sheets":           ("https://www.googleapis.com/auth/spreadsheets",     "Sheets — read/write"),
    "sheets.readonly":  ("https://www.googleapis.com/auth/spreadsheets.readonly", "Sheets — read"),
    "calendar":         ("https://www.googleapis.com/auth/calendar",         "Calendar — read/write"),
    "calendar.events":  ("https://www.googleapis.com/auth/calendar.events",  "Calendar — events"),
    "calendar.readonly":("https://www.googleapis.com/auth/calendar.readonly","Calendar — read"),
    "contacts.readonly":("https://www.googleapis.com/auth/contacts.readonly","Contacts — read"),
    "docs":             ("https://www.googleapis.com/auth/documents",        "Docs — read/write"),
    "docs.readonly":    ("https://www.googleapis.com/auth/documents.readonly","Docs — read"),
    "userinfo.email":   ("https://www.googleapis.com/auth/userinfo.email",   "Profile — email"),
    "userinfo.profile": ("https://www.googleapis.com/auth/userinfo.profile", "Profile — basic info"),
}


def _resolve_scope_ids(scope_ids: list[str]) -> list[str]:
    """Map short ids to full scope URLs; raise ValueError on unknown id."""
    urls: list[str] = []
    for sid in scope_ids:
        entry = GOOGLE_SCOPE_CATALOG.get(sid)
        if not entry:
            raise ValueError(f"Unknown Google scope id: {sid}")
        urls.append(entry[0])
    return urls


@app.route("/api/oauth2/google/scopes")
def api_oauth2_google_scopes():
    """Return the scope catalog so the UI can render checkboxes."""
    return jsonify([
        {"id": sid, "url": url, "label": label}
        for sid, (url, label) in GOOGLE_SCOPE_CATALOG.items()
    ])


@app.route("/api/oauth2/google/start", methods=["POST"])
def api_oauth2_google_start():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    client_id = data.get("client_id", "").strip()
    client_secret = data.get("client_secret", "").strip()
    scope_ids = data.get("scopes") or []

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not all(c.isalnum() or c in ("_", "-") for c in name):
        return jsonify({"error": "name must be alphanumeric (underscores/hyphens allowed)"}), 400
    if not isinstance(scope_ids, list) or not scope_ids:
        return jsonify({"error": "scopes must be a non-empty list"}), 400

    # If a credential with this name already exists, let the user extend its
    # scopes without re-entering client_id / client_secret.
    existing = get_credential(name)
    if existing and existing.get("provider") == "google":
        try:
            existing_tokens = json.loads(existing["value"])
        except json.JSONDecodeError:
            existing_tokens = {}
        client_id = client_id or existing_tokens.get("client_id", "")
        client_secret = client_secret or existing_tokens.get("client_secret", "")
        prior_scope_ids = existing_tokens.get("scopes") or []
        scope_ids = sorted(set(prior_scope_ids) | set(scope_ids))

    if not client_id or not client_secret:
        return jsonify({"error": "client_id and client_secret are required"}), 400

    try:
        scope_urls = _resolve_scope_ids(scope_ids)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    state = uuid.uuid4().hex
    _oauth2_pending[state] = {
        "name": name,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope_ids": scope_ids,
    }

    callback_url = request.host_url.rstrip("/") + "/api/oauth2/google/callback"
    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": " ".join(scope_urls),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
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

    # Google returns the granted scope list as a space-separated string; store
    # it verbatim so nodes can check against the full URL catalog.
    granted_scope_urls = (tokens.get("scope") or "").split()
    # Map granted URLs back to short ids when possible for display.
    url_to_id = {url: sid for sid, (url, _label) in GOOGLE_SCOPE_CATALOG.items()}
    granted_scope_ids = [url_to_id[u] for u in granted_scope_urls if u in url_to_id]

    credential_value = json.dumps({
        "client_id": pending["client_id"],
        "client_secret": pending["client_secret"],
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_uri": GOOGLE_TOKEN_URL,
        "scopes": granted_scope_ids or pending["scope_ids"],
        "scope_urls": granted_scope_urls,
    })

    upsert_credential(pending["name"], "google", credential_value)

    return f"""
    <html><body style="background:#1a1a2e;color:#eee;font-family:sans-serif;display:flex;
    align-items:center;justify-content:center;height:100vh;margin:0">
    <div style="text-align:center">
      <h2 style="color:#4ade80">Connected to Google</h2>
      <p>Credential saved. You can close this tab.</p>
      <script>if(window.opener){{window.opener.postMessage('oauth2_done','*')}}</script>
    </div></body></html>
    """




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
# Terminal (PTY over WebSocket, with persistent sessions)
# ------------------------------------------------------------------
# The pty lives in a server-side session registry so it survives WebSocket
# disconnects (page refresh, browser navigation). Clients reattach by passing
# the session id they received on the original connect.
_TERMINAL_BUFFER_BYTES = 256 * 1024  # ~256KB scrollback replayed on reattach
_terminal_sessions: dict[str, dict] = {}
_terminal_sessions_lock = threading.Lock()


def _terminal_set_winsize(fd: int, rows: int, cols: int) -> None:
    import fcntl
    import struct
    import termios
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


def _terminal_spawn(start_dir: Path) -> tuple[int, int]:
    import pty
    shell = os.environ.get("SHELL", "/bin/bash")
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(str(start_dir))
        except Exception:
            pass
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        os.execvpe(shell, [shell], env)
    return pid, fd


def _terminal_reader(session: dict) -> None:
    """Owns the pty fd for one session. Buffers output for replay and forwards
    to whichever WebSocket is currently attached. Runs until the shell exits.
    """
    import select as _select
    import signal as _signal

    fd = session["fd"]
    while session["alive"]:
        try:
            r, _, _ = _select.select([fd], [], [], 0.5)
        except (OSError, ValueError):
            break
        if fd not in r:
            continue
        try:
            data = os.read(fd, 4096)
        except OSError:
            break
        if not data:
            break

        with session["lock"]:
            buf = session["buffer"]
            buf.extend(data)
            if len(buf) > _TERMINAL_BUFFER_BYTES:
                del buf[: len(buf) - _TERMINAL_BUFFER_BYTES]

        ws = session.get("ws")
        if ws is not None:
            try:
                ws.send(json.dumps({
                    "type": "output",
                    "data": data.decode("utf-8", errors="replace"),
                }))
            except Exception:
                # Attached ws is gone; another may reattach later.
                pass

    session["alive"] = False
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.kill(session["pid"], _signal.SIGHUP)
    except (OSError, ProcessLookupError):
        pass
    try:
        os.waitpid(session["pid"], os.WNOHANG)
    except (OSError, ChildProcessError):
        pass
    with _terminal_sessions_lock:
        _terminal_sessions.pop(session["id"], None)


@sock.route("/api/terminal")
def terminal_socket(ws):
    """Bridge a persistent bash pty with the browser xterm.

    Query params:
      session_id  Existing session to reattach to. If missing or unknown a new
                  session is spawned in CWD and its id is sent back to the
                  client on connect.

    Both directions speak JSON-encoded text frames:
      client -> server:
        {"type": "input",  "data": "<str>"}
        {"type": "resize", "rows": N, "cols": N}
      server -> client:
        {"type": "session", "id": "<str>"}      (sent once at connect)
        {"type": "output",  "data": "<str>"}    (pty stdout, incl. replay)
    """
    import secrets

    requested = (request.args.get("session_id") or "").strip()
    session = None
    if requested:
        with _terminal_sessions_lock:
            existing = _terminal_sessions.get(requested)
            if existing and existing.get("alive"):
                session = existing

    if session is None:
        pid, fd = _terminal_spawn(CWD)
        session_id = secrets.token_hex(16)
        session = {
            "id": session_id,
            "pid": pid,
            "fd": fd,
            "buffer": bytearray(),
            "lock": threading.Lock(),
            "alive": True,
            "ws": None,
        }
        with _terminal_sessions_lock:
            _terminal_sessions[session_id] = session
        threading.Thread(target=_terminal_reader, args=(session,), daemon=True).start()

    previous_ws = session.get("ws")
    session["ws"] = ws
    if previous_ws is not None and previous_ws is not ws:
        try:
            previous_ws.close()
        except Exception:
            pass

    try:
        ws.send(json.dumps({"type": "session", "id": session["id"]}))
        with session["lock"]:
            replay = bytes(session["buffer"])
        if replay:
            ws.send(json.dumps({
                "type": "output",
                "data": replay.decode("utf-8", errors="replace"),
            }))
    except Exception:
        if session.get("ws") is ws:
            session["ws"] = None
        return

    try:
        while session["alive"]:
            msg = ws.receive(timeout=1)
            if msg is None:
                continue
            try:
                parsed = json.loads(msg)
            except Exception:
                continue
            mtype = parsed.get("type")
            if mtype == "input":
                data = parsed.get("data", "")
                try:
                    os.write(session["fd"], data.encode("utf-8"))
                except OSError:
                    break
            elif mtype == "resize":
                _terminal_set_winsize(
                    session["fd"],
                    int(parsed.get("rows", 24)),
                    int(parsed.get("cols", 80)),
                )
    finally:
        # Detach this ws but keep the pty alive for a future reconnect.
        if session.get("ws") is ws:
            session["ws"] = None


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

    mcp_auth = "enabled" if (get_global_sync("mcp_token") or "") else (
        "disabled — set `mcp_token` global to require a bearer token"
    )
    print(f"[choola] MCP: POST /mcp (auth: {mcp_auth})")
    api_auth = "enabled" if (get_global_sync("api_token") or "") else (
        "disabled — set `api_token` global to require a bearer token"
    )
    print(f"[choola] API: /api/* (auth: {api_auth})")
    return app
