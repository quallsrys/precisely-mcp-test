"""Tests for utility tools: email verification, name parsing, phone validation, IP/WiFi geolocation, emergency services."""

import pytest


UTILITY_PROMPTS = [
    ("verify email", "Verify this email address and tell me if it's valid: rystan.qualls@precisely.com"),
    ("parse name", "Parse this full name into components: 'Dr. John Robert Smith Jr.'"),
    ("geolocate ip", "What is the geographic location of IP address 8.8.8.8?"),
    ("geolocate wifi", "Geolocate this WiFi access point MAC address: 00:22:75:10:d5:91"),
    ("emergency services", "What is the emergency services dispatch center (PSAP) for 1 Global View, Troy, NY 12180?"),
]

EXPECTED_TOOLS = {
    "verify email": "verify_emails",
    "parse name": "parse_name",
    "geolocate ip": "geo_locate_ip_address",
    "geolocate wifi": "geo_locate_wifi_access_point",
    "emergency services": "find_emergency_services",
}

EXPECTED_CONTENT = {
    # Real data: valid, domain precisely.com, smtp microsoft, MX found
    "verify email": ["valid", "precisely.com", "microsoft"],
    # Real data: firstName JOHN, lastName SMITH, titleOfRespect DR, maturitySuffix JR
    "parse name": ["john", "smith", "dr", "jr"],
    # Real data: mountain view, california, google llc, postalCode 94043
    "geolocate ip": ["mountain view", "california", "google", "94043"],
    # Real data: coordinates [-117.280957, 33.13482], accuracy 251 meters
    "geolocate wifi": ["117.28", "33.13", "latitude", "longitude"],
    # Real data: Rensselaer County Bureau of Public Safety, fccId 5185, phone 518-270-5252, Troy NY 12180
    "emergency services": ["rensselaer", "5185", "518-270-5252", "troy"],
}


@pytest.mark.parametrize("label,prompt", UTILITY_PROMPTS)
async def test_utility_tools_claude(label, prompt, claude_client, log_result):
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


@pytest.mark.parametrize("label,prompt", UTILITY_PROMPTS)
async def test_utility_tools_gemini(label, prompt, gemini_client, log_result):
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


async def test_email_verification_detail_claude(claude_client):
    prompt = "Is the email address rystan.qualls@precisely.com valid and deliverable?"
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("email" in n.lower() for n in tool_names), f"Expected email tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: result=valid, domain=precisely.com, mxFound=true
    assert any(word in text_lower for word in ["valid", "precisely.com", "deliverable"])


async def test_email_verification_detail_gemini(gemini_client):
    prompt = "Is the email address rystan.qualls@precisely.com valid and deliverable?"
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("email" in n.lower() for n in tool_names), f"[Gemini] Expected email tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: result=valid, domain=precisely.com, mxFound=true
    assert any(word in text_lower for word in ["valid", "precisely.com", "deliverable"])


async def test_emergency_services_has_psap_claude(claude_client):
    prompt = "Find the 911 dispatch center (PSAP) for 350 Fifth Ave, New York, NY 10118."
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("emergency" in n.lower() for n in tool_names), f"Expected emergency tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: New York City 911 dispatch
    assert any(word in text_lower for word in ["new york", "psap", "911", "dispatch", "police"])


async def test_emergency_services_has_psap_gemini(gemini_client):
    prompt = "Find the 911 dispatch center (PSAP) for 350 Fifth Ave, New York, NY 10118."
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("emergency" in n.lower() for n in tool_names), f"[Gemini] Expected emergency tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: New York City 911 dispatch
    assert any(word in text_lower for word in ["new york", "psap", "911", "dispatch", "police"])


@pytest.mark.parametrize("label,prompt", UTILITY_PROMPTS)
async def test_utility_tools_openai(label, prompt, openai_client, log_result):
    result = openai_client.ask(prompt)
    log_result({"llm": "openai", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[OpenAI] No text for: {label}"
    assert result["tool_calls"], f"[OpenAI] No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[OpenAI] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    text_lower = result["text"].lower()
    assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
        f"[OpenAI] Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
    )


@pytest.mark.parametrize("label,prompt", UTILITY_PROMPTS)
async def test_utility_tools_llama(label, prompt, llama_client, log_result):
    result = llama_client.ask(prompt, category="utilities")
    log_result({"llm": "llama", "label": label, "prompt": prompt, "result": result})

    assert result["text"], f"[Llama] No text for: {label}"
    assert result["tool_calls"], f"[Llama] No tool calls for: {label}"

    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any(EXPECTED_TOOLS[label] in n for n in tool_names), (
        f"[Llama] Expected tool containing '{EXPECTED_TOOLS[label]}' for '{label}', got: {tool_names}"
    )

    text_lower = result["text"].lower()
    assert any(word in text_lower for word in EXPECTED_CONTENT[label]), (
        f"[Llama] Response for '{label}' missing expected content keywords {EXPECTED_CONTENT[label]}"
    )


async def test_email_verification_detail_openai(openai_client):
    prompt = "Is the email address rystan.qualls@precisely.com valid and deliverable?"
    result = openai_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("email" in n.lower() for n in tool_names), f"[OpenAI] Expected email tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: result=valid, domain=precisely.com, mxFound=true
    assert any(word in text_lower for word in ["valid", "precisely.com", "deliverable"])


async def test_email_verification_detail_llama(llama_client):
    prompt = "Is the email address rystan.qualls@precisely.com valid and deliverable?"
    result = llama_client.ask(prompt, category="utilities")

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("email" in n.lower() for n in tool_names), f"[Llama] Expected email tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: result=valid, domain=precisely.com, mxFound=true
    assert any(word in text_lower for word in ["valid", "precisely.com", "deliverable"])


async def test_emergency_services_has_psap_openai(openai_client):
    prompt = "Find the 911 dispatch center (PSAP) for 350 Fifth Ave, New York, NY 10118."
    result = openai_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("emergency" in n.lower() for n in tool_names), f"[OpenAI] Expected emergency tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: New York City 911 dispatch
    assert any(word in text_lower for word in ["new york", "psap", "911", "dispatch", "police"])


async def test_emergency_services_has_psap_llama(llama_client):
    prompt = "Find the 911 dispatch center (PSAP) for 350 Fifth Ave, New York, NY 10118."
    result = llama_client.ask(prompt, category="utilities")

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("emergency" in n.lower() for n in tool_names), f"[Llama] Expected emergency tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: New York City 911 dispatch
    assert any(word in text_lower for word in ["new york", "psap", "911", "dispatch", "police"])
