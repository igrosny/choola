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
cli.py — Choola command-line interface.

Commands:
    choola init              Initialize a new project (workflows/ dir + CLAUDE.md)
    choola start             Start the Choola server
    choola create <name>     Scaffold a new workflow
    choola list              List all workflows in the current project
    choola run <name>        Execute a workflow headlessly
    choola nodes [name]      List available node types
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import shutil
import sys
import traceback
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from choola.core.base_node import BaseNode
from choola.database import (
    get_global_async,
    init_db,
    insert_run_log,
    set_global_async,
    get_credential_async,
)

# Package root — used to locate the bundled CLAUDE.md
_PKG_ROOT = Path(__file__).resolve().parent


# ------------------------------------------------------------------
# Helpers shared by CLI and server
# ------------------------------------------------------------------
def _cwd_workflows() -> Path:
    """Return the workflows/ path relative to cwd."""
    return Path.cwd() / "workflows"


def load_workflow_classes(workflow_name: str) -> dict[str, type[BaseNode]]:
    """Import all BaseNode subclasses from a single workflow folder."""
    nodes_dir = _cwd_workflows() / workflow_name / "nodes"
    if not nodes_dir.exists():
        raise FileNotFoundError(f"No nodes/ directory in workflows/{workflow_name}/")

    registry: dict[str, type[BaseNode]] = {}
    cwd = Path.cwd()
    for py_file in sorted(nodes_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        relative = py_file.relative_to(cwd)
        module_name = str(relative.with_suffix("")).replace("/", ".").replace("\\", ".")
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if isinstance(obj, type) and issubclass(obj, BaseNode) and obj is not BaseNode:
                fq = f"{module_name}.{attr_name}"
                registry[fq] = obj
    return registry


def load_topology(workflow_name: str) -> dict:
    topo_path = _cwd_workflows() / workflow_name / "topology.json"
    if not topo_path.exists():
        raise FileNotFoundError(f"Missing topology.json in workflows/{workflow_name}/")
    return json.loads(topo_path.read_text())


def topological_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
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
        for nb in adjacency[nid]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                q.append(nb)
    if len(order) != len(id_set):
        raise ValueError("Cycle detected in workflow topology")
    return order


# ------------------------------------------------------------------
# Headless execution engine
# ------------------------------------------------------------------
async def execute_workflow(workflow_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    import uuid

    run_id = uuid.uuid4().hex[:12]
    registry = load_workflow_classes(workflow_name)
    topo = load_topology(workflow_name)
    sorted_ids = topological_sort(topo["nodes"], topo["edges"])
    topo_lookup = {n["id"]: n for n in topo["nodes"]}

    context: dict[str, Any] = {
        "workflow": workflow_name,
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    click.echo(f"[choola] Executing workflow: {workflow_name}  (run_id={run_id})")
    click.echo(f"[choola] Nodes in order: {sorted_ids}\n")

    for node_id in sorted_ids:
        topo_node = topo_lookup[node_id]
        node_type = topo_node["type"]
        node_config = topo_node.get("data", {}).get("config", {})

        cls = registry.get(node_type)
        if cls is None:
            click.secho(f"  ERROR  Unknown node type: {node_type}", fg="red")
            raise ValueError(f"Unknown node type: {node_type}")

        instance = cls(node_id=node_id, config=node_config)
        instance._db_get_global = get_global_async
        instance._db_set_global = set_global_async
        instance._db_get_credential = get_credential_async

        click.secho(f"  RUNNING  {cls.name} ({node_id})", fg="yellow")
        now = datetime.now(timezone.utc).isoformat()

        try:
            payload = await instance.execute(payload, context)
            finished = datetime.now(timezone.utc).isoformat()
            click.secho(f"  COMPLETED  {cls.name} -> {json.dumps(payload, default=str)}", fg="green")
            insert_run_log(run_id, workflow_name, node_id, node_type, "COMPLETED",
                           payload_in=payload, payload_out=payload, started_at=now, finished_at=finished)
        except Exception as exc:
            finished = datetime.now(timezone.utc).isoformat()
            click.secho(f"  ERROR  {cls.name}: {exc}", fg="red")
            insert_run_log(run_id, workflow_name, node_id, node_type, "ERROR",
                           payload_in=payload, error=traceback.format_exc(),
                           started_at=now, finished_at=finished)
            raise

    click.echo(f"\n[choola] Workflow completed. Final payload:")
    click.echo(json.dumps(payload, indent=2, default=str))
    return payload


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
@click.group()
def main():
    """Choola — workflow engine for VS Code developers."""


@main.command()
@click.option("--dir", "target", default=".", show_default=True,
              help="Directory to initialize (default: current directory)")
def init(target: str):
    """Initialize a Choola project: create workflows/ and copy CLAUDE.md."""
    project_dir = Path(target).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    # Create workflows/
    workflows_dir = project_dir / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    click.secho(f"  Created  {workflows_dir.relative_to(project_dir)}/", fg="green")

    # Copy bundled CLAUDE.md into the project
    bundled_md = _PKG_ROOT / "CLAUDE.md"
    dest_md = project_dir / "CLAUDE.md"
    if bundled_md.exists():
        shutil.copy2(bundled_md, dest_md)
        click.secho(f"  Created  CLAUDE.md", fg="green")
    else:
        click.secho("  Warning: bundled CLAUDE.md not found — skipping", fg="yellow")

    click.echo(f"\n[choola] Project initialized at {project_dir}")
    click.echo("  Run `choola start` to launch the server.")
    click.echo("  Run `choola create <workflow-name>` to create your first workflow.")


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to")
@click.option("--port", default=5000, show_default=True, help="Port to listen on")
@click.option("--debug", is_flag=True, default=False, help="Enable Flask debug mode")
def start(host: str, port: int, debug: bool):
    """Start the Choola server (blocks until interrupted)."""
    from choola.server import create_app
    flask_app = create_app()
    click.echo(f"[choola] Server starting at http://{host}:{port}")
    flask_app.run(host=host, port=port, debug=debug)


@main.command()
@click.argument("workflow_name")
def create(workflow_name: str):
    """Scaffold a new empty workflow folder."""
    if not all(c.isalnum() or c in ("_", "-") for c in workflow_name):
        click.secho("Name must be alphanumeric (underscores/hyphens allowed).", fg="red")
        raise SystemExit(1)

    workflow_dir = _cwd_workflows() / workflow_name
    if workflow_dir.exists():
        click.secho(f"Workflow '{workflow_name}' already exists.", fg="red")
        raise SystemExit(1)

    nodes_dir = workflow_dir / "nodes"
    nodes_dir.mkdir(parents=True)
    (nodes_dir / "__init__.py").write_text("")
    (workflow_dir / "topology.json").write_text(
        json.dumps({"nodes": [], "edges": []}, indent=2)
    )
    click.secho(f"Created workflow: workflows/{workflow_name}/", fg="green")
    click.echo(f"  workflows/{workflow_name}/topology.json")
    click.echo(f"  workflows/{workflow_name}/nodes/")
    click.echo(f"\nOpen http://localhost:5000 to edit the workflow in the UI.")


@main.command("list")
def list_workflows():
    """List all workflows in the current project."""
    workflows_dir = _cwd_workflows()
    if not workflows_dir.exists():
        click.echo("No workflows/ directory found. Run `choola init` first.")
        return
    found = False
    for d in sorted(workflows_dir.iterdir()):
        if not d.is_dir():
            continue
        found = True
        topo_path = d / "topology.json"
        if topo_path.exists():
            topo = json.loads(topo_path.read_text())
            n_nodes = len(topo.get("nodes", []))
            status = topo.get("status", "draft")
            status_color = "green" if status == "published" else "yellow"
            click.echo(f"  {d.name:<30}", nl=False)
            click.secho(f"[{status}]", fg=status_color, nl=False)
            click.echo(f"  {n_nodes} node(s)")
        else:
            click.secho(f"  {d.name}  (no topology.json)", fg="yellow")
    if not found:
        click.echo("  No workflows found.")


@main.command()
@click.argument("workflow_name")
@click.option("--payload", "-p", default="{}", help="JSON payload string")
def run(workflow_name: str, payload: str):
    """Execute a workflow headlessly (no server required)."""
    init_db()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        click.secho(f"Invalid JSON payload: {e}", fg="red")
        raise SystemExit(1)
    asyncio.run(execute_workflow(workflow_name, data))


@main.command()
@click.argument("workflow_name", required=False)
def nodes(workflow_name: str | None):
    """List registered node types. Pass a workflow name to include its nodes."""
    if workflow_name:
        registry = load_workflow_classes(workflow_name)
        for fq, cls in registry.items():
            click.echo(f"  {cls.name:<25}  [{cls.category}]  {fq}")
    else:
        # List core nodes only
        import choola.core.nodes.form_trigger as _ft
        import choola.core.nodes.webhook_trigger as _wt
        import choola.core.nodes.llm as _llm
        for mod in (_ft, _wt, _llm):
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if isinstance(obj, type) and issubclass(obj, BaseNode) and obj is not BaseNode:
                    click.echo(f"  {obj.name:<25}  [{obj.category}]  (core)")


if __name__ == "__main__":
    main()
