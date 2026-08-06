"""Ollama (local Llama) adapter — OpenAI-compatible API.

Mirrors the OpenAI adapter but points at a local Ollama server. Defaults to the
16k-context model (llama3.1:8b-16k) built via Modelfile.llama16k — the stock 4k
context overflows on large tool-schema payloads.

Small Llama models (8B) frequently *narrate* a tool call — emitting the
`{"name": ..., "parameters": ...}` JSON their chat template asks for, but wrapped in
prose (and sometimes a hallucinated fake response). Ollama's native parser only
promotes clean single-object output to structured `tool_calls`, so it drops these on
the floor and the loop sees nothing to execute. `_extract_tool_calls` recovers them:
when no structured calls come back, it scans the text for function-call JSON, keeps
only objects naming a real tool (so a hallucinated response object is ignored), and
synthesizes the calls the loop needs.
"""

import json
import os
import re

from openai import OpenAI

from harness.adapters.base import ModelAdapter, ToolCall, ToolResult, Turn
from harness.schema import flatten_combiners


def _iter_json_objects(text: str):
    """Yield each top-level {...} JSON object found in free text, in order."""
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    yield json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    pass
                start = None


def _parse_kwargs(s: str) -> dict:
    """Parse `key='val', key2="val2", key3=val3` from a Python-style call's arg string."""
    args = {}
    for m in re.finditer(r"(\w+)\s*=\s*('([^']*)'|\"([^\"]*)\"|([^,]+))", s):
        raw = m.group(3) if m.group(3) is not None else m.group(4) if m.group(4) is not None else (m.group(5) or "")
        args[m.group(1)] = raw.strip()
    return args


def _extract_tool_calls(text: str, allowed_names: set[str]) -> list[ToolCall]:
    """Recover narrated tool calls from text, in two dialects the 8B model drifts between:
    JSON objects (`{"name": ..., "parameters": ...}`) and Python-style calls
    (`geocode(address='...')`). Only real tool names count, which filters out a model's
    hallucinated 'response' JSON. Duplicates are dropped; JSON is preferred over py-calls.
    """
    calls: list[ToolCall] = []
    seen: set[str] = set()

    def add(name: str, args: dict) -> None:
        if name not in allowed_names or not isinstance(args, dict):
            return
        sig = name + json.dumps(args, sort_keys=True)
        if sig in seen:
            return
        seen.add(sig)
        calls.append(ToolCall(name=name, arguments=args, id=f"llama_{len(calls)}"))

    for obj in _iter_json_objects(text):
        if isinstance(obj, dict):
            add(obj.get("name"), obj.get("parameters", obj.get("arguments", {})))

    # Python-style: name(arg='val', ...). Skips names already captured as JSON above.
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)", text):
        add(m.group(1), _parse_kwargs(m.group(2)))

    return calls


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
        content = msg.content or ""

        tool_calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(name=tc.function.name, arguments=args, id=tc.id))

        # Ollama didn't parse a structured call, but the model may have narrated one as
        # JSON in the text. Recover it so the loop has something real to execute.
        narrated = False
        if not tool_calls and tools and content:
            allowed = {t["function"]["name"] for t in tools}
            recovered = _extract_tool_calls(content, allowed)
            if recovered:
                tool_calls, narrated = recovered, True

        # When we recovered calls from narration, the surrounding prose is noise (often a
        # hallucinated result) — drop it so it never shows as the answer.
        text = "" if tool_calls else content

        # Reconstruct the assistant message as a plain dict — Ollama is picky about
        # replaying its own response objects back into the history. Mirror the final
        # tool_calls (structured or recovered) so tool-result ids line up next round.
        raw = {
            "role": "assistant",
            "content": text,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in tool_calls
            ],
        }
        usage = resp.usage
        return Turn(
            text=text,
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            raw=raw,
        )
