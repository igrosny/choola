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
    choola replay <wf> <run> <node>  Re-run one node with saved evaluation input
    choola nodes [name]      List available node types
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import importlib
import importlib.util
import json
import shutil
import sys
import threading
import time
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
    upsert_credential,
    workflow_db_execute_async,
    workflow_db_query_async,
    workflow_vector_add_async,
    workflow_vector_count_async,
    workflow_vector_delete_async,
    workflow_vector_get_async,
    workflow_vector_query_async,
)
from choola.evaluations import (
    build_evaluation,
    capture_payload,
    make_node_eval,
    save_evaluation,
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
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseNode)
                and obj is not BaseNode
                and obj.__module__ == module_name
            ):
                fq = f"{module_name}.{attr_name}"
                registry[fq] = obj
    return registry


def build_workflow(registry: dict[str, type[BaseNode]]) -> dict:
    """Build the workflow DAG from node class attributes (node_id, next_nodes).

    Returns a dict with 'nodes' and 'edges' suitable for topological_sort.
    """
    # Map node_id -> (fq_name, cls) for all nodes that declare a node_id
    by_id: dict[str, tuple[str, type[BaseNode]]] = {}
    for fq_name, cls in registry.items():
        nid = cls.node_id
        if not nid:
            continue
        if nid in by_id:
            other_fq = by_id[nid][0]
            raise ValueError(f"Duplicate node_id '{nid}': {fq_name} and {other_fq}")
        by_id[nid] = (fq_name, cls)

    if not by_id:
        raise ValueError("No nodes with a node_id found in this workflow")

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


def _elapsed_str(start_iso: str, end_iso: str) -> str:
    """Return a human-readable elapsed time string like '1.2s' or '350ms'."""
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    ms = (end - start).total_seconds() * 1000
    if ms < 1000:
        return f"({int(ms)}ms)"
    return f"({ms / 1000:.1f}s)"


