"""Tests for choola.evaluations — per-run evaluation JSON persistence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from choola import evaluations as ev


# ---------------------------------------------------------------------------
# build_evaluation
# ---------------------------------------------------------------------------


def _iso(seconds_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def test_build_evaluation_computes_duration_ms():
    started = _iso(seconds_ago=5)
    result = ev.build_evaluation(
        run_id="r1",
        workflow="demo",
        started_at=started,
        initial_payload={},
        node_evals=[],
        final_status="COMPLETED",
        final_payload={"x": 1},
    )
    assert result["run_id"] == "r1"
    assert result["workflow"] == "demo"
    assert result["status"] == "COMPLETED"
    assert result["final_payload"] == {"x": 1}
    assert result["duration_ms"] >= 0
    # default token accumulator shape
    assert result["tokens"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "events": [],
    }


def test_build_evaluation_preserves_custom_tokens():
    tokens = {
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
        "events": [{"node_id": "x"}],
    }
    result = ev.build_evaluation(
        run_id="r",
        workflow="w",
        started_at=_iso(),
        initial_payload={},
        node_evals=[],
        final_status="COMPLETED",
        tokens=tokens,
    )
    assert result["tokens"] is tokens


def test_build_evaluation_captures_error_path():
    result = ev.build_evaluation(
        run_id="r",
        workflow="w",
        started_at=_iso(),
        initial_payload={"a": 1},
        node_evals=[],
        final_status="ERROR",
        error="boom",
    )
    assert result["status"] == "ERROR"
    assert result["error"] == "boom"
    assert result["final_payload"] is None


# ---------------------------------------------------------------------------
# make_node_eval
# ---------------------------------------------------------------------------


def test_make_node_eval_shape_and_duration():
    started = _iso(seconds_ago=1)
    finished = _iso()
    node_eval = ev.make_node_eval(
        node_id="n",
        node_type="pkg.N",
        status="COMPLETED",
        started_at=started,
        finished_at=finished,
        input_payload={"a": 1},
        output_payload={"a": 1, "b": 2},
        tokens={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7, "events": []},
    )
    assert node_eval["node_id"] == "n"
    assert node_eval["node_type"] == "pkg.N"
    assert node_eval["status"] == "COMPLETED"
    assert node_eval["input"] == {"a": 1}
    assert node_eval["output"] == {"a": 1, "b": 2}
    assert node_eval["error"] is None
    assert node_eval["duration_ms"] >= 0


def test_make_node_eval_error_path():
    started = _iso(seconds_ago=1)
    finished = _iso()
    node_eval = ev.make_node_eval(
        node_id="n",
        node_type="pkg.N",
        status="ERROR",
        started_at=started,
        finished_at=finished,
        input_payload={},
        error="traceback…",
    )
    assert node_eval["status"] == "ERROR"
    assert node_eval["output"] is None
    assert node_eval["error"] == "traceback…"


# ---------------------------------------------------------------------------
# capture_payload
# ---------------------------------------------------------------------------


def test_capture_payload_is_a_deep_copy():
    original = {"nested": {"list": [1, 2, 3]}}
    captured = ev.capture_payload(original)
    captured["nested"]["list"].append(999)
    assert original["nested"]["list"] == [1, 2, 3]


def test_capture_payload_falls_back_to_shallow_on_deepcopy_failure():
    class Undeepcopyable:
        def __deepcopy__(self, memo):
            raise TypeError("nope")

    payload = {"bad": Undeepcopyable(), "ok": 1}
    captured = ev.capture_payload(payload)
    assert captured["ok"] == 1
    assert set(captured.keys()) == {"bad", "ok"}


# ---------------------------------------------------------------------------
# save_evaluation
# ---------------------------------------------------------------------------


def test_save_evaluation_writes_json_file(tmp_cwd: Path):
    evaluation = ev.build_evaluation(
        run_id="abc123",
        workflow="demo",
        started_at=_iso(),
        initial_payload={},
        node_evals=[],
        final_status="COMPLETED",
    )
    path = ev.save_evaluation("demo", evaluation)

    assert path == tmp_cwd / "workflows" / "demo" / "evaluations" / "abc123.json"
    assert path.exists()

    parsed = json.loads(path.read_text())
    assert parsed["run_id"] == "abc123"
    assert parsed["workflow"] == "demo"
    assert parsed["status"] == "COMPLETED"


def test_save_evaluation_creates_missing_directories(tmp_cwd: Path):
    # No workflows/ dir yet — save_evaluation must create the tree.
    evaluation = ev.build_evaluation(
        run_id="first",
        workflow="fresh",
        started_at=_iso(),
        initial_payload={},
        node_evals=[],
        final_status="COMPLETED",
    )
    path = ev.save_evaluation("fresh", evaluation)
    assert path.exists()
    assert path.parent == tmp_cwd / "workflows" / "fresh" / "evaluations"


def test_save_evaluation_serializes_non_json_values(tmp_cwd: Path):
    """Evaluations may contain datetime objects that need to round-trip."""
    from datetime import datetime, timezone

    evaluation = ev.build_evaluation(
        run_id="r",
        workflow="demo",
        started_at=_iso(),
        initial_payload={"when": datetime.now(timezone.utc)},
        node_evals=[],
        final_status="COMPLETED",
    )
    path = ev.save_evaluation("demo", evaluation)
    # json.dumps(default=str) stringifies datetimes — file must be valid JSON.
    parsed = json.loads(path.read_text())
    assert isinstance(parsed["initial_payload"]["when"], str)
