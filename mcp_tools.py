"""MCP tool definitions for the invoice router.

The web app does not call chain.extract() or policy.policy_check() directly -
it goes through call_tool() below, the same entry point an MCP client would hit
over stdio (see mcp_server.py). So the tools are the real interface, not a
decorative wrapper: anything that speaks MCP can drive this pipeline.
"""

from __future__ import annotations

import json

import chain
import policy as policy_module

TOOLS = [
    {
        "name": "extract_invoice_fields",
        "description": (
            "Extract vendor, amount, matter id and line items from raw invoice "
            "text. Returns a confidence score. Does not approve anything."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "invoice_text": {"type": "string", "description": "Raw invoice text"},
            },
            "required": ["invoice_text"],
        },
    },
    {
        "name": "check_billing_policy",
        "description": (
            "Evaluate extracted invoice fields against policy.yaml. Returns "
            "APPROVE or EXCEPTION with a reason for every rule that fired."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "amount": {"type": "number"},
                "matter_id": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
                "line_items": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["amount", "confidence"],
        },
    },
    {
        "name": "list_exception_queue",
        "description": "List invoices currently waiting on a human decision.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_ctx = {"policy": None, "spend": None, "store": None}


def bind(policy=None, spend=None, store=None):
    """app.py hands the live policy + spend + store to the tools."""
    if policy is not None:
        _ctx["policy"] = policy
    if spend is not None:
        _ctx["spend"] = spend
    if store is not None:
        _ctx["store"] = store


def _policy():
    if _ctx["policy"] is None:
        _ctx["policy"] = policy_module.load_policy()
    return _ctx["policy"]


def _spend():
    if _ctx["spend"] is None:
        _ctx["spend"] = {
            mid: m.get("spent_to_date", 0) for mid, m in _policy()["matters"].items()
        }
    return _ctx["spend"]


def call_tool(name, arguments):
    """MCP tools/call. Returns the standard content envelope."""
    try:
        if name == "extract_invoice_fields":
            result = chain.extract(arguments["invoice_text"])
        elif name == "check_billing_policy":
            fields = {k: v for k, v in arguments.items()}
            result = policy_module.policy_check(fields, _policy(), _spend())
        elif name == "list_exception_queue":
            store = _ctx["store"]
            result = {"queue": store.exceptions() if store else []}
        else:
            raise KeyError("unknown tool: %s" % name)
    except Exception as exc:  # surfaced to the client as an MCP tool error
        return {
            "content": [{"type": "text", "text": "%s: %s" % (type(exc).__name__, exc)}],
            "isError": True,
        }

    return {
        "content": [{"type": "text", "text": json.dumps(result, default=str)[:4000]}],
        "structuredContent": result,
        "isError": False,
    }
