"""Tests for extended address tools: detailed address lookup, serviceability, ground view demographics, address family."""

import pytest


ADDRESS_EXTENDED_PROMPTS = [
    ("addresses detailed", "Get the detailed address record for 1 Global View, Troy, NY 12180 including the Precisely ID."),
    ("serviceability", "Is broadband service available at 2755 Milwaukee St, Denver, CO 80238?"),
    ("ground view", "Get the Ground View census demographic statistics for 1 Global View, Troy, NY 12180."),
    ("address family", "Find all addresses in the same building as 1 Global View, Troy, NY 12180."),
]

EXPECTED_TOOLS = {
    "addresses detailed": "get_addresses_detailed",
    "serviceability": "get_serviceability",
    "ground view": "get_ground_view_by_address",
    "address family": "get_address_family",
}

EXPECTED_CONTENT = {
    # Real data: preciselyID P0000GL41OME, streetName GLOBAL VW, city TROY, postalCode 12180
    "addresses detailed": ["p0000gl41ome", "global vw", "troy", "12180"],
    # Real data: serviceableAddress YES, serviceabilityID S000PNFQIG09, Denver
    "serviceability": ["yes", "serviceable", "denver"],
    # Real data: avgHouseholdIncome 155473, avgHomeValue 375590, population 2159, Troy NY
    "ground view": ["155", "375", "2,159", "troy"],
    # Real data: P0000GL41OME is a single commercial address — addressFamily returns null
    # Only asserting tool routing; content assertion skipped (no family members for office building)
    "address family": [],
}


@pytest.mark.parametrize("label,prompt", ADDRESS_EXTENDED_PROMPTS)
async def test_address_extended_claude(label, prompt, claude_client, log_result):
    result = claude_client.ask(prompt)
    log_result({"llm": "claude", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"No text for: {label}"
    assert result["tool_calls"], f"No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    if EXPECTED_CONTENT[label]:
        text_lower = result["text"].lower()
        assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
            f"Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
        )


@pytest.mark.parametrize("label,prompt", ADDRESS_EXTENDED_PROMPTS)
async def test_address_extended_gemini(label, prompt, gemini_client, log_result):
    result = gemini_client.ask(prompt)
    log_result({"llm": "gemini", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[Gemini] No text for: {label}"
    assert result["tool_calls"], f"[Gemini] No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Gemini] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    if EXPECTED_CONTENT[label]:
        text_lower = result["text"].lower()
        assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
            f"[Gemini] Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
        )


async def test_ground_view_income_data_claude(claude_client):
    prompt = "What is the average household income and home value for the census block group at 1 Global View, Troy, NY 12180?"
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ground" in n.lower() or "demographic" in n.lower() for n in tool_names), (
        f"Expected ground view or demographics tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: avgHouseholdIncome 155473, avgHomeValue 375590
    assert any(word in text_lower for word in ["155", "375", "income", "home value"])


async def test_ground_view_income_data_gemini(gemini_client):
    prompt = "What is the average household income and home value for the census block group at 1 Global View, Troy, NY 12180?"
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ground" in n.lower() or "demographic" in n.lower() for n in tool_names), (
        f"[Gemini] Expected ground view or demographics tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: avgHouseholdIncome 155473, avgHomeValue 375590
    assert any(word in text_lower for word in ["155", "375", "income", "home value"])


async def test_serviceability_returns_status_claude(claude_client):
    prompt = "Check broadband serviceability for 2755 Milwaukee St, Denver, CO 80238 and tell me if the address is serviceable."
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("serviceab" in n.lower() for n in tool_names), f"Expected serviceability tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: serviceableAddress YES
    assert any(word in text_lower for word in ["yes", "serviceable", "available"])


async def test_serviceability_returns_status_gemini(gemini_client):
    prompt = "Check broadband serviceability for 2755 Milwaukee St, Denver, CO 80238 and tell me if the address is serviceable."
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("serviceab" in n.lower() for n in tool_names), f"[Gemini] Expected serviceability tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: serviceableAddress YES
    assert any(word in text_lower for word in ["yes", "serviceable", "available"])


@pytest.mark.parametrize("label,prompt", ADDRESS_EXTENDED_PROMPTS)
async def test_address_extended_openai(label, prompt, openai_client, log_result):
    result = openai_client.ask(prompt)
    log_result({"llm": "openai", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[OpenAI] No text for: {label}"
    assert result["tool_calls"], f"[OpenAI] No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[OpenAI] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    if EXPECTED_CONTENT[label]:
        text_lower = result["text"].lower()
        assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
            f"[OpenAI] Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
        )


@pytest.mark.parametrize("label,prompt", ADDRESS_EXTENDED_PROMPTS)
async def test_address_extended_llama(label, prompt, llama_client, log_result):
    result = llama_client.ask(prompt, category="geocoding")
    log_result({"llm": "llama", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[Llama] No text for: {label}"
    assert result["tool_calls"], f"[Llama] No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Llama] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    if EXPECTED_CONTENT[label]:
        text_lower = result["text"].lower()
        assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
            f"[Llama] Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
        )


async def test_ground_view_income_data_openai(openai_client):
    prompt = "What is the average household income and home value for the census block group at 1 Global View, Troy, NY 12180?"
    result = openai_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ground" in n.lower() or "demographic" in n.lower() for n in tool_names), (
        f"[OpenAI] Expected ground view or demographics tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: avgHouseholdIncome 155473, avgHomeValue 375590
    assert any(word in text_lower for word in ["155", "375", "income", "home value"])


async def test_ground_view_income_data_llama(llama_client):
    prompt = "What is the average household income and home value for the census block group at 1 Global View, Troy, NY 12180?"
    result = llama_client.ask(prompt, category="geocoding")

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ground" in n.lower() or "demographic" in n.lower() for n in tool_names), (
        f"[Llama] Expected ground view or demographics tool, got: {tool_names}"
    )
    text_lower = result["text"].lower()
    # Real data: avgHouseholdIncome 155473, avgHomeValue 375590
    assert any(word in text_lower for word in ["155", "375", "income", "home value"])


async def test_serviceability_returns_status_openai(openai_client):
    prompt = "Check broadband serviceability for 2755 Milwaukee St, Denver, CO 80238 and tell me if the address is serviceable."
    result = openai_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("serviceab" in n.lower() for n in tool_names), f"[OpenAI] Expected serviceability tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: serviceableAddress YES
    assert any(word in text_lower for word in ["yes", "serviceable", "available"])


async def test_serviceability_returns_status_llama(llama_client):
    prompt = "Check broadband serviceability for 2755 Milwaukee St, Denver, CO 80238 and tell me if the address is serviceable."
    result = llama_client.ask(prompt, category="geocoding")

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("serviceab" in n.lower() for n in tool_names), f"[Llama] Expected serviceability tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: serviceableAddress YES
    assert any(word in text_lower for word in ["yes", "serviceable", "available"])
