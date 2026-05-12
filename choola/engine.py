# Copyright 2026 Ivan Grosny
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""
engine.py — Choola's workflow execution engine.

Single source of truth used by both the Flask server (real-time SSE) and the
CLI's `choola run` (headless). Callers build the DAG themselves (server pulls
from its module-global node registry; CLI imports from one workflow's nodes/
directory) and pass a `{nodes, edges}` dict in.

The engine handles:

* Topological sort + cycle detection.
* Dynamic ready-queue scheduling — every node fires the moment its parents
  finish, so independent branches run concurrently. Linear chains keep their
  byte-identical sequential behaviour because the ready set stays size 1.
* Per-branch deep-copy isolation, multi-parent shallow merge, and per-parent
  outputs exposed in ``context["parent_outputs"]``.
* Conditional routing via the ``__active_branches__`` payload key.
* Fail-fast cancellation: on the first uncaught exception, every in-flight
  sibling task is cancelled (with an ERROR run-log row tagged "Cancelled")
  and the run aborts with the failing traceback.
* Token-cap circuit breaking, evaluation save, and structured ``emit`` events
  (``node_status`` / ``run_complete``) for SSE pumps and CLI loggers.
"""

from __future__ import annotations

import asyncio
import functools
import traceback
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable

from choola import tokens as token_tracker
from choola.database import (
    get_credential_async,
    get_global_async,
    insert_run_log,
    set_global_async,
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
from choola.tokens import TokenLimitExceeded


EmitFn = Callable[[str, dict], None]


def _noop_emit(event: str, data: dict) -> None:
    """Default `emit` — silently swallows events."""


# ------------------------------------------------------------------
# Graph helpers
# ------------------------------------------------------------------
def topological_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Return node IDs in execution order (Kahn's algorithm). Raises on cycle."""
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


def _mark_skipped(
    inactive_starts: set[str],
    adjacency: dict[str, list[str]],
    parents: dict[str, list[str]],
    skipped: set[str],
    router_id: str,
) -> None:
    """BFS from *inactive_starts*, skipping nodes reachable only via dead paths.

    A merge-point node is skipped only when ALL of its parents are either
    already skipped or are inactive outputs of this router.
    """
    candidates: deque[str] = deque(inactive_starts)
    while candidates:
        nid = candidates.popleft()
        if nid in skipped:
            continue
        all_parents_dead = all(
            p in skipped or (p == router_id and nid in inactive_starts)
            for p in parents.get(nid, [])
        )
        if all_parents_dead:
            skipped.add(nid)
            for child in adjacency.get(nid, []):
                if child not in skipped:
                    candidates.append(child)


def _inject_helpers(instance: Any, workflow_name: str, run_id: str) -> None:
    """Wire DB / credential / vector / token-reporter callbacks onto a node instance."""
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
    instance._token_reporter = functools.partial(token_tracker.report, run_id)


