"""
Tests for tools with known server-side errors.

These tools are registered and callable but fail due to MCP schema bugs or
upstream API errors — not LLM routing failures. Tests assert only that the
LLM correctly routes to the tool; content assertions are skipped.

Known issues (as of 2026-06-15):
  validate_phones     — MCP schema error on all input formats
  get_timezones       — MCP schema error: dstOffset/timestamp/utcOffset must be object
  get_spatial_products — MCP schema error: recommendedStyle must be string
  lookup              — MCP schema error: must have required property 'response'
  summarize           — Upstream 500 error (DIS-1003)
"""

import pytest


BROKEN_TOOL_PROMPTS = [
    (
        "validate phones",
        "Validate the phone number 817-557-7877 and tell me if it is valid.",
    ),
    (
        "get timezones",
        "Use the get_timezones tool to find the timezone for 1 Global View, Troy, NY 12180.",
    ),
    (
        "get spatial products",
        "List all available Precisely spatial data products.",
    ),
    (
        "lookup",
        "Look up the Precisely address record for key P0000GL41OME.",
    ),
    (
        "summarize",
        "Use the summarize tool to aggregate flood risk attributes within 1 mile of 1 Global View, Troy, NY 12180.",
    ),
]

EXPECTED_TOOLS = {
    "validate phones": "validate_phones",
    "get timezones": "get_timezones",
    "get spatial products": "get_spatial_products",
    "lookup": "lookup",
    "summarize": "summarize",
}


@pytest.mark.parametrize("label,prompt", BROKEN_TOOL_PROMPTS)
async def test_broken_tools_routing_claude(label, prompt, claude_client, log_result):
    """LLM should route to the correct tool even though the server returns an error."""
    result = claude_client.ask(prompt)
    log_result({"llm": "claude", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"No text response for: {label}"
    assert result["tool_calls"], f"No tool calls for: {label} — LLM did not attempt to route"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )
    # No content assertion — server-side error means response body is unreliable


# Gemini refuses to retry lookup and summarize after receiving schema/500 errors in prior session
# calls. This is a compatibility difference from Claude (which always attempts routing).
GEMINI_REFUSES_AFTER_ERROR = {"lookup", "summarize"}


@pytest.mark.parametrize("label,prompt", BROKEN_TOOL_PROMPTS)
async def test_broken_tools_routing_gemini(label, prompt, gemini_client, log_result):
    """LLM should route to the correct tool even though the server returns an error."""
    result = gemini_client.ask(prompt)
    log_result({"llm": "gemini", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[Gemini] No text response for: {label}"

    if label in GEMINI_REFUSES_AFTER_ERROR:
        # Gemini compatibility finding: refuses to call tools that returned errors
        # in previous calls within the session. Claude always attempts routing.
        pytest.xfail(f"Gemini refuses to call {EXPECTED_TOOLS[label]} after prior session error — documented compatibility difference")

    assert result["tool_calls"], f"[Gemini] No tool calls for: {label} — LLM did not attempt to route"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Gemini] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )
    # No content assertion — server-side error means response body is unreliable
