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
    rows = conn.execute(
        "SELECT status, node_id FROM run_logs ORDER BY rowid"
    ).fetchall()
    conn.close()
    # The engine writes one row at RUNNING and another at COMPLETED.
    statuses = [r["status"] for r in rows]
    assert statuses == ["RUNNING", "COMPLETED"]
    assert all(r["node_id"] == "only" for r in rows)


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


# ---------------------------------------------------------------------------
# Router core node
# ---------------------------------------------------------------------------


_ROUTER_WORKFLOW = {
    "start.py": """
        from choola.core.base_node import BaseNode
        class Start(BaseNode):
            node_id = "start"
            next_nodes = ["route"]
            async def execute(self, payload, context):
                payload["bank"] = payload.get("bank", "chase")
                return payload
    """,
    "route.py": """
        from choola.core.nodes.router import Router
        class Route(Router):
            node_id = "route"
            next_nodes = ["chase_parser", "wf_parser", "generic_parser"]
            fields = [
                {"name": "match_key", "type": "string", "default": "bank"},
                {"name": "branches", "type": "json", "default": {
                    "chase": "chase_parser",
                    "wells_fargo": "wf_parser",
                }},
                {"name": "default", "type": "string", "default": "generic_parser"},
            ]
    """,
    "chase.py": """
        from choola.core.base_node import BaseNode
        class Chase(BaseNode):
            node_id = "chase_parser"
            next_nodes = ["normalize"]
            async def execute(self, payload, context):
                payload["parsed_by"] = "chase"
                return payload
    """,
    "wf.py": """
        from choola.core.base_node import BaseNode
        class WF(BaseNode):
            node_id = "wf_parser"
            next_nodes = ["normalize"]
            async def execute(self, payload, context):
                payload["parsed_by"] = "wf"
                return payload
    """,
    "generic.py": """
        from choola.core.base_node import BaseNode
        class Generic(BaseNode):
            node_id = "generic_parser"
            next_nodes = ["normalize"]
            async def execute(self, payload, context):
                payload["parsed_by"] = "generic"
                return payload
    """,
    "normalize.py": """
        from choola.core.base_node import BaseNode
        class Normalize(BaseNode):
            node_id = "normalize"
            next_nodes = []
            async def execute(self, payload, context):
                payload["normalized"] = True
                return payload
    """,
}


async def test_router_value_match_activates_one_branch(tmp_cwd: Path):
    _write_workflow(tmp_cwd, "router_match", _ROUTER_WORKFLOW)
    result = await cli.execute_workflow("router_match", {"bank": "chase"})
    assert result["parsed_by"] == "chase"
    assert result["router_matched"] == "chase"
    assert result["normalized"] is True
    # __active_branches__ is popped by the engine before downstream nodes.
    assert "__active_branches__" not in result


async def test_router_default_fallback(tmp_cwd: Path):
    _write_workflow(tmp_cwd, "router_default", _ROUTER_WORKFLOW)
    result = await cli.execute_workflow("router_default", {"bank": "barclays"})
    assert result["parsed_by"] == "generic"
    assert result["router_matched"] == "__default__"
    assert result["normalized"] is True


async def test_router_no_match_no_default_skips_all(tmp_cwd: Path):
    # Same workflow but the router has no default.
    workflow = {**_ROUTER_WORKFLOW}
    workflow["route.py"] = """
        from choola.core.nodes.router import Router
        class Route(Router):
            node_id = "route"
            next_nodes = ["chase_parser", "wf_parser", "generic_parser"]
            fields = [
                {"name": "match_key", "type": "string", "default": "bank"},
                {"name": "branches", "type": "json", "default": {
                    "chase": "chase_parser",
                    "wells_fargo": "wf_parser",
                }},
                {"name": "default", "type": "string", "default": ""},
            ]
    """
    _write_workflow(tmp_cwd, "router_skip_all", workflow)
    result = await cli.execute_workflow("router_skip_all", {"bank": "barclays"})
    # All branches were skipped, including normalize (every parent is dead).
    assert result.get("parsed_by") is None
    assert result.get("normalized") is None
    # Router itself ran and emitted router_matched=None.
    assert result.get("router_matched") is None


