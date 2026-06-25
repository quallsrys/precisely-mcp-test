"""Anthropic SDK wrapper — calls Precisely MCP server locally (no public URL needed)."""

import json
import os
import time
import uuid

import anthropic
import httpx
from pathlib import Path


MCP_SERVER_URL = os.environ.get("PRECISELY_MCP_URL", "http://localhost:3000/mcp")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "system_prompt.md"


def _mcp_request(method: str, params: dict | None = None) -> dict:
    """Send a single JSON-RPC request to the MCP server."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
    }
    if params:
        payload["params"] = params

    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    resp = httpx.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=30, follow_redirects=True)
    resp.raise_for_status()

    # MCP over HTTP may return SSE (text/event-stream); parse the first data line
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise ValueError(f"No data line in SSE response: {resp.text[:200]}")

    return resp.json()


def _sanitize_schema(schema: dict) -> dict:
    """Flatten oneOf/allOf/anyOf at the top level — Anthropic doesn't support them there."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    if not any(k in schema for k in ("oneOf", "allOf", "anyOf")):
        return schema

    # Merge all variant schemas' properties into one flat object schema
    merged_props: dict = {}
    merged_required: list = []
    for key in ("oneOf", "allOf", "anyOf"):
        for variant in schema.get(key, []):
            merged_props.update(variant.get("properties", {}))
            merged_required.extend(variant.get("required", []))

    result = {"type": "object", "properties": merged_props}
    if merged_required:
        result["required"] = list(dict.fromkeys(merged_required))
    return result


def _list_tools() -> list[dict]:
    """Fetch all tools from the MCP server and convert to Anthropic tool format."""
    result = _mcp_request("tools/list")
    tools = result.get("result", {}).get("tools", [])
    anthropic_tools = []
    for t in tools:
        schema = _sanitize_schema(t.get("inputSchema", {"type": "object", "properties": {}}))
        anthropic_tools.append({
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": schema,
        })
    return anthropic_tools


def _call_tool(name: str, arguments: dict) -> str:
    """Call a tool on the MCP server and return its text content."""
    result = _mcp_request("tools/call", {"name": name, "arguments": arguments})
    content = result.get("result", {}).get("content", [])
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(parts) if parts else json.dumps(result.get("result", {}))


class ClaudeClient:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = CLAUDE_MODEL
        self._tools: list[dict] | None = None
        self.system_prompt = (
            _SYSTEM_PROMPT_PATH.read_text() if _SYSTEM_PROMPT_PATH.exists() else ""
        )

    @property
    def tools(self) -> list[dict]:
        if self._tools is None:
            self._tools = _list_tools()
        return self._tools

    def ask(self, prompt: str, system: str | None = None, max_tokens: int = 4096) -> dict:
        messages = [{"role": "user", "content": prompt}]
        all_tool_calls: list[dict] = []

        t0 = time.perf_counter()

        effective_system = self.system_prompt
        if system:
            effective_system = f"{effective_system}\n\n{system}" if effective_system else system

        while True:
            kwargs = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": messages,
                "tools": self.tools,
            }
            if effective_system:
                kwargs["system"] = effective_system

            response = self.client.messages.create(**kwargs)

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b.text for b in response.content if b.type == "text"]

            for b in tool_use_blocks:
                all_tool_calls.append({"name": b.name, "input": b.input})

            if response.stop_reason != "tool_use":
                latency_ms = round((time.perf_counter() - t0) * 1000)
                return {
                    "model": self.model,
                    "text": "\n".join(text_blocks),
                    "tool_calls": all_tool_calls,
                    "latency_ms": latency_ms,
                    "stop_reason": response.stop_reason,
                    "usage": response.usage.model_dump() if response.usage else {},
                }

            # Execute each tool call and feed results back
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for b in tool_use_blocks:
                output = _call_tool(b.name, b.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": output,
                })
            messages.append({"role": "user", "content": tool_results})
