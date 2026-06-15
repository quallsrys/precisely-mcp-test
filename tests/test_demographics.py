"""Tests for demographics, neighborhoods, schools, and crime index tools."""

import pytest


DEMO_PROMPTS = [
    ("demographics", "What are the demographics for the area around 1 Global View, Troy, NY 12180?"),
    ("neighborhoods", "What neighborhood is 350 Fifth Ave, New York, NY 10118 in?"),
    ("schools", "What schools are near 1 Global View, Troy, NY 12180?"),
    ("crime index", "What is the crime index for 350 Fifth Ave, New York, NY 10118?"),
    ("places nearby", "What places are near 1 Global View, Troy, NY 12180?"),
    ("psyte geodemographics", "Get psychographic/geodemographic profile for 1 Global View, Troy, NY 12180."),
]

EXPECTED_TOOLS = {
    "demographics": "get_demographics",
    "neighborhoods": "get_neighborhoods_by_address",
    "schools": "get_schools_by_address",
    "crime index": "get_crime_index",
    "places nearby": "get_places_by_address",
    "psyte geodemographics": "get_psyte_geodemographics_by_address",
}

EXPECTED_CONTENT = {
    # Real data: avg income $155,473, census pop 2,159, avg home value $375,590
    "demographics": ["155", "375", "population", "income"],
    # Real data: Precisely returns "Koreatown" as the neighborhood for 350 Fifth Ave
    "neighborhoods": ["koreatown", "neighborhood"],
    # Real data: North Greenbush Common School District / North Greenbush School
    "schools": ["north greenbush", "school"],
    # Real data: composite 347, violent 478, property 320 — all "highest" vs national avg
    "crime index": ["347", "478", "highest"],
    # Real data: Pitney Bowes Software, MapInfo, Prime View Cafe, ChargePoint at 1 Global View
    "places nearby": ["pitney bowes", "mapinfo", "chargepoint"],
    # Real data: PSYTE returns NC.0 (Not Classified) for office park address
    "psyte geodemographics": ["not classified", "nc.0"],
}


@pytest.mark.parametrize("label,prompt", DEMO_PROMPTS)
async def test_demographic_tools(label, prompt, claude_client, log_result):
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


@pytest.mark.parametrize("label,prompt", DEMO_PROMPTS)
async def test_demographic_tools_gemini(label, prompt, gemini_client, log_result):
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


async def test_schools_include_name_and_distance(claude_client):
    prompt = "List schools within 2 miles of 1 Global View, Troy, NY 12180 with their names and distances."
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("school" in n.lower() for n in tool_names), (
        f"Expected a school tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: North Greenbush Common School District, North Greenbush School
    assert any(word in text_lower for word in ["north greenbush", "school", "district"])


async def test_schools_include_name_and_distance_gemini(gemini_client):
    prompt = "List schools within 2 miles of 1 Global View, Troy, NY 12180 with their names and distances."
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("school" in n.lower() for n in tool_names), (
        f"[Gemini] Expected a school tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: North Greenbush Common School District, North Greenbush School
    assert any(word in text_lower for word in ["north greenbush", "school", "district"])


async def test_demographics_population_data(claude_client):
    prompt = "What is the estimated population and median household income near 350 Fifth Ave, New York, NY 10118?"
    result = claude_client.ask(prompt)

    assert result["text"]
    assert result["tool_calls"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("demographic" in n.lower() for n in tool_names), (
        f"Expected a demographics tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: 350 Fifth Ave block group — avgIncome $167,918, population 2,569
    assert any(word in text_lower for word in ["167", "2,569", "population", "income"])


async def test_demographics_population_data_gemini(gemini_client):
    prompt = "What is the estimated population and median household income near 350 Fifth Ave, New York, NY 10118?"
    result = gemini_client.ask(prompt)

    assert result["text"]
    assert result["tool_calls"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("demographic" in n.lower() for n in tool_names), (
        f"[Gemini] Expected a demographics tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: 350 Fifth Ave block group — avgIncome $167,918, population 2,569
    assert any(word in text_lower for word in ["167", "2,569", "population", "income"])
