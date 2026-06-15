"""Tests for OGC API and WMS/WMTS map service tools."""

import pytest


MAP_SERVICE_PROMPTS = [
    ("ogc functions", "What OGC API spatial functions are available in the Precisely platform?"),
    ("ogc collections", "List all OGC feature collections available in the Precisely platform."),
    ("ogc collection", "Get the metadata for the OGC feature collection 'risks/flood_risk'."),
    ("ogc collection schema", "What is the schema for the OGC collection 'risks/flood_risk'? List the field names."),
    ("ogc collection queryables", "What fields can be queried in the OGC collection 'risks/flood_risk'?"),
    ("ogc collection items", "Get flood risk features within the bounding box -122.4194,37.7749,-122.4094,37.7849 (San Francisco). Limit to 2 results."),
    ("wms capabilities", "Get the WMS GetCapabilities response from the Precisely map service and list available layers."),
    ("wmts capabilities", "Get the WMTS GetCapabilities response from the Precisely tile service and list available tile layers."),
]

EXPECTED_TOOLS = {
    "ogc functions": "ogc_functions",
    "ogc collections": "ogc_collections",
    "ogc collection": "ogc_collection",
    "ogc collection schema": "ogc_collection_schema",
    "ogc collection queryables": "ogc_collection_queryables",
    "ogc collection items": "ogc_collection_items",
    "wms capabilities": "wms_request",
    "wmts capabilities": "wmts_request",
}

EXPECTED_CONTENT = {
    # Real data: 3 functions — s_within, s_contains, s_intersects
    "ogc functions": ["s_within", "s_contains", "s_intersects"],
    # Real data: 50+ collections including risks/flood_risk, properties/buildings, properties/parcels, boundaries/neighborhoods
    "ogc collections": ["flood_risk", "buildings", "parcels", "neighborhoods"],
    # Real data: id "risks/flood_risk", description "Flood Risk", itemType "feature"
    "ogc collection": ["flood_risk", "flood risk", "feature"],
    # Real data: properties include floodzone, mapname, statecode, prim_zone, bfe_elev, commstatus
    "ogc collection schema": ["floodzone", "mapname", "statecode", "prim_zone"],
    # Real data: queryable fields are incremental_s_no, id, geom, prim_zone
    "ogc collection queryables": ["prim_zone", "geom"],
    # Real data: 2 features with statecode "06", mapname "0602980116A", floodzone "X", type "P2P"
    "ogc collection items": ["0602980116", "statecode", "06", "floodzone"],
    # Real data: WMS 1.3.0 GetCapabilities with layers address_fabric, buildings, parcels
    "wms capabilities": ["address_fabric", "buildings", "parcels", "wms"],
    # Real data: WMTS GetCapabilities with identifiers address_fabric, buildings; TileMatrixSet WorldWebMercatorQuad_0_to_19
    "wmts capabilities": ["address_fabric", "buildings", "worldwebmercatorquad"],
}


@pytest.mark.parametrize("label,prompt", MAP_SERVICE_PROMPTS)
async def test_map_services_claude(label, prompt, claude_client, log_result):
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


@pytest.mark.parametrize("label,prompt", MAP_SERVICE_PROMPTS)
async def test_map_services_gemini(label, prompt, gemini_client, log_result):
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


async def test_ogc_functions_lists_spatial_ops_claude(claude_client):
    prompt = "What spatial filter functions does the Precisely OGC API support?"
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ogc_functions" in n for n in tool_names), f"Expected ogc_functions tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: s_within, s_contains, s_intersects
    assert any(word in text_lower for word in ["s_within", "s_contains", "s_intersects", "within", "contains", "intersects"])


async def test_ogc_functions_lists_spatial_ops_gemini(gemini_client):
    prompt = "What spatial filter functions does the Precisely OGC API support?"
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ogc_functions" in n for n in tool_names), f"[Gemini] Expected ogc_functions tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: s_within, s_contains, s_intersects
    assert any(word in text_lower for word in ["s_within", "s_contains", "s_intersects", "within", "contains", "intersects"])


