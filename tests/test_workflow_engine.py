"""Tests for the workflow engine helpers in choola.cli.

Covers:
  - load_workflow_classes (dynamic import from workflows/<name>/nodes/)
  - build_workflow       (DAG from node_id / next_nodes)
  - topological_sort     (Kahn's + cycle detection)
  - execute_workflow     (end-to-end with helpers injected)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from choola import cli


# ---------------------------------------------------------------------------
# Fixtures — scaffold a minimal on-disk workflow for import tests
# ---------------------------------------------------------------------------


def _write_workflow(cwd: Path, name: str, node_files: dict[str, str]) -> Path:
    """Create workflows/<name>/nodes/*.py with the given source."""
    nodes_dir = cwd / "workflows" / name / "nodes"
    nodes_dir.mkdir(parents=True, exist_ok=True)
    (nodes_dir / "__init__.py").write_text("")
    for filename, source in node_files.items():
        (nodes_dir / filename).write_text(textwrap.dedent(source))
    return nodes_dir


# ---------------------------------------------------------------------------
# load_workflow_classes
# ---------------------------------------------------------------------------


def test_load_workflow_classes_missing_dir(tmp_cwd: Path):
    with pytest.raises(FileNotFoundError):
        cli.load_workflow_classes("does_not_exist")


def test_load_workflow_classes_discovers_basenode_subclasses(tmp_cwd: Path):
    _write_workflow(
        tmp_cwd,
        "demo",
        {
            "alpha.py": """
                from choola.core.base_node import BaseNode
                class Alpha(BaseNode):
                    node_id = "alpha"
                    next_nodes = []
                    async def execute(self, payload, context):
                        payload["alpha"] = True
                        return payload
            """,
        },
    )

    registry = cli.load_workflow_classes("demo")
    assert len(registry) == 1
    fq_name, cls = next(iter(registry.items()))
    assert fq_name.endswith(".Alpha")
    assert cls.node_id == "alpha"


def test_load_workflow_classes_skips_underscore_files(tmp_cwd: Path):
    _write_workflow(
        tmp_cwd,
        "demo",
        {
            "real.py": """
                from choola.core.base_node import BaseNode
                class Real(BaseNode):
                    node_id = "real"
                    next_nodes = []
                    async def execute(self, payload, context):
                        return payload
            """,
            "_helper.py": """
                from choola.core.base_node import BaseNode
                class Helper(BaseNode):
                    node_id = "should_not_be_loaded"
                    next_nodes = []
                    async def execute(self, payload, context):
                        return payload
            """,
        },
    )
    registry = cli.load_workflow_classes("demo")
    assert any("Real" in fq for fq in registry)
    assert not any("Helper" in fq for fq in registry)


def test_load_workflow_classes_ignores_re_exported_classes(tmp_cwd: Path):
    """A class imported into a node module but defined elsewhere shouldn't register."""
    _write_workflow(
        tmp_cwd,
        "demo",
        {
            "entry.py": """
                # Re-importing a BaseNode from the stdlib choola package must NOT
                # register it as part of this workflow.
                from choola.core.nodes.manual_trigger import ManualTrigger
                from choola.core.base_node import BaseNode
                class Entry(BaseNode):
                    node_id = "entry"
                    next_nodes = []
                    async def execute(self, payload, context):
                        return payload
            """,
        },
    )
    registry = cli.load_workflow_classes("demo")
    classes = list(registry.values())
    assert len(classes) == 1
    assert classes[0].__name__ == "Entry"


# ---------------------------------------------------------------------------
# build_workflow
# ---------------------------------------------------------------------------


def _make_cls(node_id: str, next_nodes: list[str]):
    from choola.core.base_node import BaseNode

    attrs = {
        "node_id": node_id,
        "next_nodes": next_nodes,
        "execute": lambda self, payload, context: payload,
    }
    return type(f"Node_{node_id}", (BaseNode,), attrs)


def test_build_workflow_builds_nodes_and_edges():
    registry = {
        "m.A": _make_cls("a", ["b"]),
        "m.B": _make_cls("b", []),
    }
    wf = cli.build_workflow(registry)
    ids = {n["id"] for n in wf["nodes"]}
    assert ids == {"a", "b"}
    assert wf["edges"] == [{"source": "a", "target": "b"}]


def test_build_workflow_rejects_duplicate_node_ids():
    registry = {
        "m.A1": _make_cls("same", []),
        "m.A2": _make_cls("same", []),
    }
    with pytest.raises(ValueError, match="Duplicate node_id"):
        cli.build_workflow(registry)


def test_build_workflow_rejects_dangling_next_node():
    registry = {"m.A": _make_cls("a", ["ghost"])}
    with pytest.raises(ValueError, match="doesn't exist"):
        cli.build_workflow(registry)


def test_build_workflow_rejects_empty_registry():
    with pytest.raises(ValueError, match="No nodes"):
        cli.build_workflow({})


def test_build_workflow_skips_classes_without_node_id():
    """Abstract wrappers with blank node_id must be ignored."""
    registry = {
        "m.A": _make_cls("a", []),
        "m.Abstract": _make_cls("", []),
    }
    wf = cli.build_workflow(registry)
    assert {n["id"] for n in wf["nodes"]} == {"a"}


# ---------------------------------------------------------------------------
# topological_sort
# ---------------------------------------------------------------------------


def test_topological_sort_linear_chain():
    nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
    assert cli.topological_sort(nodes, edges) == ["a", "b", "c"]


def test_topological_sort_diamond_is_consistent():
    nodes = [{"id": "root"}, {"id": "l"}, {"id": "r"}, {"id": "merge"}]
    edges = [
        {"source": "root", "target": "l"},
        {"source": "root", "target": "r"},
        {"source": "l", "target": "merge"},
        {"source": "r", "target": "merge"},
    ]
    order = cli.topological_sort(nodes, edges)
    assert order[0] == "root"
    assert order[-1] == "merge"
    assert order.index("l") < order.index("merge")
    assert order.index("r") < order.index("merge")


def test_topological_sort_detects_cycle():
    nodes = [{"id": "a"}, {"id": "b"}]
    edges = [
        {"source": "a", "target": "b"},
        {"source": "b", "target": "a"},
    ]
    with pytest.raises(ValueError, match="Cycle"):
        cli.topological_sort(nodes, edges)


def test_topological_sort_handles_isolated_nodes():
    nodes = [{"id": "a"}, {"id": "b"}]
    order = cli.topological_sort(nodes, [])
    assert set(order) == {"a", "b"}


# ---------------------------------------------------------------------------
# execute_workflow — end-to-end with helpers injected
# ---------------------------------------------------------------------------


async def test_execute_workflow_runs_two_nodes_in_order(tmp_cwd: Path):
    _write_workflow(
        tmp_cwd,
        "pipeline",
        {
            "start.py": """
                from choola.core.base_node import BaseNode
                class Start(BaseNode):
                    node_id = "start"
                    next_nodes = ["finish"]
                    async def execute(self, payload, context):
                        payload["visited"] = ["start"]
                        return payload
            """,
            "finish.py": """
                from choola.core.base_node import BaseNode
                class Finish(BaseNode):
                    node_id = "finish"
                    next_nodes = []
                    async def execute(self, payload, context):
                        payload["visited"].append("finish")
                        payload["workflow_name"] = context["workflow"]
                        return payload
            """,
        },
    )

    result = await cli.execute_workflow("pipeline", {})

    assert result["visited"] == ["start", "finish"]
    assert result["workflow_name"] == "pipeline"


async def test_execute_workflow_injects_db_helpers(tmp_cwd: Path):
    """The engine must wire up set_global/get_global so nodes can persist state."""
    _write_workflow(
        tmp_cwd,
        "stateful",
        {
            "only.py": """
                from choola.core.base_node import BaseNode
                class Only(BaseNode):
                    node_id = "only"
                    next_nodes = []
                    async def execute(self, payload, context):
                        await self.set_global("last_run", context["run_id"])
                        payload["stored"] = await self.get_global("last_run")
                        return payload
            """,
        },
    )
    result = await cli.execute_workflow("stateful", {})
    assert result["stored"] == result.get("stored")
    assert isinstance(result["stored"], str) and len(result["stored"]) == 12


async def test_execute_workflow_writes_run_log_row(tmp_cwd: Path):
    from choola import database as db

    _write_workflow(
        tmp_cwd,
        "logged",
        {
            "only.py": """
                from choola.core.base_node import BaseNode
                class Only(BaseNode):
                    node_id = "only"
                    next_nodes = []
                    async def execute(self, payload, context):
                        return {"ok": True}
            """,
        },
    )
    await cli.execute_workflow("logged", {})

    conn = db.get_connection(tmp_cwd / "choola.db")
    rows = conn.execute("SELECT status, node_id FROM run_logs").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["status"] == "COMPLETED"
    assert rows[0]["node_id"] == "only"


async def test_execute_workflow_saves_evaluation(tmp_cwd: Path):
    _write_workflow(
        tmp_cwd,
        "evaluated",
        {
            "only.py": """
                from choola.core.base_node import BaseNode
                class Only(BaseNode):
                    node_id = "only"
                    next_nodes = []
                    async def execute(self, payload, context):
                        return payload
            """,
        },
    )
    await cli.execute_workflow("evaluated", {"seed": 1})

    eval_dir = tmp_cwd / "workflows" / "evaluated" / "evaluations"
    files = list(eval_dir.glob("*.json"))
    assert len(files) == 1
    import json
    parsed = json.loads(files[0].read_text())
    assert parsed["workflow"] == "evaluated"
    assert parsed["status"] == "COMPLETED"
    assert parsed["initial_payload"] == {"seed": 1}
