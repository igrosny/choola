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
    choola explain <name>    Print each node's title and description in DAG order
    choola nodes [name]      List available node types
    choola dream             Train XGBoost classifiers for every LLML node
    choola credential <name> Store a credential interactively
    choola credentials       List stored credentials (names + providers, no values)
"""

from __future__ import annotations

import asyncio
import functools
import importlib
import importlib.util
import json
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from choola import engine
from choola.core.base_node import BaseNode
from choola.database import (
    get_credential_async,
    get_global_async,
    init_db,
    list_credentials,
    set_global_async,
    upsert_credential,
    workflow_db_execute_async,
    workflow_db_query_async,
    workflow_vector_add_async,
    workflow_vector_count_async,
    workflow_vector_delete_async,
    workflow_vector_get_async,
    workflow_vector_query_async,
)
from choola.engine import topological_sort  # re-exported for tests

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
    """Execute a workflow headlessly via the shared engine.

    Loads node classes from ``workflows/<name>/nodes/`` in the current working
    directory, builds the DAG, and delegates the run to
    :func:`choola.engine.execute_dag` with a click-based emit callback for
    per-node start/end output.
    """
    registry = load_workflow_classes(workflow_name)
    wf = build_workflow(registry)
    sorted_ids = topological_sort(wf["nodes"], wf["edges"])

    run_id = engine.make_run_id()
    click.echo(f"[choola] Executing workflow: {workflow_name}  (run_id={run_id})")
    click.echo(f"[choola] Nodes in order: {sorted_ids}\n")

    started_at: dict[str, str] = {}

    def cli_emit(event: str, data: dict) -> None:
        if event != "node_status":
            return
        node_id = data.get("node_id", "")
        status = data.get("status")
        if status == "RUNNING":
            started_at[node_id] = datetime.now(timezone.utc).isoformat()
            click.echo(f"  RUNNING    {node_id}")
        elif status == "COMPLETED":
            now = datetime.now(timezone.utc).isoformat()
            elapsed = _elapsed_str(started_at.get(node_id, now), now)
            click.secho(f"  COMPLETED  {node_id}  {elapsed}", fg="green")
        elif status == "ERROR":
            err = data.get("error", "")
            click.secho(f"  ERROR      {node_id}: {err}", fg="red")
        elif status == "SKIPPED":
            click.secho(f"  SKIPPED    {node_id}", fg="yellow")

    result = await engine.execute_dag(workflow_name, wf, payload, run_id, emit=cli_emit)

    final_payload = result["payload"] or {}
    eval_path = result["evaluation_path"]
    run_tokens = result["tokens"]

    click.echo("\n[choola] Workflow completed. Final payload:")
    click.echo(json.dumps(final_payload, indent=2, default=str))
    click.echo(f"[choola] Evaluation saved: {eval_path}")
    if run_tokens["total_tokens"]:
        click.echo(
            f"[choola] Tokens used: {run_tokens['total_tokens']} "
            f"(prompt={run_tokens['prompt_tokens']}, completion={run_tokens['completion_tokens']})"
        )
    return final_payload


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

    # Copy bundled llms.txt into the project
    bundled_llms = _PKG_ROOT / "llms.txt"
    dest_llms = project_dir / "llms.txt"
    if bundled_llms.exists():
        shutil.copy2(bundled_llms, dest_llms)
        click.secho(f"  Created  llms.txt", fg="green")
    else:
        click.secho("  Warning: bundled llms.txt not found — skipping", fg="yellow")

    # Copy bundled _claude/ template into the project as .claude/
    bundled_claude = _PKG_ROOT / "_claude"
    dest_claude = project_dir / ".claude"
    if bundled_claude.exists():
        if dest_claude.exists():
            click.secho(f"  Skipped  .claude/ (already exists)", fg="yellow")
        else:
            shutil.copytree(bundled_claude, dest_claude)
            click.secho(f"  Created  .claude/", fg="green")
    else:
        click.secho("  Warning: bundled _claude/ template not found — skipping", fg="yellow")

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
@click.argument("workflow_name")
def explain(workflow_name: str):
    """Print each node's title and description in DAG (topological) order."""
    try:
        registry = load_workflow_classes(workflow_name)
        wf = build_workflow(registry)
        sorted_ids = topological_sort(wf["nodes"], wf["edges"])
    except (FileNotFoundError, ValueError) as e:
        click.secho(str(e), fg="red")
        raise SystemExit(1)

    node_lookup = {n["id"]: n for n in wf["nodes"]}
    click.secho(f"Workflow: {workflow_name}", bold=True)
    for node_id in sorted_ids:
        cls = node_lookup[node_id]["cls"]
        click.echo()
        click.secho(f"  {cls.name}  ", fg="cyan", nl=False)
        click.secho(f"({node_id})", fg="white")
        click.echo(f"    {cls.description}")


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
        import choola.core.nodes.gmail as _gmail
        import choola.core.nodes.google_sheets as _gs
        import choola.core.nodes.router as _router
        seen = set()
        skip = {BaseNode, Trigger}
        for mod in (_ft, _wt, _llm, _mt, _http, _db, _vdb, _gmail, _gs, _router):
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
    ("gemini", "Gemini"),
    ("google", "Google (OAuth2)"),
]

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

    if provider == "google":
        # Google's OOB flow (urn:ietf:wg:oauth:2.0:oob) was retired in 2022,
        # so the CLI can't complete OAuth2 on its own. The server has a
        # working browser flow with a real redirect URI — point the user there.
        click.echo()
        click.secho("Google OAuth2 must be completed in the browser.", fg="yellow")
        click.echo("  1. Start the server:    choola start")
        click.echo("  2. Open:                http://localhost:5000")
        click.echo("  3. Settings → Credentials → Add → Google (OAuth2)")
        click.echo(f"     Use the name: {name}")
        raise SystemExit(0)

    value = click.prompt("API key (hidden)", hide_input=True)

    upsert_credential(name, provider, value)
    click.secho(f"Credential '{name}' saved (provider: {provider}).", fg="green")


