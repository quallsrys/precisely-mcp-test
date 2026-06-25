"""OpenAI SDK wrapper — calls Precisely MCP server via the same local agentic loop as claude_client."""

import json
import os
import time
import uuid

import time
import httpx
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
load_dotenv()


MCP_SERVER_URL = os.environ.get("PRECISELY_MCP_URL", "http://localhost:3000/mcp")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_DELAY_SECONDS = float(os.environ.get("OPENAI_DELAY_SECONDS", "5"))
_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "system_prompt.md"


def _mcp_request(method: str, params: dict | None = None) -> dict:
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

    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise ValueError(f"No data line in SSE response: {resp.text[:200]}")

    return resp.json()


def _list_tools() -> list[dict]:
    """Fetch tools from MCP server and convert to OpenAI function-calling format."""
    result = _mcp_request("tools/list")
    tools = result.get("result", {}).get("tools", [])
    openai_tools = []
    for t in tools:
        schema = t.get("inputSchema", {"type": "object", "properties": {}})
        # OpenAI does not support oneOf/allOf/anyOf at the top level — flatten to object
        if any(k in schema for k in ("oneOf", "allOf", "anyOf")):
            merged_props: dict = {}
            merged_required: list = []
            for key in ("oneOf", "allOf", "anyOf"):
                for variant in schema.get(key, []):
                    merged_props.update(variant.get("properties", {}))
                    merged_required.extend(variant.get("required", []))
            schema = {"type": "object", "properties": merged_props}
            if merged_required:
                schema["required"] = list(dict.fromkeys(merged_required))

        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": schema,
            },
        })
    return openai_tools


def _call_tool(name: str, arguments: dict) -> str:
    result = _mcp_request("tools/call", {"name": name, "arguments": arguments})
    content = result.get("result", {}).get("content", [])
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(parts) if parts else json.dumps(result.get("result", {}))


class OpenAIClient:
    def __init__(self):
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = OPENAI_MODEL
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
        time.sleep(OPENAI_DELAY_SECONDS)

        effective_system = self.system_prompt
        if system:
            effective_system = f"{effective_system}\n\n{system}" if effective_system else system

        messages = []
        if effective_system:
            messages.append({"role": "system", "content": effective_system})
        messages.append({"role": "user", "content": prompt})

        all_tool_calls: list[dict] = []
        t0 = time.perf_counter()

        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=messages,
                tools=self.tools,
            )

            msg = response.choices[0].message
            messages.append(msg)

            if not msg.tool_calls:
                latency_ms = round((time.perf_counter() - t0) * 1000)
                usage = response.usage
                return {
                    "model": self.model,
                    "text": msg.content or "",
                    "tool_calls": all_tool_calls,
                    "latency_ms": latency_ms,
                    "stop_reason": response.choices[0].finish_reason,
                    "usage": {
                        "input_tokens": usage.prompt_tokens if usage else None,
                        "output_tokens": usage.completion_tokens if usage else None,
                    },
                }

            for tc in msg.tool_calls:
                name = tc.function.name
                arguments = json.loads(tc.function.arguments)
                all_tool_calls.append({"name": name, "input": arguments})

                output = _call_tool(name, arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": output,
                })
