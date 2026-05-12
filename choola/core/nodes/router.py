"""
@choola-node: Router
@node-id: <wrapper-defined>
@category: routing
@description: Activate one of N downstream branches by matching a payload key against a value map.
@next-nodes: <wrapper-defined — union of branch targets + default>
@input-payload:
  - <match_key> (any): The payload value to route on; key is set per-node via `match_key`.
@output-payload:
  - router_matched (str | null): The stringified value that matched, "__default__" when the default branch fired, or null when no branch matched.
  - __active_branches__ (list[str]): Engine-magic key; popped by the engine before downstream nodes see it.
  - (all upstream payload keys are preserved)
@config-fields:
  - match_key (str, required): Payload key whose value picks the branch.
  - branches (json, required): Mapping of value -> target node_id, e.g. {"chase": "chase_parser"}.
  - default (str, optional): node_id to activate when no branch matches. Empty = skip all branches.
@example-input: {"bank": "chase"}
@example-output: {"bank": "chase", "router_matched": "chase", "__active_branches__": ["chase_parser"]}
@side-effects: none
@errors: ValueError when match_key is missing or the resolved target is not in next_nodes.
@cost: free
"""

from __future__ import annotations

import json as _json
from typing import Any, ClassVar

from choola.core.base_node import BaseNode


class Router(BaseNode):
    """Declarative branch picker. Subclass it, set ``next_nodes`` to the union
    of every branch target (plus ``default`` if used), and configure
    ``match_key`` / ``branches`` via the wrapper's ``fields``.

    Value matching stringifies the payload value (``str(value)``) so JSON
    branch keys compare cleanly. That means routing on a bool uses
    ``{"True": ..., "False": ...}`` as branch keys.

    For range or threshold routing, do the bucketing in an upstream classifier
    node that sets a discrete key (e.g. ``payload["bucket"] = "high"``), then
    route on that key. For routing logic that doesn't fit value-equality,
    write a custom node that sets ``payload["__active_branches__"]`` directly
    — the Router is convenience, not the only path.
    """

    name = "Router"
    category = "routing"
    description = "Activate one of N downstream branches by matching a payload key against a value map."
    fields: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "match_key",
            "type": "string",
            "required": True,
            "description": "Payload key whose value selects the branch.",
        },
        {
            "name": "branches",
            "type": "json",
            "required": True,
            "default": {},
            "description": 'Mapping of value -> target node_id, e.g. {"chase": "chase_parser"}.',
        },
        {
            "name": "default",
            "type": "string",
            "default": "",
            "description": "node_id to activate when no branch matches. Empty = skip all branches.",
        },
    ]

    async def execute(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        match_key = self.config.get("match_key")
        if not match_key:
            raise ValueError("Router: match_key is required")

        raw_branches = self.config.get("branches") or {}
        if isinstance(raw_branches, str):
            raw_branches = _json.loads(raw_branches) if raw_branches.strip() else {}
        # Normalise keys to strings so JSON-roundtripped values compare cleanly.
        branches: dict[str, str] = {str(k): v for k, v in raw_branches.items()}

        default = self.config.get("default") or ""

        value = payload.get(match_key)
        match_str = str(value) if value is not None else None

        target = branches.get(match_str) if match_str is not None else None
        matched: str | None = match_str if target is not None else None
        if target is None and default:
            target = default
            matched = "__default__"

        if target is None:
            payload["__active_branches__"] = []
            payload["router_matched"] = None
            return payload

        if target not in self.__class__.next_nodes:
            raise ValueError(
                f"Router: target '{target}' not in next_nodes "
                f"{self.__class__.next_nodes!r}. Add it to the wrapper class's next_nodes."
            )

        payload["__active_branches__"] = [target]
        payload["router_matched"] = matched
        return payload
