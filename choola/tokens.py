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
tokens.py — LLM token telemetry and circuit breaking.

Nodes that call paid LLM APIs report usage via `BaseNode.report_tokens`,
which the engine routes into an in-memory tally keyed by run_id. After each
node completes, the engine calls `check_limits` to enforce two caps pulled
from the persistent `globals` table:

    max_tokens_per_run   — hard cap on a single run's prompt+completion total.
    max_tokens_per_hour  — rolling 1-hour cap across ALL runs on the host
                           (computed by summing the run_logs table).

A value of 0 or None disables the corresponding cap. When a cap is breached,
the engine raises `TokenLimitExceeded`, aborting the run.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from choola.database import DB_PATH, get_connection, get_global_sync


class TokenLimitExceeded(Exception):
    """Raised by the engine when a run exceeds a configured token cap."""


_lock = threading.Lock()
_run_tallies: dict[str, dict] = defaultdict(
    lambda: {"prompt": 0, "completion": 0, "events": []}
)


def init_run(run_id: str) -> None:
    """Initialize (or reset) the tally for a run."""
    with _lock:
        _run_tallies[run_id] = {"prompt": 0, "completion": 0, "events": []}


def report(
    run_id: str,
    node_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "",
    provider: str = "",
) -> None:
    """Record one LLM call's token usage against *run_id*."""
    with _lock:
        tally = _run_tallies.setdefault(
            run_id, {"prompt": 0, "completion": 0, "events": []}
        )
        tally["prompt"] += int(prompt_tokens or 0)
        tally["completion"] += int(completion_tokens or 0)
        tally["events"].append({
            "node_id": node_id,
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "model": model or "",
            "provider": provider or "",
        })


def get_node_tokens(run_id: str, node_id: str) -> dict | None:
    """Aggregate all LLM calls reported for *node_id* during *run_id*.

    Returns None if this node reported no usage.
    """
    with _lock:
        tally = _run_tallies.get(run_id)
        if not tally:
            return None
        events = [e for e in tally["events"] if e["node_id"] == node_id]
    if not events:
        return None
    return {
        "prompt_tokens": sum(e["prompt_tokens"] for e in events),
        "completion_tokens": sum(e["completion_tokens"] for e in events),
        "total_tokens": sum(e["prompt_tokens"] + e["completion_tokens"] for e in events),
        "events": events,
    }


def get_run_total(run_id: str) -> int:
    """Total prompt+completion tokens reported so far for *run_id*."""
    with _lock:
        tally = _run_tallies.get(run_id)
        if not tally:
            return 0
        return tally["prompt"] + tally["completion"]


def get_run_breakdown(run_id: str) -> dict:
    """Snapshot of the run's tally — totals and per-call events."""
    with _lock:
        tally = _run_tallies.get(run_id)
        if not tally:
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "events": []}
        return {
            "prompt_tokens": tally["prompt"],
            "completion_tokens": tally["completion"],
            "total_tokens": tally["prompt"] + tally["completion"],
            "events": list(tally["events"]),
        }


def clear_run(run_id: str) -> None:
    """Drop the tally for *run_id* — call after the run finishes."""
    with _lock:
        _run_tallies.pop(run_id, None)


def _rolling_hour_total(db_path: Path = DB_PATH) -> int:
    """Sum prompt+completion tokens from run_logs recorded in the last hour."""
    window_start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)), 0) "
            "AS total FROM run_logs WHERE started_at >= ?",
            (window_start,),
        ).fetchone()
    finally:
        conn.close()
    return int(row["total"]) if row is not None else 0


def check_limits(run_id: str, db_path: Path = DB_PATH) -> None:
    """Raise TokenLimitExceeded if either the per-run or rolling-hour cap is breached."""
    per_run_cap = get_global_sync("max_tokens_per_run", db_path) or 0
    per_hour_cap = get_global_sync("max_tokens_per_hour", db_path) or 0

    if per_run_cap:
        run_total = get_run_total(run_id)
        if run_total > int(per_run_cap):
            raise TokenLimitExceeded(
                f"Per-run token cap exceeded: {run_total} > {per_run_cap} "
                f"(max_tokens_per_run; set to 0 to disable)"
            )

    if per_hour_cap:
        window_total = _rolling_hour_total(db_path)
        if window_total > int(per_hour_cap):
            raise TokenLimitExceeded(
                f"Rolling 1-hour token cap exceeded: {window_total} > {per_hour_cap} "
                f"(max_tokens_per_hour; set to 0 to disable)"
            )
