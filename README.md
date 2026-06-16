# Precisely MCP Test Suite

End-to-end multi-LLM test suite for the **Precisely DIS / Locate APIs v2 MCP server**. Tests every tool across Claude and Gemini to verify routing accuracy, response correctness, and behavioral consistency between LLMs.

| Metric | Value |
|---|---|
| Tools covered | 51 / 51 (100%) |
| LLMs validated | Claude (Anthropic SDK), Gemini (CLI) |
| Total tests | ~160 |
| Test categories | Geocoding, Risk, Property, Demographics, Spatial, Map Services, Utilities, Workflows, LLM Compat, Broken Tools |

---

## Setup

```bash
cd precisely-mcp-test
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Set required environment variables:

```bash
export ANTHROPIC_API_KEY=your_key_here
export PRECISELY_MCP_URL=http://localhost:3000/mcp   # default if not set
```

Gemini uses the CLI — make sure `gemini` is on your PATH and authenticated via API key.

Run all tests:

```bash
pytest
```

Run by LLM:

```bash
pytest -k "claude" -v
pytest -k "gemini" -v
```

---

## How It Works

### Claude client
`clients/claude_client.py` runs a local agentic loop:
1. Fetches the full tool list from the MCP server at startup
2. Sends the prompt + tools to the Claude API (standard messages endpoint — no public URL required)
3. When Claude returns `tool_use` blocks, executes each tool call against the local MCP server
4. Feeds tool results back to Claude until `stop_reason != tool_use`

No tunnel or public-facing MCP URL is needed. Everything runs against `localhost:3000`.

### Gemini client
`clients/gemini_client.py` calls the Gemini CLI as a subprocess with the system prompt from `gemini.md`. The CLI handles MCP tool calls natively. Responses are parsed from stdout JSON.

---

## File Reference

### Root

| File | Purpose |
|------|---------|
| [`conftest.py`](conftest.py) | Shared pytest fixtures: `claude_client`, `gemini_client`, `log_result`. Loaded automatically by pytest. |
| [`pytest.ini`](pytest.ini) | Sets `asyncio_mode = auto`, points pytest at `tests/`, enables console logging. |
| [`requirements.txt`](requirements.txt) | Dependencies: `anthropic`, `httpx`, `pytest`, `pytest-asyncio`. |
| [`gemini.md`](gemini.md) | System prompt injected into every Gemini CLI call — lists all 51 Precisely tools with descriptions and behavioral guidelines. |

---

### `clients/`

| File | Purpose |
|------|---------|
| [`clients/claude_client.py`](clients/claude_client.py) | Local agentic loop over the Anthropic SDK. Fetches MCP tools at startup, runs tool calls against localhost, no public URL needed. Sanitizes `oneOf`/`allOf`/`anyOf` schemas that Anthropic rejects. |
| [`clients/gemini_client.py`](clients/gemini_client.py) | Subprocess wrapper for the Gemini CLI. Raises `GeminiClientError` with classified reason codes: `quota_exceeded`, `auth_error`, `timeout`, `network_error`. |

---

### `tests/`

| File | Tools Covered |
|------|--------------|
| [`test_geocoding.py`](tests/test_geocoding.py) | `geocode`, `reverse_geocode`, `verify_address`, `autocomplete_address`, `parse_addresses` |
| [`test_risk.py`](tests/test_risk.py) | `get_flood_risk`, `get_wildfire_risk`, `get_property_fire_risk`, `get_coastal_risk`, `get_earth_risk`, `get_historical_weather_risk` |
| [`test_property.py`](tests/test_property.py) | `get_property_data`, `get_parcels_by_address`, `get_parcel_by_owner_detailed`, `get_buildings_by_address`, `get_replacement_cost_by_address`, `get_property_attributes_by_address` |
| [`test_demographics.py`](tests/test_demographics.py) | `get_demographics`, `get_neighborhoods_by_address`, `get_schools_by_address`, `get_crime_index`, `get_places_by_address`, `get_psyte_geodemographics_by_address` |
| [`test_address_extended.py`](tests/test_address_extended.py) | `get_addresses_detailed`, `get_serviceability`, `get_ground_view_by_address`, `get_address_family` |
| [`test_utilities.py`](tests/test_utilities.py) | `verify_emails`, `parse_name`, `geo_locate_ip_address`, `geo_locate_wifi_access_point`, `find_emergency_services` |
| [`test_spatial.py`](tests/test_spatial.py) | `list_spatial_tables`, `get_table_metadata`, `find_nearest_candidates`, `search_at_location`, `overlap` |
| [`test_map_services.py`](tests/test_map_services.py) | `ogc_functions`, `ogc_collections`, `ogc_collection`, `ogc_collection_schema`, `ogc_collection_queryables`, `ogc_collection_items`, `wms_request`, `wmts_request` |
| [`test_broken_tools.py`](tests/test_broken_tools.py) | `validate_phones`, `get_timezones`, `get_spatial_products`, `lookup`, `summarize` *(routing-only — server-side errors)* |
| [`test_workflows.py`](tests/test_workflows.py) | Multi-tool chains: property due diligence, insurance underwriting, address enrichment, site selection, tax jurisdiction |
| [`test_llm_compat.py`](tests/test_llm_compat.py) | Same prompts sent to both LLMs — cross-LLM consistency checks |

---

### `data/`

| File | Purpose |
|------|---------|
| [`data/golden_addresses.json`](data/golden_addresses.json) | Six reference addresses with verified lat/lng: Precisely HQ (Troy NY), Empire State Building, SF Market St, Paradise CA, Miami Beach, White House. |
| [`data/test_prompts.json`](data/test_prompts.json) | Reusable prompt templates keyed by tool category with `{address}`, `{lat}`, `{lng}` placeholders. |

---

### `logs/`

| Path | Purpose |
|------|---------|
| [`logs/runs/`](logs/runs/) | Timestamped JSON trace files written by `log_result` fixture — one file per test, one folder per run. Includes raw model response, tool calls, and latency. |

---

### `weekly_reports/`

| File | Purpose |
|------|---------|
| [`week1_progress_report.md`](weekly_reports/week1_progress_report.md) | Week 1 progress |
| [`week2_checkin_report.md`](weekly_reports/week2_checkin_report.md) | Week 2 check-in: 51-tool coverage, Gemini validated, Claude partial trial |
| [`llm_compatibility_findings.md`](weekly_reports/llm_compatibility_findings.md) | Documented behavioral differences between Claude and Gemini |

---

## Broken Tools

5 tools have confirmed server-side bugs and cannot return valid responses. Their tests assert routing only — the LLM must call the right tool, but content is not checked.

| Tool | Error |
|------|-------|
| `validate_phones` | MCP schema error on all input formats |
| `get_timezones` | MCP schema error: dstOffset/timestamp/utcOffset must be object |
| `get_spatial_products` | MCP schema error: recommendedStyle must be string |
| `lookup` | MCP schema error: must have required property 'response' |
| `summarize` | Upstream 500 error (DIS-1003) |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key for Claude |
| `PRECISELY_MCP_URL` | `http://localhost:3000/mcp` | URL of the running Precisely MCP server |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model ID |
| `GEMINI_CMD` | `gemini` | Path or alias for the Gemini CLI binary |
