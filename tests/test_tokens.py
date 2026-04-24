"""Tests for choola.tokens — LLM token telemetry and circuit breaking."""

from __future__ import annotations

from pathlib import Path

import pytest

from choola import database as db
from choola import tokens


# ---------------------------------------------------------------------------
# Per-run tally
# ---------------------------------------------------------------------------


def test_init_run_starts_with_zero_total():
    tokens.init_run("r1")
    assert tokens.get_run_total("r1") == 0
    assert tokens.get_run_breakdown("r1") == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "events": [],
    }


def test_report_accumulates_across_calls():
    tokens.init_run("r1")
    tokens.report("r1", "node_a", 10, 5, model="m", provider="p")
    tokens.report("r1", "node_a", 3, 2)
    tokens.report("r1", "node_b", 100, 0)

    assert tokens.get_run_total("r1") == 10 + 5 + 3 + 2 + 100
    breakdown = tokens.get_run_breakdown("r1")
    assert breakdown["prompt_tokens"] == 113
    assert breakdown["completion_tokens"] == 7
    assert breakdown["total_tokens"] == 120
    assert len(breakdown["events"]) == 3


def test_report_coerces_none_to_zero():
    tokens.init_run("r1")
    tokens.report("r1", "n", None, None)  # type: ignore[arg-type]
    assert tokens.get_run_total("r1") == 0
    assert tokens.get_run_breakdown("r1")["events"][0]["prompt_tokens"] == 0


def test_report_without_init_creates_tally():
    # Engine currently calls init_run, but reporting without it must be safe.
    tokens.report("never_inited", "n", 5, 5)
    assert tokens.get_run_total("never_inited") == 10


def test_get_node_tokens_aggregates_per_node():
    tokens.init_run("r1")
    tokens.report("r1", "a", 10, 0, model="claude", provider="anthropic")
    tokens.report("r1", "a", 5, 0, model="claude", provider="anthropic")
    tokens.report("r1", "b", 2, 2)

    a = tokens.get_node_tokens("r1", "a")
    assert a is not None
    assert a["prompt_tokens"] == 15
    assert a["completion_tokens"] == 0
    assert a["total_tokens"] == 15
    assert len(a["events"]) == 2

    b = tokens.get_node_tokens("r1", "b")
    assert b["total_tokens"] == 4


def test_get_node_tokens_returns_none_when_silent():
    tokens.init_run("r1")
    tokens.report("r1", "only_me", 1, 1)
    assert tokens.get_node_tokens("r1", "other") is None


def test_get_node_tokens_returns_none_for_unknown_run():
    assert tokens.get_node_tokens("missing", "x") is None


def test_clear_run_drops_all_state():
    tokens.init_run("r1")
    tokens.report("r1", "n", 10, 5)
    tokens.clear_run("r1")
    assert tokens.get_run_total("r1") == 0


def test_get_run_breakdown_events_are_snapshot_copies():
    tokens.init_run("r1")
    tokens.report("r1", "n", 1, 1)
    snap = tokens.get_run_breakdown("r1")
    snap["events"].append("bad")
    # The internal tally must be untouched.
    assert len(tokens.get_run_breakdown("r1")["events"]) == 1


# ---------------------------------------------------------------------------
# Circuit breaker: check_limits
# ---------------------------------------------------------------------------


def test_check_limits_no_caps_configured_is_noop(db_path: Path):
    tokens.init_run("r1")
    tokens.report("r1", "n", 10**9, 10**9)
    # No globals set → both caps disabled → no exception.
    tokens.check_limits("r1", db_path)


def test_check_limits_per_run_cap_raises(db_path: Path):
    db.set_global_sync("max_tokens_per_run", 100, db_path)
    tokens.init_run("r1")
    tokens.report("r1", "n", 60, 60)  # total 120 > 100
    with pytest.raises(tokens.TokenLimitExceeded, match="Per-run token cap"):
        tokens.check_limits("r1", db_path)


def test_check_limits_per_run_cap_at_boundary_passes(db_path: Path):
    db.set_global_sync("max_tokens_per_run", 100, db_path)
    tokens.init_run("r1")
    tokens.report("r1", "n", 50, 50)  # exactly at the cap — allowed
    tokens.check_limits("r1", db_path)


def test_check_limits_per_hour_cap_sums_run_logs(db_path: Path):
    from datetime import datetime, timezone

    db.set_global_sync("max_tokens_per_hour", 500, db_path)

    now = datetime.now(timezone.utc).isoformat()
    db.insert_run_log(
        run_id="past", workflow_name="w", node_id="n", node_type="t",
        status="COMPLETED", started_at=now, finished_at=now,
        prompt_tokens=400, completion_tokens=200, db_path=db_path,
    )

    tokens.init_run("current")
    with pytest.raises(tokens.TokenLimitExceeded, match="1-hour token cap"):
        tokens.check_limits("current", db_path)


def test_check_limits_per_hour_cap_ignores_old_logs(db_path: Path):
    from datetime import datetime, timedelta, timezone

    db.set_global_sync("max_tokens_per_hour", 500, db_path)

    two_hours_ago = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()
    db.insert_run_log(
        run_id="old", workflow_name="w", node_id="n", node_type="t",
        status="COMPLETED", started_at=two_hours_ago, finished_at=two_hours_ago,
        prompt_tokens=1000, completion_tokens=1000, db_path=db_path,
    )

    tokens.init_run("current")
    tokens.check_limits("current", db_path)  # 2-hour-old usage must not count


def test_check_limits_zero_value_disables_cap(db_path: Path):
    db.set_global_sync("max_tokens_per_run", 0, db_path)
    tokens.init_run("r1")
    tokens.report("r1", "n", 10**9, 10**9)
    tokens.check_limits("r1", db_path)
