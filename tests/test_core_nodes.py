"""Tests for the shipped core nodes in choola/core/nodes/.

One logical test group per node. HTTP patches requests to avoid the network;
DB/VectorDB use the real per-workflow SQLite/Chroma backends inside the
isolated tmp_cwd.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from choola.core.nodes.db import DB
from choola.core.nodes.form_trigger import FormTrigger
from choola.core.nodes.http import HTTP
from choola.core.nodes.manual_trigger import ManualTrigger
from choola.core.nodes.trigger import Trigger
from choola.core.nodes.vectordb import VectorDB
from choola.core.nodes.webhook_trigger import WebhookTrigger


def _ctx(workflow: str = "demo") -> dict:
    return {"workflow": workflow, "run_id": "test_run", "started_at": "2026-01-01T00:00:00+00:00"}


# ---------------------------------------------------------------------------
# Trigger base class
# ---------------------------------------------------------------------------


async def test_trigger_adds_triggered_at_timestamp():
    node = Trigger()  # type: ignore[abstract]  # Trigger is concrete here
    payload = await node.execute({}, _ctx())
    assert "triggered_at" in payload
    # Must be ISO-parseable.
    from datetime import datetime
    datetime.fromisoformat(payload["triggered_at"])


async def test_trigger_does_not_overwrite_existing_timestamp():
    node = Trigger()
    payload = await node.execute({"triggered_at": "2020-01-01T00:00:00+00:00"}, _ctx())
    assert payload["triggered_at"] == "2020-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# ManualTrigger
# ---------------------------------------------------------------------------


async def test_manual_trigger_tags_payload():
    node = ManualTrigger()
    payload = await node.execute({"x": 1}, _ctx())
    assert payload["trigger_type"] == "manual"
    assert payload["x"] == 1
    assert "triggered_at" in payload


# ---------------------------------------------------------------------------
# WebhookTrigger
# ---------------------------------------------------------------------------


async def test_webhook_trigger_passes_payload_through():
    node = WebhookTrigger()
    incoming = {"method": "POST", "headers": {"X": "1"}, "body": {"a": 1}}
    out = await node.execute(incoming, _ctx())
    assert out == incoming


# ---------------------------------------------------------------------------
# FormTrigger — execute + rendering
# ---------------------------------------------------------------------------


async def test_form_trigger_passes_payload_through():
    node = FormTrigger()
    out = await node.execute({"form_data": {"name": "Alice"}}, _ctx())
    assert out == {"form_data": {"name": "Alice"}}


def test_form_trigger_render_form_contains_fields():
    node = FormTrigger(
        config={
            "path": "/forms/contact",
            "form_title": "Contact Us",
            "form_description": "Say hi",
            "submit_label": "Send",
            "form_fields": [
                {"label": "Name", "field_name": "name", "field_type": "text", "required": True},
                {"label": "Body", "field_name": "body", "field_type": "textarea"},
                {
                    "label": "Topic",
                    "field_name": "topic",
                    "field_type": "dropdown",
                    "options": ["sales", "support"],
                },
                {"label": "Subscribe", "field_name": "subscribe", "field_type": "checkbox"},
            ],
        }
    )
    html = node.render_form()
    assert "Contact Us" in html
    assert "Say hi" in html
    assert 'name="name"' in html
    assert "<textarea" in html
    assert "<select" in html
    assert 'value="sales"' in html
    assert 'type="checkbox"' in html
    assert 'action="/webhook/forms/contact"' in html
    assert ">Send<" in html


def test_form_trigger_render_form_handles_bad_json():
    """Malformed form_fields JSON must not crash rendering."""
    node = FormTrigger(config={"path": "/x", "form_fields": "not json"})
    html = node.render_form()
    assert "<form" in html  # still renders


def test_form_trigger_render_thank_you_page():
    node = FormTrigger(config={"path": "/x", "form_title": "Hi"})
    assert "Form Submitted" in node.render_thank_you()
    assert "Hi" in node.render_thank_you()


def test_form_trigger_escapes_user_input():
    """Titles and labels must be HTML-escaped to prevent XSS."""
    node = FormTrigger(
        config={
            "path": "/x",
            "form_title": "<script>alert(1)</script>",
            "form_fields": [],
        }
    )
    html = node.render_form()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# HTTP node
# ---------------------------------------------------------------------------


def _fake_response(status=200, json_body=None, text="", headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {"content-type": "application/json"}
    if json_body is not None:
        resp.json.return_value = json_body
        resp.text = ""
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = text
    return resp


async def test_http_raises_when_url_missing():
    node = HTTP()
    with pytest.raises(ValueError, match="url is required"):
        await node.execute({}, _ctx())


async def test_http_interpolates_url_and_returns_body():
    node = HTTP(
        config={
            "method": "GET",
            "url": "https://api.example.com/users/{user_id}",
            "headers": "{}",
            "query_params": "{}",
            "timeout": 5,
        }
    )
    captured = {}

    def fake_request(method, url, headers, params, data, timeout):
        captured.update(locals())
        return _fake_response(200, json_body={"id": 42, "name": "Alice"})

    with patch("choola.core.nodes.http.requests.request", side_effect=fake_request):
        result = await node.execute({"user_id": "42"}, _ctx())

    assert captured["url"] == "https://api.example.com/users/42"
    assert captured["method"] == "GET"
    assert result["http_status"] == 200
    assert result["http_body"] == {"id": 42, "name": "Alice"}
    assert result["user_id"] == "42"  # upstream keys preserved


async def test_http_raises_on_missing_interpolation_key():
    node = HTTP(config={"url": "https://api/{missing}"})
    with pytest.raises(ValueError, match="missing payload key"):
        await node.execute({}, _ctx())


async def test_http_parses_text_response_when_not_json():
    node = HTTP(config={"url": "https://x/", "headers": "{}", "query_params": "{}"})
    with patch(
        "choola.core.nodes.http.requests.request",
        return_value=_fake_response(200, text="hello world", headers={"content-type": "text/plain"}),
    ):
        out = await node.execute({}, _ctx())
    assert out["http_body"] == "hello world"


async def test_http_post_interpolates_body_and_sets_content_type():
    # Outer JSON braces must be doubled to survive str.format() interpolation.
    node = HTTP(
        config={
            "method": "POST",
            "url": "https://api/x",
            "headers": "{}",
            "query_params": "{}",
            "body": '{{"name": "{name}"}}',
        }
    )
    captured = {}

    def fake_request(method, url, headers, params, data, timeout):
        captured["data"] = data
        captured["headers"] = headers
        return _fake_response(200, json_body={})

    with patch("choola.core.nodes.http.requests.request", side_effect=fake_request):
        await node.execute({"name": "Ada"}, _ctx())

    assert captured["data"] == '{"name": "Ada"}'
    assert captured["headers"]["Content-Type"] == "application/json"


async def test_http_get_does_not_send_body():
    node = HTTP(
        config={
            "method": "GET",
            "url": "https://api/x",
            "body": '{"ignored": true}',
            "headers": "{}",
            "query_params": "{}",
        }
    )
    captured = {}

    def fake_request(method, url, headers, params, data, timeout):
        captured["data"] = data
        return _fake_response(200, json_body={})

    with patch("choola.core.nodes.http.requests.request", side_effect=fake_request):
        await node.execute({}, _ctx())

    assert captured["data"] is None


async def test_http_adds_bearer_token_from_credential():
    node = HTTP(
        config={
            "method": "GET",
            "url": "https://api/x",
            "headers": "{}",
            "query_params": "{}",
            "credential_name": "my-api-key",
        }
    )

    async def fake_get_cred(name):
        assert name == "my-api-key"
        return {"name": name, "provider": "generic", "value": "sk-token"}

    node._db_get_credential = fake_get_cred
    captured = {}

    def fake_request(method, url, headers, params, data, timeout):
        captured["headers"] = headers
        return _fake_response(200, json_body={})

    with patch("choola.core.nodes.http.requests.request", side_effect=fake_request):
        await node.execute({}, _ctx())

    assert captured["headers"]["Authorization"] == "Bearer sk-token"


async def test_http_raises_when_credential_missing():
    node = HTTP(
        config={
            "url": "https://api/x",
            "headers": "{}",
            "query_params": "{}",
            "credential_name": "absent",
        }
    )

    async def fake_get_cred(name):
        return None

    node._db_get_credential = fake_get_cred

    with pytest.raises(ValueError, match="not found"):
        await node.execute({}, _ctx())


async def test_http_rejects_invalid_json_headers():
    node = HTTP(config={"url": "https://api/x", "headers": "{not-json}"})
    with pytest.raises(ValueError, match="headers must be valid JSON"):
        await node.execute({}, _ctx())


async def test_http_rejects_non_object_json_headers():
    node = HTTP(config={"url": "https://api/x", "headers": "[1,2]"})
    with pytest.raises(ValueError, match="must be a JSON object"):
        await node.execute({}, _ctx())


# ---------------------------------------------------------------------------
# DB node — provisioning
# ---------------------------------------------------------------------------


async def test_db_node_requires_schema(tmp_cwd: Path):
    node = DB(config={"schema": ""})
    with pytest.raises(ValueError, match="schema is required"):
        await node.execute({}, _ctx())


async def test_db_node_creates_tables(tmp_cwd: Path):
    node = DB(
        config={"schema": "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT);"}
    )
    result = await node.execute({"pass": "through"}, _ctx("wf1"))

    assert result["pass"] == "through"
    assert result["db_path"].endswith("workflows/wf1/files/db.sqlite") or result["db_path"].endswith(
        "workflows\\wf1\\files\\db.sqlite"
    )

    # Re-running is idempotent.
    await node.execute({}, _ctx("wf1"))

    from choola import database as db
    rows = await db.workflow_db_query_async(
        "wf1", "SELECT name FROM sqlite_master WHERE type='table'"
    )
    assert {r["name"] for r in rows} >= {"items"}


# ---------------------------------------------------------------------------
# VectorDB node — provisioning
# ---------------------------------------------------------------------------


async def test_vectordb_accepts_list_of_strings(tmp_cwd: Path):
    node = VectorDB(config={"collections": '["alpha", "beta"]'})
    result = await node.execute({}, _ctx("wfv"))

    assert result["collections"] == ["alpha", "beta"]
    assert "vectordb_path" in result


async def test_vectordb_accepts_list_of_objects_with_metadata(tmp_cwd: Path):
    node = VectorDB(
        config={
            "collections": [
                {"name": "docs", "metadata": {"hnsw:space": "cosine"}},
            ]
        }
    )
    result = await node.execute({}, _ctx("wfv2"))
    assert result["collections"] == ["docs"]


async def test_vectordb_rejects_empty_config(tmp_cwd: Path):
    node = VectorDB(config={"collections": ""})
    with pytest.raises(ValueError, match="collections is required"):
        await node.execute({}, _ctx("wf"))


async def test_vectordb_rejects_malformed_json(tmp_cwd: Path):
    node = VectorDB(config={"collections": "{not-json"})
    with pytest.raises(ValueError, match="valid JSON"):
        await node.execute({}, _ctx("wf"))


async def test_vectordb_rejects_non_list_value(tmp_cwd: Path):
    node = VectorDB(config={"collections": '{"a": 1}'})
    with pytest.raises(ValueError, match="non-empty list"):
        await node.execute({}, _ctx("wf"))


async def test_vectordb_rejects_bad_entry_shape(tmp_cwd: Path):
    node = VectorDB(config={"collections": [{"no_name": "x"}]})
    with pytest.raises(ValueError, match="string or an object with"):
        await node.execute({}, _ctx("wf"))
