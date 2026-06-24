"""LLM compatibility tests — same prompt sent to Claude and Gemini for comparison."""

import pytest


COMPARISON_PROMPTS = [
    (
        "geocode_basic",
        "Geocode 1 Global View, Troy, NY 12180 and return the latitude and longitude.",
    ),
    (
        "flood_risk",
        "What is the flood risk for 1 Market St, San Francisco, CA 94105?",
    ),
    (
        "property_summary",
        "Use the get_property_data tool to summarize the property at 2755 Milwaukee St, Denver, CO 80238 — year built, size, and type.",
    ),
    (
        "neighborhood_lookup",
        "What neighborhood is 1600 Pennsylvania Ave NW, Washington, DC 20500 in?",
    ),
]

EXPECTED_TOOLS = {
    "geocode_basic": "geocode",
    "flood_risk": "get_flood_risk_by_address",
    "property_summary": "get_property_data",
    "neighborhood_lookup": "get_neighborhoods_by_address",
}

EXPECTED_CONTENT = {
    # Real data: Precisely geocodes 1 Global View to [-73.704443, 42.682242]
    "geocode_basic": ["42.682", "73.704", "latitude", "longitude", "troy"],
    # Real data: Zone SHX, elevation 10ft, 556ft from 100-year flood zone (SF Market St)
    "flood_risk": ["shx", "556", "flood", "francisco"],
    # Real data: 2755 Milwaukee St Denver — yearBuilt 1927, 1,107 sqft, 2 bed, market value $644,300
    "property_summary": ["1927", "1,107", "denver", "residential"],
    # Real data: Precisely returns "Washington Mall" as the neighborhood
    "neighborhood_lookup": ["washington mall", "neighborhood"],
}


@pytest.mark.parametrize("label,prompt", COMPARISON_PROMPTS)
async def test_claude_responds(label, prompt, claude_client, log_result):
    result = claude_client.ask(prompt)
    log_result({"label": label, "model": "claude", "result": result})

    assert result["text"], f"Claude returned no text for: {label}"
    assert result["tool_calls"], f"Claude made no tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Claude] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    text_lower = result["text"].lower()
    assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
        f"[Claude] Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
    )


@pytest.mark.parametrize("label,prompt", COMPARISON_PROMPTS)
async def test_gemini_responds(label, prompt, gemini_client, log_result):
    result = gemini_client.ask(prompt)
    log_result({"label": label, "model": "gemini", "result": result})

    assert result["text"], f"Gemini returned no text for: {label}"
    assert result["tool_calls"], f"[Gemini] No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Gemini] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    text_lower = result["text"].lower()
    assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
        f"[Gemini] Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
    )


@pytest.mark.parametrize("label,prompt", COMPARISON_PROMPTS)
async def test_both_models_address_prompt(label, prompt, claude_client, gemini_client, log_result):
    """Both models should produce non-empty responses for the same prompt."""
    claude_result = claude_client.ask(prompt)
    gemini_result = gemini_client.ask(prompt)

    log_result({
        "label": label,
        "claude": {"text": claude_result["text"], "tools": [t["name"] for t in claude_result["tool_calls"]]},
        "gemini": {"text": gemini_result["text"], "tools": [t["name"] for t in gemini_result["tool_calls"]]},
    })

    assert claude_result["text"], f"Claude empty for {label}"
    assert gemini_result["text"], f"Gemini empty for {label}"

    # Both models should call the expected tool
    claude_tools = [t["name"] for t in claude_result["tool_calls"]]
    gemini_tools = [t["name"] for t in gemini_result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in claude_tools), (
        f"[Claude cross-model] Expected tool '{EXPECTED_TOOLS[label]}' for '{label}', got: {claude_tools}"
    )
    assert any(EXPECTED_TOOLS[label] in n for n in gemini_tools), (
        f"[Gemini cross-model] Expected tool '{EXPECTED_TOOLS[label]}' for '{label}', got: {gemini_tools}"
    )
