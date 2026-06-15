"""Shared fixtures for Precisely MCP test suite."""

import json
import os
import re
import pytest
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def run_dir():
    """One timestamped folder per test run, shared across all tests in the session."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = Path(__file__).parent / "logs" / "runs" / timestamp
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def golden_addresses():
    with open(DATA_DIR / "golden_addresses.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def test_prompts():
    with open(DATA_DIR / "test_prompts.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def claude_client():
    from clients.claude_client import ClaudeClient
    return ClaudeClient()


@pytest.fixture(scope="session")
def gemini_client():
    from clients.gemini_client import GeminiClient
    return GeminiClient()


def _clean_name(node_id: str) -> str:
    """Convert a pytest node ID into a short readable filename.

    tests/test_geocoding.py::test_geocoding_gemini[geocode a specific address-...]
    → gemini__geocoding__geocode_a_specific_address
    """
    # Extract the parametrize label (everything inside [...]) if present
    label_match = re.search(r"\[([^\]]+)\]", node_id)
    label = label_match.group(1) if label_match else ""

    # Pull the label portion before the first '-' (that's our short human label)
    short_label = label.split("-")[0].strip() if "-" in label else label

    # Detect LLM from function name
    llm = "claude"
    if "gemini" in node_id:
        llm = "gemini"

    # Detect category from the test filename only (not the label, which can contain false matches)
    file_part = node_id.split("::")[0]
    category = "misc"
    for cat in ("geocoding", "risk", "property", "demographics", "workflows", "llm_compat"):
        if cat in file_part:
            category = cat
            break

    # Fall back to the test function name if no parametrize label
    if not short_label:
        fn_match = re.search(r"::(\w+)$", node_id)
        short_label = fn_match.group(1) if fn_match else "unknown"

    slug = re.sub(r"[^a-z0-9]+", "_", short_label.lower()).strip("_")
    return f"{llm}__{category}__{slug}"


@pytest.fixture
def log_result(request, run_dir):
    """Write a JSON trace for each test into the current run folder."""
    traces = []

    def _log(data: dict):
        traces.append(data)

    yield _log

    if traces:
        filename = _clean_name(request.node.nodeid)
        out_file = run_dir / f"{filename}.json"
        with open(out_file, "w") as f:
            json.dump(traces, f, indent=2)
