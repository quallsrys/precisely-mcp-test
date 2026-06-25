"""Ollama wrapper using OpenAI-compatible API — drives local llama3.1:8b against Precisely MCP server."""

import json
import os
import time
import uuid

import httpx
from openai import OpenAI
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


MCP_SERVER_URL = os.environ.get("PRECISELY_MCP_URL", "http://localhost:3000/mcp")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
LLAMA_MODEL = os.environ.get("LLAMA_MODEL", "llama3.1:8b")
_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "system_prompt.md"


def _mcp_request(method: str, params: dict | None = None) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
    }
    if params:
        payload["params"] = params

    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    resp = httpx.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=30, follow_redirects=True)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise ValueError(f"No data line in SSE response: {resp.text[:200]}")

    return resp.json()


def _list_tools() -> list[dict]:
    """Fetch tools from MCP server in OpenAI function-calling format."""
    result = _mcp_request("tools/list")
    tools = result.get("result", {}).get("tools", [])
    openai_tools = []
    for t in tools:
        schema = t.get("inputSchema", {"type": "object", "properties": {}})
        if any(k in schema for k in ("oneOf", "allOf", "anyOf")):
            merged_props: dict = {}
            merged_required: list = []
            for key in ("oneOf", "allOf", "anyOf"):
                for variant in schema.get(key, []):
                    merged_props.update(variant.get("properties", {}))
                    merged_required.extend(variant.get("required", []))
            schema = {"type": "object", "properties": merged_props}
            if merged_required:
                schema["required"] = list(dict.fromkeys(merged_required))

        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": schema,
            },
        })
    return openai_tools


def _call_tool(name: str, arguments: dict) -> str:
    result = _mcp_request("tools/call", {"name": name, "arguments": arguments})
    content = result.get("result", {}).get("content", [])
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(parts) if parts else json.dumps(result.get("result", {}))


# llama3.1:8b fails to route when given all 51 tools — filter to a relevant subset per category.
# Keys are category names passed via the `tools` parameter on ask(); values are exact tool names.
TOOL_CATEGORIES: dict[str, list[str]] = {
    "geocoding": ["geocode", "reverse_geocode", "verify_address", "autocomplete_address", "parse_addresses", "lookup", "get_addresses_detailed", "get_address_family"],
    "risk": ["get_flood_risk_by_address", "get_wildfire_risk_by_address", "get_property_fire_risk", "get_coastal_risk", "get_earth_risk", "get_historical_weather_risk"],
    "property": ["get_property_data", "get_parcels_by_address", "get_parcel_by_owner_detailed", "get_buildings_by_address", "get_replacement_cost_by_address", "get_property_attributes_by_address", "get_serviceability", "get_ground_view_by_address"],
    "demographics": ["get_demographics", "get_neighborhoods_by_address", "get_schools_by_address", "get_crime_index", "get_places_by_address", "get_psyte_geodemographics_by_address"],
    "spatial": ["find_nearest_candidates", "search_at_location", "overlap", "get_spatial_products", "list_spatial_tables", "get_table_metadata", "summarize"],
    "map_services": ["ogc_functions", "ogc_collections", "ogc_collection", "ogc_collection_schema", "ogc_collection_queryables", "ogc_collection_items", "wms_request", "wmts_request"],
    "utilities": ["verify_emails", "validate_phones", "parse_name", "geo_locate_ip_address", "geo_locate_wifi_access_point", "find_emergency_services", "lookup_tax_jurisdiction", "get_timezones"],
    # Cross-category set for workflow and broken-tool tests
    "workflow": ["geocode", "verify_address", "get_neighborhoods_by_address", "get_property_data", "get_property_attributes_by_address", "get_replacement_cost_by_address", "get_flood_risk_by_address", "get_coastal_risk", "get_wildfire_risk_by_address", "get_earth_risk", "get_property_fire_risk", "get_demographics", "get_schools_by_address", "get_crime_index", "get_places_by_address", "lookup_tax_jurisdiction"],
    "broken": ["validate_phones", "get_timezones", "get_spatial_products", "lookup", "summarize"],
}


class LlamaClient:
    def __init__(self):
        # Ollama's OpenAI-compatible endpoint — api_key is required by the SDK but unused by Ollama
        self.client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
        self.model = LLAMA_MODEL
        self._all_tools: list[dict] | None = None
        self.system_prompt = (
            _SYSTEM_PROMPT_PATH.read_text() if _SYSTEM_PROMPT_PATH.exists() else
            "You are a helpful assistant. Always call the appropriate tool for location, address, or geographic data — never answer from your own knowledge."
        )

    @property
    def all_tools(self) -> list[dict]:
        if self._all_tools is None:
            self._all_tools = _list_tools()
        return self._all_tools

    def _filter_tools(self, category: str | None) -> list[dict]:
        """Return only the tools relevant to the given category, or all tools if None."""
        if not category or category not in TOOL_CATEGORIES:
            return self.all_tools
        allowed = set(TOOL_CATEGORIES[category])
        return [t for t in self.all_tools if t["function"]["name"] in allowed]

    def ask(self, prompt: str, system: str | None = None, max_tokens: int = 4096, category: str | None = None) -> dict:
        effective_system = self.system_prompt
        if system:
            effective_system = f"{effective_system}\n\n{system}" if effective_system else system
        messages = [{"role": "system", "content": effective_system}]
        messages.append({"role": "user", "content": prompt})
        tools = self._filter_tools(category)

        all_tool_calls: list[dict] = []
        t0 = time.perf_counter()

        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=messages,
                tools=tools,
            )

            msg = response.choices[0].message
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in (msg.tool_calls or [])
            ]})

            if not msg.tool_calls:
                latency_ms = round((time.perf_counter() - t0) * 1000)
                usage = response.usage
                return {
                    "model": self.model,
                    "text": msg.content or "",
                    "tool_calls": all_tool_calls,
                    "latency_ms": latency_ms,
                    "stop_reason": response.choices[0].finish_reason,
                    "usage": {
                        "input_tokens": usage.prompt_tokens if usage else None,
                        "output_tokens": usage.completion_tokens if usage else None,
                    },
                }

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}
                all_tool_calls.append({"name": name, "input": arguments})

                output = _call_tool(name, arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": output,
                })
