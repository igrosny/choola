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
mcp.py — Model Context Protocol server over JSON-RPC.

Exposes every workflow on disk as one MCP tool. The Flask layer (server.py)
owns the HTTP endpoint and auth; this module owns the protocol + tool shape.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from typing import Any

from choola import __version__

# MCP spec version we advertise. Clients negotiate down if they only speak older.
PROTOCOL_VERSION = "2025-06-18"

# JSON-RPC 2.0 error codes we use.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ------------------------------------------------------------------
# Tool discovery
# ------------------------------------------------------------------
def build_tools_registry() -> dict[str, dict[str, Any]]:
    """Return `{tool_name: {workflow, trigger_kind, node_type, definition}}`.

    Rebuilt on every MCP request so newly-added workflows appear without a
    server restart. Cost is the same as `register_webhooks()` does at startup.
    """
    # Lazy import to avoid circular dependency with server.py on module load.
    from choola.server import (
        WORKFLOWS_DIR,
        _find_trigger,
    )

    registry: dict[str, dict[str, Any]] = {}
    if not WORKFLOWS_DIR.exists():
        return registry

    for wf_dir in sorted(WORKFLOWS_DIR.iterdir()):
        if not wf_dir.is_dir():
            continue
        workflow_name = wf_dir.name
        trigger_kind, trigger_config, node_type = _find_trigger(workflow_name)
        if trigger_kind is None:
            # No recognised trigger — skip so callers can't invoke a malformed DAG.
            continue

        tool_name = _tool_name_for(workflow_name)
        input_schema = _schema_from_trigger(trigger_kind, trigger_config)
        description = _description_from_trigger(
            workflow_name, trigger_kind, trigger_config, node_type
        )

        registry[tool_name] = {
            "workflow": workflow_name,
            "trigger_kind": trigger_kind,
            "node_type": node_type,
            "definition": {
                "name": tool_name,
                "description": description,
                "inputSchema": input_schema,
            },
        }
    return registry


def _tool_name_for(workflow_name: str) -> str:
    # MCP tool names accept [a-zA-Z0-9_-], so the workflow name passes as-is.
    # We prefix with `run__` to make intent obvious to the client and to leave
    # room for future namespacing (e.g. `list__`, `eval__`) without collision.
    return f"run__{workflow_name.replace('-', '_')}"


def _description_from_trigger(
    workflow_name: str,
    trigger_kind: str,
    config: dict[str, Any],
    node_type: str | None,
) -> str:
    from choola.server import node_registry

    cls = node_registry.get(node_type) if node_type else None
    base = (cls.description if cls and cls.description else "") or ""
    title = config.get("form_title") or config.get("name") or workflow_name
    parts: list[str] = []
    if base:
        parts.append(base)
    if title and title != workflow_name and trigger_kind == "form":
        parts.append(f"Form: {title}")
    parts.append(f"Workflow: {workflow_name}")
    parts.append(f"Trigger: {trigger_kind}")
    return " — ".join(parts)


# ------------------------------------------------------------------
# Input-schema derivation
# ------------------------------------------------------------------
_FIELD_TYPE_TO_JSON: dict[str, str] = {
    "text": "string",
    "email": "string",
    "password": "string",
    "textarea": "string",
    "date": "string",
    "number": "number",
    "checkbox": "boolean",
    "dropdown": "string",
}


def _schema_from_trigger(trigger_kind: str, config: dict[str, Any]) -> dict[str, Any]:
    if trigger_kind == "form":
        return _schema_from_form(config)
    if trigger_kind == "webhook":
        return _schema_from_webhook(config)
    # manual / unknown — free-form pass-through
    return {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "description": "Arbitrary payload forwarded to the workflow's trigger.",
                "additionalProperties": True,
            },
        },
        "additionalProperties": False,
    }


