# Precisely MCP Test Suite

End-to-end tests for the **Precisely DIS / Locate APIs v2 MCP server**, covering geocoding, risk assessment, property intelligence, demographics, and multi-tool workflows. Tests run against Claude (via the Anthropic SDK) and optionally Gemini (via CLI) to verify both LLM integrations.

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
export PRECISELY_MCP_URL=http://localhost:3000/mcp   # or your hosted MCP URL
```

Run all tests:

```bash
pytest
```

---

## File Reference

### Root

| File | Purpose |
|------|---------|
| [`conftest.py`](conftest.py) | Shared pytest fixtures: `claude_client`, `gemini_client`, `golden_addresses`, `test_prompts`, and `log_result`. Loaded automatically by pytest for every test module. |
| [`pytest.ini`](pytest.ini) | Pytest configuration — sets `asyncio_mode = auto`, points pytest at the `tests/` directory, and enables console logging. |
| [`requirements.txt`](requirements.txt) | Python dependencies: `anthropic`, `pytest`, `pytest-asyncio`, `httpx`, and `python-dotenv`. |
| [`gemini.md`](gemini.md) | System prompt injected into every Gemini CLI call. Describes all available Precisely MCP tools and behavioral guidelines so Gemini knows when and how to call them. |

---

### `clients/`

| File | Purpose |
|------|---------|
| [`clients/__init__.py`](clients/__init__.py) | Makes `clients/` a Python package so fixtures can import from it. |
| [`clients/claude_client.py`](clients/claude_client.py) | Thin wrapper around the Anthropic SDK (`anthropic.Anthropic`). Connects to the Precisely MCP server via `mcp_servers`, sends a prompt, and returns a normalized dict with `text`, `tool_calls`, `stop_reason`, and `usage`. |
| [`clients/gemini_client.py`](clients/gemini_client.py) | Subprocess wrapper that calls the Gemini CLI (`gemini -p "..."`). Prepends the system prompt from `gemini.md`, captures stdout/stderr, and returns a normalized response dict. |

---

### `tests/`

| File | Purpose |
|------|---------|
| [`tests/__init__.py`](tests/__init__.py) | Makes `tests/` a Python package. |
| [`tests/test_geocoding.py`](tests/test_geocoding.py) | Tests `geocode`, `reverse_geocode`, `verify_address`, `autocomplete_address`, and `parse_addresses`. Parametrized across a range of prompts; also asserts that expected coordinates appear in Claude's response for golden addresses. |
| [`tests/test_risk.py`](tests/test_risk.py) | Tests flood, wildfire, property fire, coastal, earthquake, and historical weather risk tools. Includes a multi-risk summary test that expects at least 2 tool calls. |
| [`tests/test_property.py`](tests/test_property.py) | Tests `get_property_data`, `get_parcels_by_address`, `get_buildings_by_address`, `get_replacement_cost_by_address`, and `get_property_attributes_by_address`. Validates that property-family tool names appear in the response. |
| [`tests/test_demographics.py`](tests/test_demographics.py) | Tests `get_demographics`, `get_neighborhoods_by_address`, `get_schools_by_address`, `get_crime_index`, `get_places_by_address`, and `get_psyte_geodemographics_by_address`. |
| [`tests/test_workflows.py`](tests/test_workflows.py) | **Most important file.** Multi-tool integration scenarios: property due diligence, insurance underwriting, address enrichment, site selection, and tax jurisdiction lookup. Each test asserts that Claude chains ≥ 3 tools together. |
| [`tests/test_llm_compat.py`](tests/test_llm_compat.py) | Same natural-language prompts sent to both Claude and Gemini. Verifies that both LLMs return non-empty responses and that Claude calls at least one tool. Useful for catching regressions when upgrading models or switching providers. |

---

### `data/`

| File | Purpose |
|------|---------|
| [`data/golden_addresses.json`](data/golden_addresses.json) | Six well-known addresses with expected lat/lng values: Precisely HQ (Troy NY), Empire State Building, SF Market St, Paradise CA (wildfire), Miami Beach (coastal/flood), and the White House. Used in fixture-driven assertions. |
| [`data/test_prompts.json`](data/test_prompts.json) | Reusable natural-language prompt templates keyed by tool category (`geocode`, `flood_risk`, `demographics`, etc.). Use `{address}`, `{lat}`, `{lng}` placeholders — substitute values at test time. |

---

### `logs/`

| Path | Purpose |
|------|---------|
| [`logs/results/`](logs/results/) | Auto-generated JSON trace files, one per test, written by the `log_result` fixture in `conftest.py`. File names mirror the pytest node ID. Check this directory after a run to inspect raw model responses and tool call sequences. |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key for Claude |
| `PRECISELY_MCP_URL` | `http://localhost:3000/mcp` | URL of the running Precisely MCP server |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model ID to use |
| `GEMINI_CMD` | `gemini` | Path or alias for the Gemini CLI binary |

---

## Running Specific Test Files

```bash
pytest tests/test_workflows.py -v          # most important — run these first
pytest tests/test_geocoding.py -v
pytest tests/test_llm_compat.py -v         # requires Gemini CLI configured
pytest -k "flood" -v                       # run any test whose name contains "flood"
```
