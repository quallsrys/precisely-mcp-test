"""Anthropic (Claude) adapter."""

import os

import anthropic

from harness.adapters.base import ModelAdapter, ToolCall, ToolResult, Turn
from harness.schema import flatten_combiners


class ClaudeAdapter(ModelAdapter):
    name = "claude"

    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def format_tools(self, raw_tools):
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": flatten_combiners(t.get("inputSchema", {"type": "object", "properties": {}})),
            }
            for t in raw_tools
        ]

    def init_messages(self, prompt):
        return [{"role": "user", "content": prompt}]

    def add_user_message(self, messages, text):
        messages.append({"role": "user", "content": text})

    def add_assistant_turn(self, messages, turn):
        messages.append({"role": "assistant", "content": turn.raw})

    def add_tool_results(self, messages, results):
        blocks = [
            {"type": "tool_result", "tool_use_id": r.call.id, "content": r.output}
            for r in results
        ]
        messages.append({"role": "user", "content": blocks})

    def complete(self, system, messages, tools, max_tokens):
        kwargs = {"model": self.model_id, "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        resp = self.client.messages.create(**kwargs)

        tool_calls = [
            ToolCall(name=b.name, arguments=b.input, id=b.id)
            for b in resp.content if b.type == "tool_use"
        ]
        text = "\n".join(b.text for b in resp.content if b.type == "text")
        usage = resp.usage
        return Turn(
            text=text,
            tool_calls=tool_calls,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            raw=resp.content,
        )
