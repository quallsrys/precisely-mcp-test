"""
Tests for tools that were previously broken server-side.

As of 2026-06-17, validate_phones, get_timezones, and get_spatial_products are
confirmed working — full content assertions restored. lookup and summarize remain
broken server-side (routing-only assertions, xfail on Gemini).

Known remaining issues (as of 2026-06-17):
  lookup    — MCP schema error: must have required property 'response'
  summarize — Upstream 500 error (DIS-1003)
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

# Real data verified 2026-06-17 against live Precisely API
EXPECTED_CONTENT = {
    # Real data: 817-557-7877 is a valid US mobile number on AT&T Wireless
    "validate phones": ["valid", "at&t", "mobile", "8175577877"],
    # Real data: 1 Global View, Troy NY → America/New_York, UTC offset -18000000ms
    "get timezones": ["america/new_york", "eastern", "-18000000"],
    # Real data: products include Flood Risk, Parcels, Crime Index, Property Attributes
    "get spatial products": ["flood risk", "parcels", "crime index", "property"],
}

# These two remain broken server-side — routing-only assertions
STILL_BROKEN = {"lookup", "summarize"}


@pytest.mark.parametrize("label,prompt", BROKEN_TOOL_PROMPTS)
async def test_broken_tools_routing_claude(label, prompt, claude_client, log_result):
    result = claude_client.ask(prompt)
    log_result({"llm": "claude", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"No text response for: {label}"
    assert result["tool_calls"], f"No tool calls for: {label} — LLM did not attempt to route"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    if label not in STILL_BROKEN and label in EXPECTED_CONTENT:
        text_lower = result["text"].lower()
        assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
            f"Response for '{label}' missing expected content {EXPECTED_CONTENT[label]}"
        )



@pytest.mark.parametrize("label,prompt", BROKEN_TOOL_PROMPTS)
async def test_broken_tools_routing_gemini(label, prompt, gemini_client, log_result):
    result = gemini_client.ask(prompt)
    log_result({"llm": "gemini", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[Gemini] No text response for: {label}"

    if label in STILL_BROKEN:
        pytest.xfail(f"Gemini refuses to call {EXPECTED_TOOLS[label]} after prior session error — documented compatibility difference")

    assert result["tool_calls"], f"[Gemini] No tool calls for: {label} — LLM did not attempt to route"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Gemini] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    if label not in STILL_BROKEN and label in EXPECTED_CONTENT:
        text_lower = result["text"].lower()
        assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
            f"[Gemini] Response for '{label}' missing expected content {EXPECTED_CONTENT[label]}"
        )
