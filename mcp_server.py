#!/usr/bin/env python3
"""Standalone MCP server over stdio (JSON-RPC 2.0).

The web demo calls mcp_tools.call_tool() in-process, but the same tools are
reachable by any MCP client. Point Claude Desktop / Cursor at:

    { "command": "python3", "args": ["/path/to/src/mcp_server.py"] }

Try it by hand:
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 mcp_server.py
"""

from __future__ import annotations

import json
import sys

import mcp_tools

SERVER_INFO = {"name": "soren-invoice-router", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"


def handle(request):
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "tools/list":
        return {"tools": mcp_tools.TOOLS}
    if method == "tools/call":
        return mcp_tools.call_tool(params["name"], params.get("arguments") or {})
    if method == "ping":
        return {}
    raise KeyError("method not found: %s" % method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        response = {"jsonrpc": "2.0", "id": request.get("id")}
        try:
            response["result"] = handle(request)
        except Exception as exc:
            response["error"] = {"code": -32601, "message": str(exc)}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