# ------------------------------------------------------------------
# Headless execution engine
# ------------------------------------------------------------------
async def execute_workflow(workflow_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    import uuid

    run_id = uuid.uuid4().hex[:12]
    registry = load_workflow_classes(workflow_name)
    wf = build_workflow(registry)
    sorted_ids = topological_sort(wf["nodes"], wf["edges"])
    node_lookup = {n["id"]: n for n in wf["nodes"]}

    context: dict[str, Any] = {
        "workflow": workflow_name,
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    click.echo(f"[choola] Executing workflow: {workflow_name}  (run_id={run_id})")
    click.echo(f"[choola] Nodes in order: {sorted_ids}\n")

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
        instance._db_query = functools.partial(workflow_db_query_async, workflow_name)
        instance._db_execute = functools.partial(workflow_db_execute_async, workflow_name)
        instance._vector_add = functools.partial(workflow_vector_add_async, workflow_name)
        instance._vector_query = functools.partial(workflow_vector_query_async, workflow_name)
        instance._vector_get = functools.partial(workflow_vector_get_async, workflow_name)
        instance._vector_delete = functools.partial(workflow_vector_delete_async, workflow_name)
        instance._vector_count = functools.partial(workflow_vector_count_async, workflow_name)

        now = datetime.now(timezone.utc).isoformat()
        payload_before = capture_payload(payload)

        # Spinner runs while the node executes
        spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        stop_spinner = threading.Event()

        def _spin(_label=f"{cls.name} ({node_id})"):
            i = 0
            while not stop_spinner.is_set():
                char = spinner_chars[i % len(spinner_chars)]
                click.echo(f"\r  {char} RUNNING  {_label}  ", nl=False)
                i += 1
                time.sleep(0.08)

        spin_thread = threading.Thread(target=_spin, daemon=True)
        spin_thread.start()

        try:
            payload = await instance.execute(payload, context)
            finished = datetime.now(timezone.utc).isoformat()
            stop_spinner.set()
            spin_thread.join()
            elapsed = _elapsed_str(now, finished)
            click.echo(f"\r  COMPLETED  {cls.name} -> {json.dumps(payload, default=str)}  ", nl=False)
            click.secho(elapsed, fg="green")
            insert_run_log(run_id, workflow_name, node_id, node_type, "COMPLETED",
                           payload_in=payload_before, payload_out=payload, started_at=now, finished_at=finished)
            node_evals.append(make_node_eval(node_id, node_type, "COMPLETED", now, finished, payload_before, capture_payload(payload)))
        except Exception as exc:
            finished = datetime.now(timezone.utc).isoformat()
            stop_spinner.set()
            spin_thread.join()
            tb = traceback.format_exc()
            click.echo(f"\r  ", nl=False)
            click.secho(f"ERROR  {cls.name}: {exc}", fg="red")
            insert_run_log(run_id, workflow_name, node_id, node_type, "ERROR",
                           payload_in=payload_before, error=tb,
                           started_at=now, finished_at=finished)
            node_evals.append(make_node_eval(node_id, node_type, "ERROR", now, finished, payload_before, error=tb))
            evaluation = build_evaluation(run_id, workflow_name, context["started_at"], initial_payload, node_evals, "ERROR", error=tb)
            save_evaluation(workflow_name, evaluation)
            raise

    evaluation = build_evaluation(run_id, workflow_name, context["started_at"], initial_payload, node_evals, "COMPLETED", payload)
    eval_path = save_evaluation(workflow_name, evaluation)
    click.echo(f"\n[choola] Workflow completed. Final payload:")
    click.echo(json.dumps(payload, indent=2, default=str))
    click.echo(f"[choola] Evaluation saved: {eval_path}")
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
    (workflow_dir / "files").mkdir()
    click.secho(f"Created workflow: workflows/{workflow_name}/", fg="green")
    click.echo(f"  workflows/{workflow_name}/nodes/")
    click.echo(f"  workflows/{workflow_name}/files/")
    click.echo(f"\nAdd node files to nodes/ and run `choola run {workflow_name}` to execute.")


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
        nodes_dir = d / "nodes"
        n_nodes = 0
        if nodes_dir.exists():
            n_nodes = sum(1 for f in nodes_dir.glob("*.py") if not f.name.startswith("_"))
        click.echo(f"  {d.name:<30}  {n_nodes} node(s)")
    if not found:
        click.echo("  No workflows found.")


@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("workflow_name")
@click.argument("field_values", nargs=-1, type=click.UNPROCESSED)
@click.option("--payload", "-p", default="{}", help="JSON payload string")
def run(workflow_name: str, field_values: tuple[str, ...], payload: str):
    """Execute a workflow headlessly (no server required).

    Positional values after the workflow name are mapped to the trigger
    node's form_fields in order:

        choola run bank-statement ../test.pdf 1BxiMVs...
    """
    init_db()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        click.secho(f"Invalid JSON payload: {e}", fg="red")
        raise SystemExit(1)

    if field_values:
        from choola.core.nodes.form_trigger import FormTrigger

        registry = load_workflow_classes(workflow_name)
        trigger_cls = None
        for cls in registry.values():
            if issubclass(cls, FormTrigger):
                trigger_cls = cls
                break
        if trigger_cls is None:
            click.secho("No FormTrigger found in this workflow — cannot map positional args", fg="red")
            raise SystemExit(1)

        # Extract form_fields from the trigger's fields definition
        form_fields_def = []
        for f in trigger_cls.fields:
            if f.get("name") == "form_fields":
                raw = f.get("default", [])
                if isinstance(raw, str):
                    form_fields_def = json.loads(raw)
                else:
                    form_fields_def = raw
                break

        field_names = [ff["field_name"] for ff in form_fields_def]
        if len(field_values) > len(field_names):
            click.secho(
                f"Too many values: got {len(field_values)} but trigger only has "
                f"{len(field_names)} field(s): {', '.join(field_names)}",
                fg="red",
            )
            raise SystemExit(1)

        form_data = dict(zip(field_names, field_values))
        data.setdefault("form_data", {}).update(form_data)

    try:
        asyncio.run(execute_workflow(workflow_name, data))
    except Exception:
        raise SystemExit(1)


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
        from choola.core.nodes.trigger import Trigger
        import choola.core.nodes.form_trigger as _ft
        import choola.core.nodes.webhook_trigger as _wt
        import choola.core.nodes.llm as _llm
        import choola.core.nodes.manual_trigger as _mt
        import choola.core.nodes.http as _http
        import choola.core.nodes.db as _db
        import choola.core.nodes.vectordb as _vdb
        seen = set()
        skip = {BaseNode, Trigger}
        for mod in (_ft, _wt, _llm, _mt, _http, _db, _vdb):
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseNode)
                    and obj not in skip
                    and obj not in seen
                ):
                    seen.add(obj)
                    click.echo(f"  {obj.name:<25}  [{obj.category}]  (core)")


