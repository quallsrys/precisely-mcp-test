"""
Tests for tools that were previously labeled "broken server-side."

As of 2026-08-05 all five WORK. None were Precisely outages — every one was a
client-side bug in our own MCP wrapper (a wrong Accept header, or an output schema that
didn't match the real API shape). Fixes are in dis-locate-apis-v2 (precisely/spatial.py
+ mcp_servers/tools/output_schemas.py).

These tests only check LLM *routing* (does the model call the right tool). They never
validated a tool's output shape, which is exactly why the schema bugs hid here. The real
regression guard lives with the schemas: dis-locate-apis-v2/test_output_schemas_live.py
calls each tool and validates its response against TOOL_OUTPUT_SCHEMAS — run that before
a demo.
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

# All five now work (fixed 2026-08-05). Kept as a named set so the routing tests below
# stay structurally unchanged; empty means no tool is treated as broken / xfailed.
STILL_BROKEN = set()


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


@pytest.mark.parametrize("label,prompt", BROKEN_TOOL_PROMPTS)
async def test_broken_tools_routing_openai(label, prompt, openai_client, log_result):
    result = openai_client.ask(prompt)
    log_result({"llm": "openai", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[OpenAI] No text response for: {label}"
    assert result["tool_calls"], f"[OpenAI] No tool calls for: {label} — LLM did not attempt to route"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[OpenAI] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    if label not in STILL_BROKEN and label in EXPECTED_CONTENT:
        text_lower = result["text"].lower()
        assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
            f"[OpenAI] Response for '{label}' missing expected content {EXPECTED_CONTENT[label]}"
        )


@pytest.mark.parametrize("label,prompt", BROKEN_TOOL_PROMPTS)
async def test_broken_tools_routing_llama(label, prompt, llama_client, log_result):
    result = llama_client.ask(prompt, category="broken")
    log_result({"llm": "llama", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[Llama] No text response for: {label}"

    if label in STILL_BROKEN:
        pytest.xfail(f"[Llama] {EXPECTED_TOOLS[label]} is broken server-side — routing-only not asserted")

    assert result["tool_calls"], f"[Llama] No tool calls for: {label} — LLM did not attempt to route"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Llama] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    if label not in STILL_BROKEN and label in EXPECTED_CONTENT:
        text_lower = result["text"].lower()
        assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
            f"[Llama] Response for '{label}' missing expected content {EXPECTED_CONTENT[label]}"
        )