async def test_router_missing_match_key_raises(tmp_cwd: Path):
    workflow = {
        "start.py": """
            from choola.core.base_node import BaseNode
            class Start(BaseNode):
                node_id = "start"
                next_nodes = ["route"]
                async def execute(self, payload, context):
                    return payload
        """,
        "route.py": """
            from choola.core.nodes.router import Router
            class Route(Router):
                node_id = "route"
                next_nodes = ["sink"]
                fields = [
                    {"name": "match_key", "type": "string", "default": ""},
                    {"name": "branches", "type": "json", "default": {}},
                    {"name": "default", "type": "string", "default": ""},
                ]
        """,
        "sink.py": """
            from choola.core.base_node import BaseNode
            class Sink(BaseNode):
                node_id = "sink"
                next_nodes = []
                async def execute(self, payload, context):
                    return payload
        """,
    }
    _write_workflow(tmp_cwd, "router_missing_key", workflow)
    with pytest.raises(ValueError, match="match_key is required"):
        await cli.execute_workflow("router_missing_key", {})


async def test_router_target_not_in_next_nodes_raises(tmp_cwd: Path):
    workflow = {
        "start.py": """
            from choola.core.base_node import BaseNode
            class Start(BaseNode):
                node_id = "start"
                next_nodes = ["route"]
                async def execute(self, payload, context):
                    payload["bank"] = "chase"
                    return payload
        """,
        "route.py": """
            from choola.core.nodes.router import Router
            class Route(Router):
                node_id = "route"
                # Wrapper forgot to add "chase_parser" to next_nodes.
                next_nodes = ["other"]
                fields = [
                    {"name": "match_key", "type": "string", "default": "bank"},
                    {"name": "branches", "type": "json", "default": {"chase": "chase_parser"}},
                    {"name": "default", "type": "string", "default": ""},
                ]
        """,
        "other.py": """
            from choola.core.base_node import BaseNode
            class Other(BaseNode):
                node_id = "other"
                next_nodes = []
                async def execute(self, payload, context):
                    return payload
        """,
    }
    _write_workflow(tmp_cwd, "router_bad_target", workflow)
    with pytest.raises(ValueError, match="not in next_nodes"):
        await cli.execute_workflow("router_bad_target", {})


# ---------------------------------------------------------------------------
# Concurrent execution + fail-fast cancellation
# ---------------------------------------------------------------------------


async def test_execute_workflow_runs_independent_branches_in_parallel(tmp_cwd: Path):
    """Two siblings that each sleep 0.5s should finish in ~0.5s wall clock, not 1.0s."""
    _write_workflow(
        tmp_cwd,
        "parallel",
        {
            "start.py": """
                from choola.core.base_node import BaseNode
                class Start(BaseNode):
                    node_id = "start"
                    next_nodes = ["left", "right"]
                    async def execute(self, payload, context):
                        return payload
            """,
            "left.py": """
                import asyncio
                from choola.core.base_node import BaseNode
                class Left(BaseNode):
                    node_id = "left"
                    next_nodes = ["merge"]
                    async def execute(self, payload, context):
                        await asyncio.sleep(0.5)
                        payload["left_done"] = True
                        return payload
            """,
            "right.py": """
                import asyncio
                from choola.core.base_node import BaseNode
                class Right(BaseNode):
                    node_id = "right"
                    next_nodes = ["merge"]
                    async def execute(self, payload, context):
                        await asyncio.sleep(0.5)
                        payload["right_done"] = True
                        return payload
            """,
            "merge.py": """
                from choola.core.base_node import BaseNode
                class Merge(BaseNode):
                    node_id = "merge"
                    next_nodes = []
                    async def execute(self, payload, context):
                        return payload
            """,
        },
    )

    import time
    t0 = time.perf_counter()
    result = await cli.execute_workflow("parallel", {})
    elapsed = time.perf_counter() - t0

    assert result["left_done"] is True
    assert result["right_done"] is True
    # Sequential would be ~1.0s+; parallel is ~0.5s plus scheduler overhead.
    assert elapsed < 0.85, f"Expected parallel execution under 0.85s, got {elapsed:.2f}s"