@main.command("credentials")
def credentials_list():
    """List stored credentials (names + providers only — values never shown)."""
    init_db()
    rows = list_credentials()
    if not rows:
        click.echo("No credentials stored. Use `choola credential <name>` to add one.")
        return
    for row in rows:
        click.echo(f"  {row['name']:<30}  [{row['provider']}]")


@main.command()
@click.option("--workflow", "workflow_filter", default=None,
              help="Only train nodes in this workflow (default: all workflows).")
@click.option("--min-examples", default=10, type=int,
              help="Skip nodes with fewer 'source=llm' rows.")
def dream(workflow_filter: str | None, min_examples: int):
    """Train XGBoost classifiers for every LLML node in every workflow.

    Walks workflows/, finds nodes that subclass the LLML core node, reads
    their SQLite history (rows where source='llm' only — never xgboost
    predictions), pulls their embeddings from the workflow's ChromaDB, and
    writes a per-node model to workflows/<wf>/files/llml/<node_id>/.
    """
    from choola._dream import discover_llml_nodes, train_llml_node

    init_db()
    workflows_dir = _cwd_workflows()
    if not workflows_dir.exists():
        click.secho("No workflows/ directory found.", fg="red")
        raise SystemExit(1)

    if workflow_filter:
        targets = [workflow_filter]
    else:
        targets = sorted(
            d.name for d in workflows_dir.iterdir()
            if d.is_dir() and (d / "nodes").exists()
        )
    if not targets:
        click.echo("No workflows found.")
        return

    click.echo(f"[choola dream] Scanning {len(targets)} workflow(s) for LLML nodes...\n")
    total_trained = 0
    total_skipped = 0

    for wf in targets:
        try:
            node_classes = discover_llml_nodes(wf)
        except FileNotFoundError as exc:
            click.secho(f"  {wf}: {exc}", fg="yellow")
            continue
        except Exception as exc:
            click.secho(f"  {wf}: failed to load nodes — {exc}", fg="yellow")
            continue

        if not node_classes:
            continue

        click.secho(wf, bold=True)
        for cls in node_classes:
            node_id = cls.node_id
            if not node_id:
                click.secho(
                    f"  {cls.__name__}: skipped (no node_id)", fg="yellow"
                )
                total_skipped += 1
                continue
            try:
                result = train_llml_node(wf, node_id, min_examples=min_examples)
            except Exception as exc:
                click.secho(f"  {node_id}: ERROR — {exc}", fg="red")
                total_skipped += 1
                continue

            status = result.get("status")
            if status == "trained":
                click.secho(
                    f"  {node_id}: trained on {result['n_examples']} examples, "
                    f"{result['n_classes']} classes, "
                    f"train_acc={result['train_accuracy']:.3f}",
                    fg="green",
                )
                total_trained += 1
            elif status == "skipped_too_few":
                click.echo(
                    f"  {node_id}: skipped — only {result['n_examples']} "
                    f"LLM-sourced rows (min {min_examples})"
                )
                total_skipped += 1
            elif status == "skipped_single_class":
                click.echo(
                    f"  {node_id}: skipped — only {result['n_classes']} "
                    "distinct label so far"
                )
                total_skipped += 1
            elif status == "skipped_no_embeddings":
                click.echo(
                    f"  {node_id}: skipped — embeddings missing for all rows"
                )
                total_skipped += 1
            elif status == "skipped_no_table":
                click.echo(f"  {node_id}: skipped — no history table yet")
                total_skipped += 1
            else:
                click.echo(f"  {node_id}: {status}")
                total_skipped += 1
        click.echo()

    click.secho(
        f"[choola dream] done — trained {total_trained}, skipped {total_skipped}",
        fg="cyan",
    )


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
