"""Tests for risk assessment tools: flood, wildfire, fire, earthquake, coastal."""

import pytest


RISK_PROMPTS = [
    ("flood risk", "What is the flood risk for 1 Global View, Troy, NY 12180?"),
    ("wildfire risk", "What is the wildfire risk for 1 Panoramic Way, Berkeley, CA 94704?"),
    ("fire risk", "Get the property fire risk for 350 Fifth Ave, New York, NY 10118."),
    ("coastal risk", "What is the coastal risk for 1 Ocean Drive, Miami Beach, FL 33139?"),
    ("earth/earthquake risk", "What is the earthquake or earth risk for 1 Market St, San Francisco, CA 94105?"),
    ("historical weather risk", "What historical weather risks exist at 1 Global View, Troy, NY 12180?"),
]

EXPECTED_TOOLS = {
    "flood risk": "get_flood_risk_by_address",
    "wildfire risk": "get_wildfire_risk_by_address",
    "fire risk": "get_property_fire_risk",
    "coastal risk": "get_coastal_risk",
    "earth/earthquake risk": "get_earth_risk",
    "historical weather risk": "get_historical_weather_risk",
}

EXPECTED_CONTENT = {
    # Real data: Zone C, elevation 178ft, 1,374ft from 100-year flood zone, waterbody 986ft
    "flood risk": ["zone c", "1,374", "178", "flood"],
    # Real data: baseline Moderate, extreme High, Interface aggregation model, WUI 769ft
    "wildfire risk": ["moderate", "high", "interface", "berkeley"],
    # Real data: 3 stations, nearest 0.9mi, night drive 5.32min (fire station proximity tool)
    "fire risk": ["fire station", "0.9", "5", "new york"],
    # Real data: 564ft to Florida Strait, Category 1 winds 150-160mph, wind-borne debris region
    "coastal risk": ["florida strait", "564", "150", "debris"],
    # Real data: nearest fault 8.62mi, 5 magnitude-6 events, 1 magnitude-7 event, NEHRP class CD
    "earth/earthquake risk": ["8.62", "fault", "earthquake", "magnitude"],
    # Real data: hail low risk (79 events), tornado low risk (8 events), wind 1,275 events
    "historical weather risk": ["hail", "tornado", "1,275", "low"],
}


@pytest.mark.parametrize("label,prompt", RISK_PROMPTS)
async def test_risk_tools(label, prompt, claude_client, log_result):
    result = claude_client.ask(prompt)
    log_result({"label": label, "prompt": prompt, "result": result})

    assert result["text"], f"No text for: {label}"
    assert result["tool_calls"], f"No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    text_lower = result["text"].lower()
    assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
        f"Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
    )


@pytest.mark.parametrize("label,prompt", RISK_PROMPTS)
async def test_risk_tools_gemini(label, prompt, gemini_client, log_result):
    result = gemini_client.ask(prompt)
    log_result({"llm": "gemini", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[Gemini] No text for: {label}"
    assert result["tool_calls"], f"[Gemini] No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Gemini] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    text_lower = result["text"].lower()
    assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
        f"[Gemini] Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
    )


async def test_flood_risk_includes_zone(claude_client):
    prompt = "What FEMA flood zone is 1 Global View, Troy, NY 12180 in?"
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("flood" in n.lower() for n in tool_names), f"Expected flood tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: Zone C, elevation 178ft, 1,374ft from 100-year flood zone
    assert any(word in text_lower for word in ["zone c", "1,374", "178", "flood"])


async def test_flood_risk_includes_zone_gemini(gemini_client):
    prompt = "What FEMA flood zone is 1 Global View, Troy, NY 12180 in?"
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("flood" in n.lower() for n in tool_names), f"[Gemini] Expected flood tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: Zone C, elevation 178ft, 1,374ft from 100-year flood zone
    assert any(word in text_lower for word in ["zone c", "1,374", "178", "flood"])


async def test_multi_risk_summary(claude_client):
    prompt = (
        "Give me a complete risk profile for 1 Market St, San Francisco, CA 94105. "
        "Include flood, earthquake, wildfire, and coastal risks."
    )
    result = claude_client.ask(prompt)

    assert result["text"]
    assert len(result["tool_calls"]) >= 2, "Expected multiple risk tools to be called"
    text_lower = result["text"].lower()
    # Real SF data: Zone SHX flood, fault 8.62mi, earthquake magnitude events
    assert any(word in text_lower for word in ["shx", "8.62", "fault", "flood", "earthquake"])


async def test_multi_risk_summary_gemini(gemini_client):
    prompt = (
        "Give me a complete risk profile for 1 Market St, San Francisco, CA 94105. "
        "Include flood, earthquake, wildfire, and coastal risks."
    )
    result = gemini_client.ask(prompt)

    assert result["text"]
    assert len(result["tool_calls"]) >= 2, "[Gemini] Expected multiple risk tools to be called"
    text_lower = result["text"].lower()
    # Real SF data: Zone SHX flood, fault 8.62mi, earthquake magnitude events
    assert any(word in text_lower for word in ["shx", "8.62", "fault", "flood", "earthquake"])