async def test_failing_node_cancels_in_flight_siblings(tmp_cwd: Path):
    _write_workflow(
        tmp_cwd,
        "fail_fast",
        {
            "start.py": """
                from choola.core.base_node import BaseNode
                class Start(BaseNode):
                    node_id = "start"
                    next_nodes = ["slow", "fast_fail"]
                    async def execute(self, payload, context):
                        return payload
            """,
            "slow.py": """
                import asyncio
                from choola.core.base_node import BaseNode
                class Slow(BaseNode):
                    node_id = "slow"
                    next_nodes = []
                    async def execute(self, payload, context):
                        await asyncio.sleep(2.0)
                        payload["slow_done"] = True
                        return payload
            """,
            "fast_fail.py": """
                from choola.core.base_node import BaseNode
                class FastFail(BaseNode):
                    node_id = "fast_fail"
                    next_nodes = []
                    async def execute(self, payload, context):
                        raise RuntimeError("boom")
            """,
        },
    )

    import time
    t0 = time.perf_counter()
    with pytest.raises(RuntimeError, match="boom"):
        await cli.execute_workflow("fail_fast", {})
    elapsed = time.perf_counter() - t0

    # Must fail fast — well under the 2s the slow branch would have taken.
    assert elapsed < 0.5, f"Expected fast-fail under 0.5s, got {elapsed:.2f}s"

    # Evaluation should record `slow` as ERROR with the cancel message.
    import json
    eval_files = list((tmp_cwd / "workflows" / "fail_fast" / "evaluations").glob("*.json"))
    assert len(eval_files) == 1
    parsed = json.loads(eval_files[0].read_text())
    slow_eval = next(n for n in parsed["nodes"] if n["node_id"] == "slow")
    assert slow_eval["status"] == "ERROR"
    assert "Cancelled" in (slow_eval["error"] or "")
    assert "fast_fail" in (slow_eval["error"] or "")