def _schema_from_form(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("form_fields", [])
    if isinstance(raw, str):
        try:
            form_fields = json.loads(raw)
        except json.JSONDecodeError:
            form_fields = []
    else:
        form_fields = raw or []

    properties: dict[str, Any] = {}
    required: list[str] = []
    for f in form_fields:
        if not isinstance(f, dict):
            continue
        name = (f.get("field_name") or "").strip()
        if not name:
            continue
        ftype = f.get("field_type", "text")
        prop: dict[str, Any] = {"type": _FIELD_TYPE_TO_JSON.get(ftype, "string")}
        label = f.get("label")
        placeholder = f.get("placeholder")
        desc_parts: list[str] = []
        if label:
            desc_parts.append(str(label))
        if placeholder:
            desc_parts.append(f"placeholder: {placeholder}")
        if desc_parts:
            prop["description"] = " — ".join(desc_parts)
        if ftype == "dropdown":
            options = f.get("options") or []
            if isinstance(options, list) and options:
                prop["enum"] = [str(o) for o in options]
        default_value = f.get("default_value")
        if default_value not in (None, ""):
            prop["default"] = default_value
        properties[name] = prop
        if f.get("required"):
            required.append(name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _schema_from_webhook(config: dict[str, Any]) -> dict[str, Any]:
    method = (config.get("method") or "POST").upper()
    return {
        "type": "object",
        "properties": {
            "body": {
                "type": "object",
                "description": f"JSON body to deliver as if an HTTP {method} hit the webhook.",
                "additionalProperties": True,
            },
            "method": {
                "type": "string",
                "description": "HTTP method to report to the workflow (defaults to the trigger's configured method).",
            },
            "headers": {
                "type": "object",
                "description": "Request headers to forward to the workflow.",
                "additionalProperties": {"type": "string"},
            },
            "query": {
                "type": "object",
                "description": "Query-string parameters to forward to the workflow.",
                "additionalProperties": {"type": "string"},
            },
        },
        "additionalProperties": False,
    }


# ------------------------------------------------------------------
# Arguments → payload
# ------------------------------------------------------------------
def _payload_from_args(
    trigger_kind: str,
    config: dict[str, Any],
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    args = arguments or {}
    now_iso = datetime.now(timezone.utc).isoformat()

    if trigger_kind == "form":
        # Match the shape produced by the real form handler in server.py.
        # Form fields always arrive as strings over HTTP, so coerce here too
        # to avoid surprising downstream nodes that expect `str` values.
        form_data = {k: ("" if v is None else str(v) if not isinstance(v, (dict, list)) else v)
                     for k, v in args.items()}
        return {"form_data": form_data, "submitted_at": now_iso}

    if trigger_kind == "webhook":
        return {
            "method": (args.get("method") or config.get("method") or "POST").upper(),
            "headers": args.get("headers") or {},
            "query": args.get("query") or {},
            "body": args.get("body") if args.get("body") is not None else {},
        }

    # manual — accept either {"payload": {...}} or raw kwargs as the payload.
    if "payload" in args and isinstance(args["payload"], dict):
        return dict(args["payload"])
    return dict(args)


# ------------------------------------------------------------------
# Tool invocation
# ------------------------------------------------------------------
def _call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    from choola.server import run_workflow

    registry = build_tools_registry()
    entry = registry.get(name)
    if entry is None:
        return {
            "content": [
                {"type": "text", "text": f"Unknown tool: {name!r}. Call tools/list for the current set."}
            ],
            "isError": True,
        }

    workflow_name = entry["workflow"]
    trigger_kind = entry["trigger_kind"]
    # Fetch the trigger config again so we always use the on-disk source of truth.
    from choola.server import _find_trigger
    _, config, _ = _find_trigger(workflow_name)
    payload = _payload_from_args(trigger_kind, config, arguments)

    try:
        result = run_workflow(workflow_name, payload)
    except Exception as exc:
        tb = traceback.format_exc()
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"status": "ERROR", "error": str(exc), "traceback": tb},
                        ensure_ascii=False,
                    ),
                }
            ],
            "isError": True,
        }

    return {
        "content": [
            {"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}
        ],
        "isError": False,
    }


# ------------------------------------------------------------------
# JSON-RPC dispatch
# ------------------------------------------------------------------
def dispatch(method: str, params: dict[str, Any] | None) -> tuple[Any, dict[str, Any] | None]:
    """Run an MCP method. Returns (result, error) — exactly one is non-None."""
    params = params or {}

    if method == "initialize":
        return (
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "choola", "version": __version__},
            },
            None,
        )

    if method == "tools/list":
        registry = build_tools_registry()
        tools = [entry["definition"] for entry in registry.values()]
        return ({"tools": tools}, None)

    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return (None, {"code": INVALID_PARAMS, "message": "params.name is required"})
        arguments = params.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            return (None, {"code": INVALID_PARAMS, "message": "params.arguments must be an object"})
        return (_call_tool(name, arguments), None)

    # Silent acks for notifications and any other ping-like method the client sends.
    if method.startswith("notifications/") or method == "ping":
        return (None, None)

    return (None, {"code": METHOD_NOT_FOUND, "message": f"Method not found: {method}"})
