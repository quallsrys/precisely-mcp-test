"""Anthropic SDK wrapper that connects to the Precisely MCP server."""

import os
import time
import anthropic


MCP_SERVER_URL = os.environ.get("PRECISELY_MCP_URL", "http://localhost:3000/mcp")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")


class ClaudeClient:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = CLAUDE_MODEL
        self.mcp_servers = [
            {
                "type": "url",
                "url": MCP_SERVER_URL,
                "name": "precisely",
            }
        ]

    def ask(self, prompt: str, system: str | None = None, max_tokens: int = 4096) -> dict:
        """Send a prompt and return the full response dict including tool use."""
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "mcp_servers": self.mcp_servers,
        }
        if system:
            kwargs["system"] = system

        t0 = time.perf_counter()
        response = self.client.beta.messages.create(
            **kwargs,
            betas=["mcp-client-2025-04-04"],
        )
        latency_ms = round((time.perf_counter() - t0) * 1000)

        tool_calls = [
            {"name": b.name, "input": b.input}
            for b in response.content
            if b.type == "tool_use"
        ]
        text_blocks = [b.text for b in response.content if b.type == "text"]

        return {
            "model": self.model,
            "text": "\n".join(text_blocks),
            "tool_calls": tool_calls,
            "latency_ms": latency_ms,
            "stop_reason": response.stop_reason,
            "usage": response.usage.model_dump() if response.usage else {},
        }
