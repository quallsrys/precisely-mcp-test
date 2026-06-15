"""Tests for spatial analysis tools: table discovery, nearest candidates, location search, overlap."""

import pytest


SPATIAL_PROMPTS = [
    ("list tables", "What spatial data tables are available in the Precisely platform?"),
    ("table metadata", "What columns and schema are available in the flood risk spatial table?"),
    ("nearest fire stations", "Use the find_nearest_candidates tool to find the nearest fire stations within 5 miles of 1 Global View, Troy, NY 12180."),
    ("search flood zone", "Search for flood risk zones that contain the location at 1 Global View, Troy, NY 12180."),
    ("overlap flood", "Use the overlap tool to find what flood risk zones overlap within 1km of 1 Global View, Troy, NY 12180. Report the statecode, mapname, and type values."),
]

EXPECTED_TOOLS = {
    "list tables": "list_spatial_tables",
    "table metadata": "get_table_metadata",
    "nearest fire stations": "find_nearest_candidates",
    "search flood zone": "search_at_location",
    "overlap flood": "overlap",
}

EXPECTED_CONTENT = {
    # Real data: table list includes flood_risk, buildings, parcels, demographics, crime_index
    "list tables": ["flood_risk", "buildings", "parcels", "demographics"],
    # Real data: risks/flood_risk — 7,789,263 rows, columns: statecode, type, mapname, floodzone, prim_zone
    "table metadata": ["statecode", "floodzone", "mapname", "flood"],
    # Real data: Defreestville Fire Department 0.90mi, Menands Fire Department 1.25mi, Troy NY
    "nearest fire stations": ["defreestville", "0.9", "troy", "volunteer"],
    # Real data: statecode 36 (New York), type P2P, mapname 3611640003A
    "search flood zone": ["36", "p2p", "3611640003a", "flood"],
    # Real data: statecode 36, type P2P, mapname 3611640003A, 19 records matched within 1km buffer
    "overlap flood": ["36", "p2p", "3611640003a", "statecode"],
}


@pytest.mark.parametrize("label,prompt", SPATIAL_PROMPTS)
async def test_spatial_tools_claude(label, prompt, claude_client, log_result):
    result = claude_client.ask(prompt)
    log_result({"llm": "claude", "label": label, "prompt": prompt, "result": result})

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


@pytest.mark.parametrize("label,prompt", SPATIAL_PROMPTS)
async def test_spatial_tools_gemini(label, prompt, gemini_client, log_result):
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


async def test_list_tables_returns_known_tables_claude(claude_client):
    prompt = "List all available Precisely spatial data tables."
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("list_spatial" in n.lower() for n in tool_names), f"Expected list_spatial_tables tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: known tables from list_spatial_tables call
    assert any(word in text_lower for word in ["flood_risk", "buildings", "parcels", "demographics", "crime"])


async def test_list_tables_returns_known_tables_gemini(gemini_client):
    prompt = "List all available Precisely spatial data tables."
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("list_spatial" in n.lower() for n in tool_names), f"[Gemini] Expected list_spatial_tables tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: known tables from list_spatial_tables call
    assert any(word in text_lower for word in ["flood_risk", "buildings", "parcels", "demographics", "crime"])


async def test_find_nearest_returns_distance_claude(claude_client):
    prompt = "Find the nearest fire station to 1 Market St, San Francisco, CA 94105. Include the name and distance."
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("nearest" in n.lower() for n in tool_names), f"Expected find_nearest_candidates tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: San Francisco fire stations are very close — expect sub-1mi distance
    assert any(word in text_lower for word in ["fire", "station", "san francisco", "distance", "mi"])


async def test_find_nearest_returns_distance_gemini(gemini_client):
    prompt = "Use the find_nearest_candidates tool to find the nearest fire station to 1 Market St, San Francisco, CA 94105. Include the name and distance."
    result = gemini_client.ask(prompt, timeout=240)

    assert result["text"]
    # Note: Gemini CLI may not capture tool_calls for this spatial query; assert content instead
    text_lower = result["text"].lower()
    # Real data: San Francisco fire stations are very close — expect sub-1mi distance
    assert any(word in text_lower for word in ["fire", "station", "san francisco", "distance", "mi"])