CREDENTIAL_PROVIDERS = [
    ("claude", "Claude"),
    ("openai", "OpenAI"),
    ("google", "Google"),
    ("google_oauth2", "Google OAuth2"),
    ("gmail", "Gmail"),
]

_OAUTH2_PROVIDERS = {"google_oauth2", "gmail"}


@main.command()
@click.argument("name")
def credential(name: str):
    """Store a credential interactively (provider and value are prompted)."""
    init_db()

    click.echo("Select a provider:")
    for i, (_, label) in enumerate(CREDENTIAL_PROVIDERS, 1):
        click.echo(f"  {i}. {label}")

    choice = click.prompt("Enter number", type=click.IntRange(1, len(CREDENTIAL_PROVIDERS)))
    provider = CREDENTIAL_PROVIDERS[choice - 1][0]

    if provider in _OAUTH2_PROVIDERS:
        client_id = click.prompt("Client ID (hidden)", hide_input=True)
        client_secret = click.prompt("Client Secret (hidden)", hide_input=True)

        from urllib.parse import urlencode

        scopes = {
            "google_oauth2": "https://www.googleapis.com/auth/drive.file",
            "gmail": "https://www.googleapis.com/auth/gmail.send",
        }
        redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scopes[provider],
            "access_type": "offline",
            "prompt": "consent",
        })

        click.echo()
        click.echo("Open this URL in your browser to authorize:")
        click.echo()
        click.secho(f"  {auth_url}", fg="cyan")
        click.echo()
        code = click.prompt("Paste the authorization code here")

        import requests as http_requests

        token_url = "https://oauth2.googleapis.com/token"
        token_resp = http_requests.post(token_url, data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })

        if token_resp.status_code != 200:
            click.secho(f"Token exchange failed: {token_resp.text}", fg="red")
            raise SystemExit(1)

        tokens = token_resp.json()
        value = json.dumps({
            "client_id": client_id,
            "client_secret": client_secret,
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "token_uri": token_url,
        })
    else:
        value = click.prompt("API key (hidden)", hide_input=True)

    upsert_credential(name, provider, value)
    click.secho(f"Credential '{name}' saved (provider: {provider}).", fg="green")


