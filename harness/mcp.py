"""Shared MCP (Model Context Protocol) transport — one JSON-RPC layer for all adapters.

Replaces the _mcp_request / _list_tools / _call_tool helpers that were copy-pasted
byte-for-byte across the four per-model clients.
"""

import json
import os
import uuid

import httpx

MCP_SERVER_URL = os.environ.get("PRECISELY_MCP_URL", "http://localhost:3000/mcp")


def mcp_request(method: str, params: dict | None = None) -> dict:
    """Send a single JSON-RPC request to the MCP server and return the parsed envelope."""
    payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method}
    if params:
        payload["params"] = params

    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    resp = httpx.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=30, follow_redirects=True)
    resp.raise_for_status()

    # MCP over HTTP may answer with SSE (text/event-stream); pull the first data line.
    if "text/event-stream" in resp.headers.get("content-type", ""):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise ValueError(f"No data line in SSE response: {resp.text[:200]}")

    return resp.json()


def list_raw_tools() -> list[dict]:
    """Fetch the raw, provider-agnostic MCP tool list. Each item has name/description/inputSchema."""
    result = mcp_request("tools/list")
    return result.get("result", {}).get("tools", [])


def call_tool(name: str, arguments: dict) -> str:
    """Invoke a tool on the MCP server and return its text content."""
    result = mcp_request("tools/call", {"name": name, "arguments": arguments})
    content = result.get("result", {}).get("content", [])
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(parts) if parts else json.dumps(result.get("result", {}))