async def test_router_plus_parallel_only_selected_subdag_runs(tmp_cwd: Path):
    """Router picks one of two parallel sub-DAGs; selected fans out into 3 parallel nodes."""
    _write_workflow(
        tmp_cwd,
        "mixed",
        {
            "start.py": """
                from choola.core.base_node import BaseNode
                class Start(BaseNode):
                    node_id = "start"
                    next_nodes = ["route"]
                    async def execute(self, payload, context):
                        payload["mode"] = "fast"
                        return payload
            """,
            "route.py": """
                from choola.core.nodes.router import Router
                class Route(Router):
                    node_id = "route"
                    # Only the direct branch heads — fast_a fans out further on its own.
                    next_nodes = ["fast_a", "slow_a"]
                    fields = [
                        {"name": "match_key", "type": "string", "default": "mode"},
                        {"name": "branches", "type": "json", "default": {"fast": "fast_a", "slow": "slow_a"}},
                        {"name": "default", "type": "string", "default": ""},
                    ]
            """,
            # `fast_a` is the route target; it fans into fast_b and fast_c
            # which both converge into fast_merge. The merge gives the run
            # a single final payload that contains both branches' work.
            "fast_a.py": """
                import asyncio
                from choola.core.base_node import BaseNode
                class FastA(BaseNode):
                    node_id = "fast_a"
                    next_nodes = ["fast_b", "fast_c"]
                    async def execute(self, payload, context):
                        await asyncio.sleep(0.3)
                        payload["a_done"] = True
                        return payload
            """,
            "fast_b.py": """
                import asyncio
                from choola.core.base_node import BaseNode
                class FastB(BaseNode):
                    node_id = "fast_b"
                    next_nodes = ["fast_merge"]
                    async def execute(self, payload, context):
                        await asyncio.sleep(0.3)
                        payload["b_done"] = True
                        return payload
            """,
            "fast_c.py": """
                import asyncio
                from choola.core.base_node import BaseNode
                class FastC(BaseNode):
                    node_id = "fast_c"
                    next_nodes = ["fast_merge"]
                    async def execute(self, payload, context):
                        await asyncio.sleep(0.3)
                        payload["c_done"] = True
                        return payload
            """,
            "fast_merge.py": """
                from choola.core.base_node import BaseNode
                class FastMerge(BaseNode):
                    node_id = "fast_merge"
                    next_nodes = []
                    async def execute(self, payload, context):
                        # Multi-parent merge — engine shallow-merges b and c
                        # before invoking us, so both keys are present.
                        return payload
            """,
            "slow_a.py": """
                import asyncio
                from choola.core.base_node import BaseNode
                class SlowA(BaseNode):
                    node_id = "slow_a"
                    next_nodes = ["slow_merge"]
                    async def execute(self, payload, context):
                        await asyncio.sleep(5.0)  # would dominate runtime if run
                        return payload
            """,
            "slow_merge.py": """
                from choola.core.base_node import BaseNode
                class SlowMerge(BaseNode):
                    node_id = "slow_merge"
                    next_nodes = []
                    async def execute(self, payload, context):
                        return payload
            """,
        },
    )

    import time, json as _json
    t0 = time.perf_counter()
    result = await cli.execute_workflow("mixed", {})
    elapsed = time.perf_counter() - t0

    # fast_a (0.3s) then (fast_b || fast_c, ~0.3s) → ~0.6s if b/c run in parallel.
    assert elapsed < 1.0, f"Expected fast-path under 1.0s, got {elapsed:.2f}s"
    assert result["a_done"] is True
    assert result["b_done"] is True
    assert result["c_done"] is True

    # The slow sub-DAG must be SKIPPED in the evaluation, not executed.
    eval_files = list((tmp_cwd / "workflows" / "mixed" / "evaluations").glob("*.json"))
    parsed = _json.loads(eval_files[0].read_text())
    statuses = {n["node_id"]: n["status"] for n in parsed["nodes"]}
    for sk in ("slow_a", "slow_merge"):
        assert statuses[sk] == "SKIPPED", f"{sk}: expected SKIPPED, got {statuses[sk]}"
    for ok in ("fast_a", "fast_b", "fast_c", "fast_merge"):
        assert statuses[ok] == "COMPLETED"


async def test_router_routes_on_bool_via_string_keys(tmp_cwd: Path):
    """Routing on a bool payload value uses 'True'/'False' string keys."""
    workflow = {
        "start.py": """
            from choola.core.base_node import BaseNode
            class Start(BaseNode):
                node_id = "start"
                next_nodes = ["route"]
                async def execute(self, payload, context):
                    payload["duplicate"] = True
                    return payload
        """,
        "route.py": """
            from choola.core.nodes.router import Router
            class Route(Router):
                node_id = "route"
                next_nodes = ["yes_handler", "no_handler"]
                fields = [
                    {"name": "match_key", "type": "string", "default": "duplicate"},
                    {"name": "branches", "type": "json", "default": {
                        "True": "yes_handler",
                        "False": "no_handler",
                    }},
                    {"name": "default", "type": "string", "default": ""},
                ]
        """,
        "yes.py": """
            from choola.core.base_node import BaseNode
            class Yes(BaseNode):
                node_id = "yes_handler"
                next_nodes = []
                async def execute(self, payload, context):
                    payload["handled"] = "yes"
                    return payload
        """,
        "no.py": """
            from choola.core.base_node import BaseNode
            class No(BaseNode):
                node_id = "no_handler"
                next_nodes = []
                async def execute(self, payload, context):
                    payload["handled"] = "no"
                    return payload
        """,
    }
    _write_workflow(tmp_cwd, "router_bool", workflow)
    result = await cli.execute_workflow("router_bool", {})
    assert result["handled"] == "yes"
    assert result["router_matched"] == "True"
