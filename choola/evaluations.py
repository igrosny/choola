"""Evaluation storage — writes one JSON file per workflow run for debugging."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path


def build_evaluation(
    run_id: str,
    workflow: str,
    started_at: str,
    initial_payload: dict,
    node_evals: list[dict],
    final_status: str,
    final_payload: dict | None = None,
    error: str | None = None,
) -> dict:
    """Assemble the evaluation dict from collected node execution data."""
    finished_at = datetime.now(timezone.utc).isoformat()
    started_dt = datetime.fromisoformat(started_at)
    finished_dt = datetime.fromisoformat(finished_at)
    duration_ms = int((finished_dt - started_dt).total_seconds() * 1000)

    return {
        "run_id": run_id,
        "workflow": workflow,
        "status": final_status,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "initial_payload": initial_payload,
        "nodes": node_evals,
        "final_payload": final_payload,
        "error": error,
    }


def save_evaluation(workflow_name: str, evaluation: dict) -> Path:
    """Write evaluation dict to workflows/<name>/evaluations/<run_id>.json."""
    eval_dir = Path.cwd() / "workflows" / workflow_name / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)

    path = eval_dir / f"{evaluation['run_id']}.json"
    path.write_text(json.dumps(evaluation, indent=2, default=str) + "\n")
    return path


def capture_payload(payload: dict) -> dict:
    """Deep-copy a payload for evaluation capture. Falls back to shallow copy."""
    try:
        return copy.deepcopy(payload)
    except Exception:
        return dict(payload)


def make_node_eval(
    node_id: str,
    node_type: str,
    status: str,
    started_at: str,
    finished_at: str,
    input_payload: dict,
    output_payload: dict | None = None,
    error: str | None = None,
) -> dict:
    """Build a single node evaluation entry."""
    started_dt = datetime.fromisoformat(started_at)
    finished_dt = datetime.fromisoformat(finished_at)
    duration_ms = int((finished_dt - started_dt).total_seconds() * 1000)

    return {
        "node_id": node_id,
        "node_type": node_type,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "input": input_payload,
        "output": output_payload,
        "error": error,
    }
