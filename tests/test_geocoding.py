"""Tests for geocode, reverse_geocode, and verify_address tools."""

import pytest


GEOCODE_PROMPTS = [
    ("geocode a specific address", "Geocode 1 Global View, Troy, NY 12180 and give me the latitude and longitude."),
    ("reverse geocode coordinates", "What address is at latitude 40.7128, longitude -74.0060?"),
    ("verify an address", "Verify this address and tell me if it's deliverable: 350 Fifth Ave, New York, NY 10118"),
    ("autocomplete partial address", "Autocomplete this partial address: '1 Global View, Troy'"),
    ("parse a freeform address", "Parse this freeform address into components: '1600 Amphitheatre Pkwy Mountain View CA 94043'"),
]

EXPECTED_TOOLS = {
    "geocode a specific address": "geocode",
    "reverse geocode coordinates": "reverse_geocode",
    "verify an address": "verify_address",
    "autocomplete partial address": "autocomplete_address",
    "parse a freeform address": "parse_addresses",
}

EXPECTED_CONTENT = {
    # Real coords from Precisely: [-73.704443, 42.682242]
    "geocode a specific address": ["42.682", "73.704", "latitude", "longitude", "troy"],
    # Real reverse result: 52 Chambers St, New York, NY 10007
    "reverse geocode coordinates": ["chambers", "new york", "10007"],
    # Real verify result: EMPIRE STATE BUILDING, 350 5TH AVE, NY 10118 — deliverable
    "verify an address": ["deliverable", "empire state", "5th ave", "10118"],
    # Real autocomplete result: 1 GLOBAL VW, TROY NY 12180
    "autocomplete partial address": ["global", "troy", "12180"],
    # Real parse result: 1600, amphitheatre pkwy, mountain view, ca, 94043
    "parse a freeform address": ["1600", "amphitheatre", "mountain view", "94043"],
}


@pytest.mark.parametrize("label,prompt", GEOCODE_PROMPTS)
async def test_geocoding_claude(label, prompt, claude_client, log_result):
    result = claude_client.ask(prompt)
    log_result({"llm": "claude", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"No text response for: {label}"
    assert result["tool_calls"], f"No tool calls made for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    text_lower = result["text"].lower()
    assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
        f"Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
    )


@pytest.mark.parametrize("label,prompt", GEOCODE_PROMPTS)
async def test_geocoding_gemini(label, prompt, gemini_client, log_result):
    result = gemini_client.ask(prompt)
    log_result({"llm": "gemini", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[Gemini] No text response for: {label}"
    assert result["tool_calls"], f"[Gemini] No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Gemini] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    text_lower = result["text"].lower()
    assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
        f"[Gemini] Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
    )


async def test_geocode_returns_coordinates(claude_client, golden_addresses):
    addr = golden_addresses[0]
    prompt = f"Geocode this address and return the lat/lng: {addr['address']}"
    result = claude_client.ask(prompt)

    assert result["tool_calls"], "Expected at least one tool call"
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("geocode" in n.lower() for n in tool_names), f"Expected a geocode tool, got: {tool_names}"

    text = result["text"].lower()
    # Real Precisely coords: 42.682242, -73.704443
    assert "42.682" in text or "73.704" in text or addr["city"].lower() in text


async def test_geocode_returns_coordinates_gemini(gemini_client, golden_addresses):
    addr = golden_addresses[0]
    prompt = f"Geocode this address and return the lat/lng: {addr['address']}"
    result = gemini_client.ask(prompt)

    assert result["tool_calls"], "[Gemini] Expected at least one tool call"
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("geocode" in n.lower() for n in tool_names), f"[Gemini] Expected a geocode tool, got: {tool_names}"

    text = result["text"].lower()
    # Real Precisely coords: 42.682242, -73.704443
    assert "42.682" in text or "73.704" in text or addr["city"].lower() in text


async def test_verify_address_deliverable(claude_client):
    prompt = "Is this address deliverable? 1 Global View, Troy, NY 12180"
    result = claude_client.ask(prompt)

    assert result["text"]
    assert result["tool_calls"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("verify" in n.lower() for n in tool_names), f"Expected verify_address tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: NON_DELIVERABLE=N, GLOBAL_DELIVERY_INDICATOR=1, "1 GLOBAL VW, TROY NY 12180-8371"
    assert any(word in text_lower for word in ["deliverable", "global vw", "12180", "troy"])


async def test_verify_address_deliverable_gemini(gemini_client):
    prompt = "Is this address deliverable? 1 Global View, Troy, NY 12180"
    result = gemini_client.ask(prompt)

    assert result["text"]
    assert result["tool_calls"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("verify" in n.lower() for n in tool_names), f"[Gemini] Expected verify_address tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: NON_DELIVERABLE=N, GLOBAL_DELIVERY_INDICATOR=1, "1 GLOBAL VW, TROY NY 12180-8371"
    assert any(word in text_lower for word in ["deliverable", "global vw", "12180", "troy"])
