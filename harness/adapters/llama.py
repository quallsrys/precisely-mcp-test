"""Ollama (local Llama) adapter — OpenAI-compatible API.

Mirrors the OpenAI adapter but points at a local Ollama server. Defaults to the
16k-context model (llama3.1:8b-16k) built via Modelfile.llama16k — the stock 4k
context overflows on large tool-schema payloads.
"""

import json
import os

from openai import OpenAI

from harness.adapters.base import ModelAdapter, ToolCall, ToolResult, Turn
from harness.schema import flatten_combiners


class LlamaAdapter(ModelAdapter):
    name = "llama"

    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or os.environ.get("LLAMA_MODEL", "llama3.1:8b-16k")
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        # api_key is required by the SDK but ignored by Ollama.
        self.client = OpenAI(base_url=base_url, api_key="ollama")

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

        # Reconstruct the assistant message as a plain dict — Ollama is picky about
        # replaying its own response objects back into the history.
        raw = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in (msg.tool_calls or [])
            ],
        }
        usage = resp.usage
        return Turn(
            text=msg.content or "",
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            raw=raw,
        )
