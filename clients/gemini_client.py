"""Subprocess wrapper that drives the Antigravity CLI (agy) for Precisely MCP tests."""

import json
import os
import subprocess
import time
from pathlib import Path


GEMINI_CMD = os.environ.get("GEMINI_CMD", "/Users/rystan.qualls/.local/bin/agy")
GEMINI_DELAY_SECONDS = float(os.environ.get("GEMINI_DELAY_SECONDS", "10"))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "gemini.md"
import re as _re

# Strips the MCP server prefix added by Gemini (mcp_precisely_) or Claude (mcp__precisely__)
_MCP_PREFIX_RE = _re.compile(r"^mcp_{1,2}precisely_{1,2}", _re.IGNORECASE)


class GeminiClientError(RuntimeError):
    """Raised when the Gemini CLI fails so pytest surfaces the real cause."""
    def __init__(self, reason: str, returncode: int, stderr: str, stdout: str):
        self.reason = reason
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        super().__init__(
            f"Gemini CLI error [{reason}] (exit {returncode})\n"
            f"  stderr: {stderr[:500] or '(empty)'}\n"
            f"  stdout: {stdout[:200] or '(empty)'}"
        )


def _classify_error(stderr: str, returncode: int) -> str:
    """Return a short human-readable reason string from CLI stderr."""
    s = stderr.lower()
    if "quota" in s or "429" in s or "exhausted" in s:
        return "quota_exceeded"
    if "api key" in s or "authentication" in s or "unauthenticated" in s or "401" in s:
        return "auth_error"
    if "not found" in s or "404" in s or "unknown model" in s:
        return "model_not_found"
    if "timeout" in s or "deadline" in s:
        return "timeout"
    if "network" in s or "connection" in s or "enotfound" in s:
        return "network_error"
    return f"cli_exit_{returncode}"


def _normalize_tool_calls(tool_calls: list) -> list:
    """Strip any MCP server prefix so tool names are bare and consistent across all LLMs."""
    normalized = []
    for tc in tool_calls:
        name = tc.get("name", "")
        if name:
            name = _MCP_PREFIX_RE.sub("", name)
        normalized.append({**tc, "name": name})
    return normalized


class GeminiClient:
    def __init__(self):
        self.cmd = GEMINI_CMD
        self.model = GEMINI_MODEL
        self.system_prompt = (
            SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""
        )

    def ask(self, prompt: str, timeout: int = 120) -> dict:
        """Run the Gemini CLI with the given prompt and return a response dict."""
        full_prompt = (
            f"{self.system_prompt}\n\n{prompt}" if self.system_prompt else prompt
        )

        # Append JSON instruction so we can parse tool calls
        full_prompt += (
            "\n\nIMPORTANT: You MUST call a Precisely MCP tool to answer this. "
            "Never answer from your own knowledge — all location data must come from a tool call. "
            "If you do not call a tool, your response is incorrect.\n\n"
            "After calling the tool, respond in JSON only — no markdown, no explanation. "
            "The tool_calls array MUST list every MCP tool you called, with the exact name and parameters you used. "
            "Never leave tool_calls as an empty array if you called a tool. "
            "Use this format exactly: "
            "{\"text\": \"your response\", \"tool_calls\": [{\"name\": \"actual_tool_name_you_called\", \"parameters\": {\"param\": \"value\"}}]}"
        )

        time.sleep(GEMINI_DELAY_SECONDS)

        try:
            t0 = time.perf_counter()
            result = subprocess.run(
                [self.cmd, "--model", self.model, "--prompt", full_prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            latency_ms = round((time.perf_counter() - t0) * 1000)

            stderr = result.stderr.strip()
            raw = result.stdout.strip()

            # Non-zero exit or empty stdout with stderr → the CLI failed
            if result.returncode != 0 or (not raw and stderr):
                reason = _classify_error(stderr, result.returncode)
                raise GeminiClientError(reason, result.returncode, stderr, raw)

            # Strip markdown code fences if Gemini wraps output anyway
            if raw.startswith("```"):
                raw = _re.sub(r"^```[a-z]*\n?", "", raw)
                raw = _re.sub(r"\n?```$", "", raw)
                raw = raw.strip()

            # Try to parse JSON response
            try:
                parsed = json.loads(raw)
                text = parsed.get("text", raw)
                # Gemini sometimes returns a nested dict/object as "text" (raw JSON leaked in)
                if not isinstance(text, str):
                    text = json.dumps(text)
                return {
                    "model": self.model,
                    "text": text,
                    "tool_calls": _normalize_tool_calls(parsed.get("tool_calls", [])),
                    "latency_ms": latency_ms,
                    "raw_output": raw,
                    "stderr": stderr,
                    "returncode": result.returncode,
                }
            except json.JSONDecodeError:
                return {
                    "model": self.model,
                    "text": raw,
                    "tool_calls": [],
                    "latency_ms": latency_ms,
                    "raw_output": raw,
                    "stderr": stderr,
                    "returncode": result.returncode,
                }

        except subprocess.TimeoutExpired:
            raise GeminiClientError(
                "timeout", -1, f"No response after {timeout}s", ""
            )
