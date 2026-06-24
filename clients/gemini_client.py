"""Gemini client using google-genai SDK — drives Gemini against Precisely MCP server."""

import json
import os
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MCP_SERVER_URL = os.environ.get("PRECISELY_MCP_URL", "http://localhost:3000/mcp")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
GEMINI_DELAY_SECONDS = float(os.environ.get("GEMINI_DELAY_SECONDS", "5"))
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "gemini.md"


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


_GEMINI_ALLOWED_SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "format"}


def _sanitize_schema(schema: dict) -> dict:
    """Recursively flatten and strip JSON Schema keywords that Gemini's SDK rejects."""
    if not isinstance(schema, dict):
        return schema

    # Flatten oneOf/allOf/anyOf by merging all variant properties
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

    # Keep only keys Gemini accepts, then recurse into nested schemas
    clean: dict = {}
    for k, v in schema.items():
        if k not in _GEMINI_ALLOWED_SCHEMA_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            clean[k] = {pk: _sanitize_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            clean[k] = _sanitize_schema(v)
        else:
            clean[k] = v

    # Strip required entries that don't correspond to actual properties
    if "required" in clean and "properties" in clean:
        valid_props = set(clean["properties"].keys())
        filtered = [r for r in clean["required"] if r in valid_props]
        if filtered:
            clean["required"] = filtered
        else:
            del clean["required"]

    return clean


def _list_tools() -> list[types.Tool]:
    """Fetch MCP tools and convert to Gemini function declarations."""
    result = _mcp_request("tools/list")
    tools = result.get("result", {}).get("tools", [])

    declarations = []
    for t in tools:
        schema = _sanitize_schema(t.get("inputSchema", {"type": "object", "properties": {}}))

        declarations.append(
            types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=schema,
            )
        )

    return [types.Tool(function_declarations=declarations)]


def _call_tool(name: str, arguments: dict) -> str:
    result = _mcp_request("tools/call", {"name": name, "arguments": arguments})
    content = result.get("result", {}).get("content", [])
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(parts) if parts else json.dumps(result.get("result", {}))


class GeminiClient:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set — add it to .env")
        self.client = genai.Client(api_key=api_key)
        self.model = GEMINI_MODEL
        self.system_prompt = (
            SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""
        )
        self._tools: list[types.Tool] | None = None

    @property
    def tools(self) -> list[types.Tool]:
        if self._tools is None:
            self._tools = _list_tools()
        return self._tools

    def ask(self, prompt: str, system: str | None = None, max_tokens: int = 4096, timeout: int = 240) -> dict:
        time.sleep(GEMINI_DELAY_SECONDS)

        system_instruction = self.system_prompt
        if system:
            system_instruction = f"{system_instruction}\n\n{system}" if system_instruction else system

        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            tools=self.tools,
            max_output_tokens=max_tokens,
        )

        messages: list[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=prompt)])
        ]

        all_tool_calls: list[dict] = []
        t0 = time.perf_counter()

        while True:
            response = self.client.models.generate_content(
                model=self.model,
                contents=messages,
                config=config,
            )

            candidate = response.candidates[0]
            response_content = candidate.content
            messages.append(response_content)

            function_calls = [
                part.function_call
                for part in response_content.parts
                if part.function_call is not None
            ]

            if not function_calls:
                latency_ms = round((time.perf_counter() - t0) * 1000)
                text_parts = [
                    part.text
                    for part in response_content.parts
                    if hasattr(part, "text") and part.text
                ]
                text = "\n".join(text_parts)

                usage = response.usage_metadata
                return {
                    "model": self.model,
                    "text": text,
                    "tool_calls": all_tool_calls,
                    "latency_ms": latency_ms,
                    "stop_reason": str(candidate.finish_reason),
                    "usage": {
                        "input_tokens": usage.prompt_token_count if usage else None,
                        "output_tokens": usage.candidates_token_count if usage else None,
                    },
                }

            tool_response_parts = []
            for fc in function_calls:
                arguments = dict(fc.args) if fc.args else {}
                all_tool_calls.append({"name": fc.name, "input": arguments})

                output = _call_tool(fc.name, arguments)
                tool_response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": output},
                        )
                    )
                )

            messages.append(
                types.Content(role="user", parts=tool_response_parts)
            )