@main.command()
@click.argument("workflow_name")
@click.argument("run_id")
@click.argument("node_id")
@click.option("--payload", "-p", default=None, help="Override input payload (JSON string)")
@click.option("--no-diff", is_flag=True, help="Suppress output diff")
def replay(workflow_name: str, run_id: str, node_id: str, payload: str | None, no_diff: bool):
    """Re-run a single node using saved input from a previous evaluation.

    Loads the evaluation file for RUN_ID, extracts the input that NODE_ID
    received, and re-executes the node with its current code. Useful for
    iterating on a fix without re-running the entire workflow.
    """
    init_db()

    # 1. Load evaluation
    eval_path = _cwd_workflows() / workflow_name / "evaluations" / f"{run_id}.json"
    if not eval_path.exists():
        click.secho(f"Evaluation not found: {eval_path}", fg="red")
        raise SystemExit(1)

    evaluation = json.loads(eval_path.read_text())

    # 2. Find the target node in the evaluation
    node_eval = None
    for entry in evaluation["nodes"]:
        if entry["node_id"] == node_id:
            node_eval = entry
            break

    if node_eval is None:
        available = [e["node_id"] for e in evaluation["nodes"]]
        click.secho(f"Node '{node_id}' not found in evaluation. Available: {', '.join(available)}", fg="red")
        raise SystemExit(1)

    # 3. Load workflow classes and find the matching node
    registry = load_workflow_classes(workflow_name)
    target_cls = None
    for cls in registry.values():
        if cls.node_id == node_id:
            target_cls = cls
            break

    if target_cls is None:
        click.secho(f"Node '{node_id}' no longer exists in workflow code.", fg="red")
        raise SystemExit(1)

    # 4. Determine input payload
    if payload is not None:
        try:
            input_payload = json.loads(payload)
        except json.JSONDecodeError as e:
            click.secho(f"Invalid JSON payload: {e}", fg="red")
            raise SystemExit(1)
        click.echo(f"[choola] Using custom payload override")
    else:
        input_payload = node_eval["input"] or {}
        click.echo(f"[choola] Using saved input from evaluation {run_id}")

    # 5. Execute
    context = {
        "workflow": workflow_name,
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    click.echo(f"[choola] Replaying node: {target_cls.name} ({node_id})")
    click.echo(f"[choola] Input: {json.dumps(input_payload, default=str)}\n")

    async def _replay():
        instance = target_cls()
        instance._db_get_global = get_global_async
        instance._db_set_global = set_global_async
        instance._db_get_credential = get_credential_async
        instance._db_query = functools.partial(workflow_db_query_async, workflow_name)
        instance._db_execute = functools.partial(workflow_db_execute_async, workflow_name)
        instance._vector_add = functools.partial(workflow_vector_add_async, workflow_name)
        instance._vector_query = functools.partial(workflow_vector_query_async, workflow_name)
        instance._vector_get = functools.partial(workflow_vector_get_async, workflow_name)
        instance._vector_delete = functools.partial(workflow_vector_delete_async, workflow_name)
        instance._vector_count = functools.partial(workflow_vector_count_async, workflow_name)
        return await instance.execute(input_payload, context)

    try:
        result = asyncio.run(_replay())
        click.secho(f"  COMPLETED  {target_cls.name}", fg="green")
        click.echo(f"\n[choola] Output:")
        click.echo(json.dumps(result, indent=2, default=str))
    except Exception as exc:
        tb = traceback.format_exc()
        click.secho(f"  ERROR  {target_cls.name}: {exc}", fg="red")
        click.echo(f"\n{tb}")
        raise SystemExit(1)

    # 6. Diff against saved output
    saved_output = node_eval.get("output")
    if saved_output is not None and not no_diff:
        click.echo(f"\n[choola] Diff (saved vs new):")
        added = set(result.keys()) - set(saved_output.keys())
        removed = set(saved_output.keys()) - set(result.keys())
        changed = {
            k for k in set(result.keys()) & set(saved_output.keys())
            if result[k] != saved_output[k]
        }
        if not added and not removed and not changed:
            click.secho("  No changes — output matches saved evaluation.", fg="green")
        else:
            for k in sorted(changed):
                click.echo(f"  ~ {k}: {json.dumps(saved_output[k], default=str)} -> {json.dumps(result[k], default=str)}")
            for k in sorted(added):
                click.secho(f"  + {k}: {json.dumps(result[k], default=str)}", fg="green")
            for k in sorted(removed):
                click.secho(f"  - {k}: {json.dumps(saved_output[k], default=str)}", fg="red")


if __name__ == "__main__":
    main()
