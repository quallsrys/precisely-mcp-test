"""OpenAI (GPT) adapter."""

import json
import os

from openai import OpenAI

from harness.adapters.base import ModelAdapter, ToolCall, ToolResult, Turn
from harness.schema import flatten_combiners


class OpenAIAdapter(ModelAdapter):
    name = "openai"

    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def format_tools(self, raw_tools):
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": flatten_combiners(t.get("inputSchema", {"type": "object", "properties": {}})),
                },
            }
            for t in raw_tools
        ]

    def init_messages(self, prompt):
        return [{"role": "user", "content": prompt}]

    def add_user_message(self, messages, text):
        messages.append({"role": "user", "content": text})

    def add_assistant_turn(self, messages, turn):
        messages.append(turn.raw)

    def add_tool_results(self, messages, results):
        for r in results:
            messages.append({"role": "tool", "tool_call_id": r.call.id, "content": r.output})

    def complete(self, system, messages, tools, max_tokens):
        call_messages = ([{"role": "system", "content": system}] if system else []) + messages
        kwargs = {"model": self.model_id, "max_tokens": max_tokens, "messages": call_messages}
        if tools:
            kwargs["tools"] = tools

        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        tool_calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(name=tc.function.name, arguments=args, id=tc.id))

        usage = resp.usage
        return Turn(
            text=msg.content or "",
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            raw=msg,
        )
