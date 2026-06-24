"""Shared fixtures for Precisely MCP test suite."""

import json
import os
import re
import pytest
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Session-wide results store populated by log_result; read by pytest_terminal_summary.
_SESSION_RESULTS: list[dict] = []


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


@pytest.fixture(scope="session")
def openai_client():
    from clients.openai_client import OpenAIClient
    return OpenAIClient()


@pytest.fixture(scope="session")
def llama_client():
    from clients.llama_client import LlamaClient
    return LlamaClient()


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
    """Write a JSON trace for each test and record a summary row for the terminal report."""
    traces = []

    def _log(data: dict):
        traces.append(data)

    yield _log

    if traces:
        filename = _clean_name(request.node.nodeid)
        out_file = run_dir / f"{filename}.json"
        with open(out_file, "w") as f:
            json.dump(traces, f, indent=2)

        # Build a summary row for the terminal report from the first trace entry.
        entry = traces[0]
        # Tests log as {"llm": "claude", "result": {...}} — unwrap if needed
        result = entry.get("result", entry)

        tool_calls = result.get("tool_calls", [])
        tool_names = [t["name"] for t in tool_calls]
        unique_tools = list(dict.fromkeys(tool_names))  # deduplicate, preserve order

        usage = result.get("usage", {})
        tokens_in = usage.get("input_tokens")
        tokens_out = usage.get("output_tokens")

        _SESSION_RESULTS.append({
            "node_id": request.node.nodeid,
            "label": filename,
            "llm": entry.get("llm", result.get("model", "?")),
            "tools": unique_tools,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": result.get("latency_ms"),
        })


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print a formatted tool + token summary table after the run."""
    if not _SESSION_RESULTS:
        return

    tw = terminalreporter
    tw.write_sep("=", "MCP Tool Coverage & Token Summary")

    # Column widths
    W_LABEL = 52
    W_LLM = 8
    W_TOOLS = 46
    W_TOKENS = 22

    header = (
        f"{'Test':<{W_LABEL}}  {'LLM':<{W_LLM}}  {'Tools Called':<{W_TOOLS}}  {'Tokens In / Out':<{W_TOKENS}}"
    )
    tw.write_line(header)
    tw.write_line("─" * (W_LABEL + W_LLM + W_TOOLS + W_TOKENS + 6))

    for row in _SESSION_RESULTS:
        # Shorten label: drop the llm__ prefix since it's in the LLM column
        label = row["label"]
        label = re.sub(r"^(claude|gemini)__", "", label).replace("__", " / ")
        label = label[:W_LABEL]

        llm = str(row["llm"])
        if "claude" in llm.lower():
            llm = "claude"
        elif "gemini" in llm.lower():
            llm = "gemini"

        tools = row["tools"]
        tool_str = f"{', '.join(tools)} ({len(tools)})" if tools else "none (0)"
        tool_str = tool_str[:W_TOOLS]

        t_in = row["tokens_in"]
        t_out = row["tokens_out"]
        if t_in is not None and t_out is not None:
            token_str = f"{t_in:,} / {t_out:,}"
        else:
            token_str = "N/A"

        tw.write_line(
            f"{label:<{W_LABEL}}  {llm:<{W_LLM}}  {tool_str:<{W_TOOLS}}  {token_str:<{W_TOKENS}}"
        )