# ------------------------------------------------------------------
# Execution — dynamic ready-queue scheduler
# ------------------------------------------------------------------
async def execute_dag(
    workflow_name: str,
    wf: dict,
    payload: dict[str, Any],
    run_id: str,
    *,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    """Execute a prepared ``{nodes, edges}`` DAG.

    Returns ``{"status", "payload", "run_id", "evaluation_path", "tokens"}``.
    Raises any exception thrown by a node — after cancelling in-flight
    siblings and writing the ERROR evaluation.
    """
    emit = emit or _noop_emit
    sorted_ids = topological_sort(wf["nodes"], wf["edges"])
    topo_index = {nid: i for i, nid in enumerate(sorted_ids)}
    node_lookup = {n["id"]: n for n in wf["nodes"]}

    parents: dict[str, list[str]] = defaultdict(list)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in wf["edges"]:
        parents[edge["target"]].append(edge["source"])
        adjacency[edge["source"]].append(edge["target"])

    context: dict[str, Any] = {
        "workflow": workflow_name,
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    outputs: dict[str, dict[str, Any]] = {}
    skipped: set[str] = set()
    done: set[str] = set()
    running: dict[str, dict[str, Any]] = {}  # node_id -> spawn-time bookkeeping
    initial_payload = capture_payload(payload)
    node_evals: list[dict] = []
    token_tracker.init_run(run_id)

    # ------------------------------------------------------------------
    # Scheduler helpers (closures over the state above)
    # ------------------------------------------------------------------
    def _ready_now() -> list[str]:
        """Topo-ordered list of nodes whose parents have all finished/skipped."""
        ready = []
        for nid in sorted_ids:
            if nid in done or nid in skipped or nid in running:
                continue
            if all(p in done or p in skipped for p in parents.get(nid, [])):
                ready.append(nid)
        return ready

    def _assemble_input(nid: str) -> tuple[dict, list[str]]:
        """Compute a node's input payload and the list of its active parents."""
        node_parents = parents.get(nid, [])
        active_parents = [p for p in node_parents if p not in skipped]
        if not node_parents:
            return capture_payload(payload), active_parents
        if len(active_parents) == 1:
            return capture_payload(outputs[active_parents[0]]), active_parents
        merged: dict[str, Any] = {}
        # Stable merge order: topological.
        for pid in sorted_ids:
            if pid in active_parents:
                merged.update(capture_payload(outputs[pid]))
        return merged, active_parents

    def _spawn(nid: str) -> None:
        """Create the asyncio.Task for a single node and record its bookkeeping."""
        node_entry = node_lookup[nid]
        node_type = node_entry["type"]
        cls = node_entry["cls"]

        node_input, active_parents = _assemble_input(nid)
        # Per-task context snapshot so concurrent tasks can't trample each
        # other's parent_outputs (shallow copy + fresh parent_outputs dict).
        task_context = dict(context)
        task_context["parent_outputs"] = {
            pid: capture_payload(outputs[pid]) for pid in active_parents
        }

        started_at = datetime.now(timezone.utc).isoformat()
        payload_before = capture_payload(node_input)

        async def _body() -> tuple[dict, list[str]]:
            emit("node_status", {"node_id": nid, "status": "RUNNING", "payload": node_input})
            insert_run_log(
                run_id, workflow_name, nid, node_type, "RUNNING",
                payload_in=payload_before, started_at=started_at,
            )
            instance = cls()
            _inject_helpers(instance, workflow_name, run_id)
            result = await instance.execute(node_input, task_context)
            return result, list(cls.next_nodes)

        task = asyncio.create_task(_body(), name=f"node:{nid}")
        running[nid] = {
            "task": task,
            "node_type": node_type,
            "cls": cls,
            "payload_before": payload_before,
            "started_at": started_at,
        }

    def _emit_skipped(sk_nid: str) -> None:
        """Emit + persist a SKIPPED record for one node."""
        sk_type = node_lookup[sk_nid]["type"]
        sk_now = datetime.now(timezone.utc).isoformat()
        emit("node_status", {"node_id": sk_nid, "status": "SKIPPED"})
        insert_run_log(
            run_id, workflow_name, sk_nid, sk_type, "SKIPPED",
            started_at=sk_now, finished_at=sk_now,
        )
        node_evals.append(
            make_node_eval(sk_nid, sk_type, "SKIPPED", sk_now, sk_now, {})
        )

    async def _abort(failing_nid: str, failing_exc: BaseException) -> None:
        """Cancel every in-flight sibling, then write ERROR rows for them."""
        siblings = [(n, e) for n, e in running.items() if n != failing_nid]
        for _nid, entry in siblings:
            if not entry["task"].done():
                entry["task"].cancel()
        if siblings:
            await asyncio.gather(
                *[entry["task"] for _, entry in siblings], return_exceptions=True
            )
        cancel_msg = (
            f"Cancelled: sibling node '{failing_nid}' failed with "
            f"{type(failing_exc).__name__}: {failing_exc}"
        )
        for nid, entry in siblings:
            finished_now = datetime.now(timezone.utc).isoformat()
            node_tokens = token_tracker.get_node_tokens(run_id, nid)
            prompt_t = node_tokens["prompt_tokens"] if node_tokens else 0
            completion_t = node_tokens["completion_tokens"] if node_tokens else 0
            emit("node_status", {"node_id": nid, "status": "ERROR", "error": cancel_msg})
            insert_run_log(
                run_id, workflow_name, nid, entry["node_type"], "ERROR",
                payload_in=entry["payload_before"], error=cancel_msg,
                started_at=entry["started_at"], finished_at=finished_now,
                prompt_tokens=prompt_t, completion_tokens=completion_t,
            )
            node_evals.append(make_node_eval(
                nid, entry["node_type"], "ERROR",
                entry["started_at"], finished_now,
                entry["payload_before"], error=cancel_msg, tokens=node_tokens,
            ))
            # Drop the entry — _abort is the last code path that needs it.
            running.pop(nid, None)

    def _save_error_evaluation(exc: BaseException, error_text: str) -> None:
        node_evals.sort(key=lambda e: e.get("started_at") or "")
        evaluation = build_evaluation(
            run_id, workflow_name, context["started_at"], initial_payload,
            node_evals, "ERROR", error=error_text,
            tokens=token_tracker.get_run_breakdown(run_id),
        )
        save_evaluation(workflow_name, evaluation)
        emit("run_complete", {"status": "ERROR", "error": str(exc)})
        token_tracker.clear_run(run_id)

    # ------------------------------------------------------------------
    # Main scheduler loop
    # ------------------------------------------------------------------
    ready = _ready_now()
    while ready or running:
        for nid in ready:
            _spawn(nid)
        ready = []

        if not running:
            break

        tasks = [entry["task"] for entry in running.values()]
        done_tasks, _pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )

        for task in done_tasks:
            # Reverse-lookup the node_id for this finished task.
            nid = next(n for n, e in running.items() if e["task"] is task)
            entry = running.pop(nid)
            cls = entry["cls"]
            node_type = entry["node_type"]
            payload_before = entry["payload_before"]
            started_at = entry["started_at"]

            # Did the task throw?
            if task.cancelled():
                # Shouldn't happen — only _abort cancels, and _abort removes
                # the entry from `running`. Defensive: treat as a fatal exc.
                cancel_exc = asyncio.CancelledError()
                await _abort(nid, cancel_exc)
                _save_error_evaluation(cancel_exc, "Task cancelled unexpectedly")
                raise cancel_exc

            exc = task.exception()
            if exc is not None:
                finished = datetime.now(timezone.utc).isoformat()
                tb = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
                node_tokens = token_tracker.get_node_tokens(run_id, nid)
                prompt_t = node_tokens["prompt_tokens"] if node_tokens else 0
                completion_t = node_tokens["completion_tokens"] if node_tokens else 0
                emit("node_status", {"node_id": nid, "status": "ERROR", "error": str(exc)})
                insert_run_log(
                    run_id, workflow_name, nid, node_type, "ERROR",
                    payload_in=payload_before, error=tb,
                    started_at=started_at, finished_at=finished,
                    prompt_tokens=prompt_t, completion_tokens=completion_t,
                )
                node_evals.append(make_node_eval(
                    nid, node_type, "ERROR", started_at, finished,
                    payload_before, error=tb, tokens=node_tokens,
                ))
                await _abort(nid, exc)
                _save_error_evaluation(exc, tb)
                raise exc

            # Success.
            result, cls_next_nodes = task.result()
            active_branches = result.pop("__active_branches__", None)
            outputs[nid] = result
            done.add(nid)

            # Propagate conditional skips, eagerly emitting SKIPPED records
            # for any descendants that just became unreachable. Topo order
            # keeps the SSE/event stream readable.
            if active_branches is not None:
                inactive = set(cls_next_nodes) - set(active_branches)
                before_skipped = set(skipped)
                if inactive:
                    _mark_skipped(inactive, adjacency, parents, skipped, nid)
                newly_skipped = skipped - before_skipped
                for sk_nid in sorted(newly_skipped, key=lambda x: topo_index[x]):
                    _emit_skipped(sk_nid)

            finished = datetime.now(timezone.utc).isoformat()
            node_tokens = token_tracker.get_node_tokens(run_id, nid)
            prompt_t = node_tokens["prompt_tokens"] if node_tokens else 0
            completion_t = node_tokens["completion_tokens"] if node_tokens else 0
            emit("node_status", {"node_id": nid, "status": "COMPLETED", "payload": result})
            insert_run_log(
                run_id, workflow_name, nid, node_type, "COMPLETED",
                payload_in=payload_before, payload_out=result,
                started_at=started_at, finished_at=finished,
                prompt_tokens=prompt_t, completion_tokens=completion_t,
            )
            node_evals.append(make_node_eval(
                nid, node_type, "COMPLETED", started_at, finished,
                payload_before, capture_payload(result), tokens=node_tokens,
            ))

            # Circuit breaker — checked after every node completion. If any
            # in-flight node's reported tokens push us over the cap, this is
            # the next caller that trips it.
            try:
                token_tracker.check_limits(run_id)
            except TokenLimitExceeded as cap_exc:
                tb = str(cap_exc)
                await _abort(nid, cap_exc)
                _save_error_evaluation(cap_exc, tb)
                raise

        ready = _ready_now()

    # Sort completion-order evals into chronological (started_at) order so
    # the evaluation JSON reads top-to-bottom even after parallel execution.
    node_evals.sort(key=lambda e: e.get("started_at") or "")

    # Final payload = the last non-skipped node in topo order. Topo order is
    # independent of execution order, so this stays deterministic.
    final_payload = None
    for nid in reversed(sorted_ids):
        if nid not in skipped and nid in outputs:
            final_payload = outputs[nid]
            break

    run_tokens = token_tracker.get_run_breakdown(run_id)
    evaluation = build_evaluation(
        run_id, workflow_name, context["started_at"], initial_payload,
        node_evals, "COMPLETED", final_payload, tokens=run_tokens,
    )
    eval_path = save_evaluation(workflow_name, evaluation)
    emit("run_complete", {"status": "COMPLETED", "payload": final_payload})
    token_tracker.clear_run(run_id)
    return {
        "status": "COMPLETED",
        "payload": final_payload,
        "run_id": run_id,
        "evaluation_path": str(eval_path),
        "tokens": run_tokens,
    }


def make_run_id() -> str:
    return uuid.uuid4().hex[:12]
