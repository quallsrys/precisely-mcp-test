"""Gemini adapter — google-genai SDK.

Gemini's Pydantic FunctionDeclaration is stricter than the other providers: it rejects
combinators *and* unknown keywords at every nesting level, so it needs a recursive
sanitize pass beyond the shared top-level flatten.
"""

import os
import time

from google import genai
from google.genai import types

from harness.adapters.base import ModelAdapter, ToolCall, ToolResult, Turn

_ALLOWED_SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "format"}


def _sanitize(schema: dict) -> dict:
    """Recursively flatten combinators and strip keys Gemini's FunctionDeclaration rejects."""
    if not isinstance(schema, dict):
        return schema

    if any(k in schema for k in ("oneOf", "allOf", "anyOf")):
        merged_props, merged_required = {}, []
        for key in ("oneOf", "allOf", "anyOf"):
            for variant in schema.get(key, []):
                merged_props.update(variant.get("properties", {}))
                merged_required.extend(variant.get("required", []))
        schema = {"type": "object", "properties": merged_props}
        if merged_required:
            schema["required"] = list(dict.fromkeys(merged_required))

    clean: dict = {}
    for k, v in schema.items():
        if k not in _ALLOWED_SCHEMA_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            clean[k] = {pk: _sanitize(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            clean[k] = _sanitize(v)
        else:
            clean[k] = v

    if "required" in clean and "properties" in clean:
        valid = set(clean["properties"].keys())
        filtered = [r for r in clean["required"] if r in valid]
        if filtered:
            clean["required"] = filtered
        else:
            del clean["required"]
    return clean


class GeminiAdapter(ModelAdapter):
    name = "gemini"

    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.delay = float(os.environ.get("GEMINI_DELAY_SECONDS", "5"))

    def format_tools(self, raw_tools):
        decls = [
            types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=_sanitize(t.get("inputSchema", {"type": "object", "properties": {}})),
            )
            for t in raw_tools
        ]
        return [types.Tool(function_declarations=decls)]

    def init_messages(self, prompt):
        return [types.Content(role="user", parts=[types.Part(text=prompt)])]

    def add_user_message(self, messages, text):
        messages.append(types.Content(role="user", parts=[types.Part(text=text)]))

    def add_assistant_turn(self, messages, turn):
        messages.append(turn.raw)

    def add_tool_results(self, messages, results):
        parts = [
            types.Part(
                function_response=types.FunctionResponse(name=r.call.name, response={"result": r.output})
            )
            for r in results
        ]
        messages.append(types.Content(role="user", parts=parts))

    def complete(self, system, messages, tools, max_tokens):
        if self.delay:
            time.sleep(self.delay)

        config = types.GenerateContentConfig(
            system_instruction=system or None,
            tools=tools or None,
            max_output_tokens=max_tokens,
        )
        resp = self.client.models.generate_content(model=self.model_id, contents=messages, config=config)
        content = resp.candidates[0].content

        tool_calls, text_parts = [], []
        for part in content.parts:
            if getattr(part, "function_call", None):
                fc = part.function_call
                tool_calls.append(ToolCall(name=fc.name, arguments=dict(fc.args) if fc.args else {}))
            elif getattr(part, "text", None):
                text_parts.append(part.text)

        usage = resp.usage_metadata
        return Turn(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
            raw=content,
        )