async def test_ogc_collection_schema_field_names_claude(claude_client):
    prompt = "List every field name in the schema for the risks/flood_risk OGC collection."
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ogc_collection_schema" in n for n in tool_names), f"Expected ogc_collection_schema tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: floodzone, mapname, statecode, prim_zone, bfe_elev
    assert any(word in text_lower for word in ["floodzone", "mapname", "statecode", "prim_zone", "bfe_elev"])


async def test_ogc_collection_schema_field_names_gemini(gemini_client):
    prompt = "List every field name in the schema for the risks/flood_risk OGC collection."
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ogc_collection_schema" in n for n in tool_names), f"[Gemini] Expected ogc_collection_schema tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: floodzone, mapname, statecode, prim_zone, bfe_elev
    assert any(word in text_lower for word in ["floodzone", "mapname", "statecode", "prim_zone", "bfe_elev"])


async def test_ogc_items_returns_geojson_claude(claude_client):
    prompt = (
        "Retrieve flood risk features from the risks/flood_risk OGC collection within bounding box "
        "-122.4194,37.7749,-122.4094,37.7849 in San Francisco. Return up to 2 results and report "
        "the statecode, mapname, and floodzone values."
    )
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ogc_collection_items" in n for n in tool_names), f"Expected ogc_collection_items tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: statecode "06" (California), mapname starts with "060298", floodzone "X"
    assert any(word in text_lower for word in ["06", "0602980116", "floodzone", "statecode", "mapname"])


async def test_ogc_items_returns_geojson_gemini(gemini_client):
    prompt = (
        "Retrieve flood risk features from the risks/flood_risk OGC collection within bounding box "
        "-122.4194,37.7749,-122.4094,37.7849 in San Francisco. Return up to 2 results and report "
        "the statecode, mapname, and floodzone values."
    )
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("ogc_collection_items" in n for n in tool_names), f"[Gemini] Expected ogc_collection_items tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: statecode "06" (California), mapname starts with "060298", floodzone "X"
    assert any(word in text_lower for word in ["06", "0602980116", "floodzone", "statecode", "mapname"])


async def test_wms_capabilities_lists_layers_claude(claude_client):
    prompt = "Call the Precisely WMS GetCapabilities endpoint and list the available map layers."
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("wms_request" in n for n in tool_names), f"Expected wms_request tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: WMS layers include address_fabric, buildings, parcels
    assert any(word in text_lower for word in ["address_fabric", "buildings", "parcels", "wms", "layer"])


async def test_wms_capabilities_lists_layers_gemini(gemini_client):
    prompt = "Call the Precisely WMS GetCapabilities endpoint and list the available map layers."
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("wms_request" in n for n in tool_names), f"[Gemini] Expected wms_request tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: WMS layers include address_fabric, buildings, parcels
    assert any(word in text_lower for word in ["address_fabric", "buildings", "parcels", "wms", "layer"])


async def test_wmts_capabilities_lists_tile_layers_claude(claude_client):
    prompt = "Call the Precisely WMTS GetCapabilities endpoint and list the available tile layers and tile matrix sets."
    result = claude_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("wmts_request" in n for n in tool_names), f"Expected wmts_request tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: WMTS identifiers include address_fabric, buildings; TileMatrixSet WorldWebMercatorQuad_0_to_19
    assert any(word in text_lower for word in ["address_fabric", "buildings", "worldwebmercatorquad", "tile"])


async def test_wmts_capabilities_lists_tile_layers_gemini(gemini_client):
    prompt = "Call the Precisely WMTS GetCapabilities endpoint and list the available tile layers and tile matrix sets."
    result = gemini_client.ask(prompt)

    assert result["text"]
    tool_names = [t["name"] for t in result["tool_calls"]]
    assert any("wmts_request" in n for n in tool_names), f"[Gemini] Expected wmts_request tool, got: {tool_names}"
    text_lower = result["text"].lower()
    # Real data: WMTS identifiers include address_fabric, buildings; TileMatrixSet WorldWebMercatorQuad_0_to_19
    assert any(word in text_lower for word in ["address_fabric", "buildings", "worldwebmercatorquad", "tile"])
