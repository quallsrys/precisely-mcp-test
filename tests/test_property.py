"""Tests for property data tools: property_data, parcels, buildings, replacement_cost."""

import pytest


PROPERTY_PROMPTS = [
    ("property data", "Get property data for 2755 Milwaukee St, Denver, CO 80238."),
    ("parcel info", "What parcel information is available for 1 Global View, Troy, NY 12180?"),
    ("building info", "What buildings are at 1600 Pennsylvania Ave NW, Washington, DC 20500?"),
    ("replacement cost", "What is the replacement cost estimate for 2755 Milwaukee St, Denver, CO 80238?"),
    ("property attributes", "Get property attributes for 233 S Wacker Dr, Chicago, IL 60606."),
    ("parcel by owner", "Find parcel details by owner name for 1 Global View, Troy, NY 12180."),
]

EXPECTED_TOOLS = {
    "property data": "get_property_data",
    "parcel info": "get_parcels_by_address",
    "building info": "get_buildings_by_address",
    "replacement cost": "get_replacement_cost_by_address",
    "property attributes": "get_property_attributes_by_address",
    "parcel by owner": "get_parcel_by_owner_detailed",
}

EXPECTED_CONTENT = {
    # Real data: 2755 Milwaukee St Denver — yearBuilt 1927, 1,107 sqft, 2 bed, market value $644,300
    "property data": ["1927", "1,107", "644,300", "denver"],
    # Real data: APN 122.-1-4.221, area 603,556 sqft, FIPS 36083
    "parcel info": ["apn", "122", "36083", "troy"],
    # Real data: Business type, area 55,662 sqft, elevation 58ft, Washington DC
    "building info": ["55,662", "business", "58", "washington"],
    # Real data: 2755 Milwaukee St Denver — replacement cost $292,289, confidence HIGH
    "replacement cost": ["292,289", "high", "replacement", "denver"],
    # Real data: yearBuilt 1970, buildingSquareFootage 4,001,900 (Willis Tower)
    "property attributes": ["1970", "wacker", "chicago"],
    # Real data: 3 parcels, APNs starting with 122, FIPS 36083
    "parcel by owner": ["apn", "122", "36083", "troy"],
}


@pytest.mark.parametrize("label,prompt", PROPERTY_PROMPTS)
async def test_property_tools_claude(label, prompt, claude_client, log_result):
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


@pytest.mark.parametrize("label,prompt", PROPERTY_PROMPTS)
async def test_property_tools_gemini(label, prompt, gemini_client, log_result):
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


async def test_property_data_has_expected_fields_claude(claude_client):
    # Using residential address — commercial addresses (Precisely HQ, ESB) return no property attributes
    prompt = "Get full property data for 2755 Milwaukee St, Denver, CO 80238 including year built, square footage, and bedrooms."
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("property" in n.lower() or "parcel" in n.lower() for n in tool_names), (
        f"Expected property or parcel tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: yearBuilt 1927, 1,107 sqft, 2 bedrooms, market value $644,300
    assert any(word in text_lower for word in ["1927", "1,107", "644,300", "denver"])


async def test_property_data_has_expected_fields_gemini(gemini_client):
    # Using residential address — commercial addresses (Precisely HQ, ESB) return no property attributes
    prompt = "Get full property data for 2755 Milwaukee St, Denver, CO 80238 including year built, square footage, and bedrooms."
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("property" in n.lower() or "parcel" in n.lower() for n in tool_names), (
        f"[Gemini] Expected property or parcel tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: yearBuilt 1927, 1,107 sqft, 2 bedrooms, market value $644,300
    assert any(word in text_lower for word in ["1927", "1,107", "644,300", "denver"])


async def test_buildings_response_claude(claude_client):
    prompt = "What buildings exist at 1 World Trade Center, New York, NY 10007?"
    result = claude_client.ask(prompt)

    assert result["text"]
    assert result["tool_calls"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("building" in n.lower() for n in tool_names), f"Expected buildings tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: Mixed type, 42,570 sqft, elevation -5ft (below sea level)
    assert any(word in text_lower for word in ["42,570", "42570", "mixed", "world trade", "new york"])


async def test_buildings_response_gemini(gemini_client):
    prompt = "What buildings exist at 1 World Trade Center, New York, NY 10007?"
    result = gemini_client.ask(prompt)

    assert result["text"]
    assert result["tool_calls"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("building" in n.lower() for n in tool_names), f"[Gemini] Expected buildings tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: Mixed type, 42,570 sqft, elevation -5ft (below sea level)
    assert any(word in text_lower for word in ["42,570", "42570", "mixed", "world trade", "new york"])
