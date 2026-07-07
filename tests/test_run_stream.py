"""Unit tests for Harness.run_stream — adapter and raw_tools injected, mcp patched."""

import pytest

from harness import harness as harness_mod
from harness.harness import Harness
from harness.planner import PlanResult
from harness.adapters.base import ModelAdapter, ToolCall, Turn


class ScriptedAdapter(ModelAdapter):
    name = "fake"
    model_id = "fake-1"

    def __init__(self, turns):
        self._turns = list(turns)
        self.tools_formatted = None

    def format_tools(self, raw_tools):
        self.tools_formatted = raw_tools
        return raw_tools

    def init_messages(self, prompt):
        return [{"role": "user", "content": prompt}]

    def add_user_message(self, messages, text):
        messages.append({"role": "user", "content": text})

    def add_assistant_turn(self, messages, turn):
        messages.append({"role": "assistant"})

    def add_tool_results(self, messages, results):
        messages.append({"role": "tool"})

    def complete(self, system, messages, tools, max_tokens):
        return self._turns.pop(0)


RAW_TOOLS = [
    {"name": "geocode", "description": "Geocode."},
    {"name": "get_flood_risk_by_address", "description": "Flood."},
    {"name": "get_demographics", "description": "Demographics."},
]


def _harness(adapter):
    return Harness("fake", adapter=adapter, raw_tools=RAW_TOOLS)


def test_harness_mode_emits_planning_and_plan_with_cost(monkeypatch):
    monkeypatch.setattr(harness_mod, "make_plan",
                        lambda a, p, t: PlanResult(["geocode"], 200, 10))
    monkeypatch.setattr(harness_mod.mcp, "call_tool", lambda n, a: "OK")
    adapter = ScriptedAdapter([
        Turn("", [ToolCall("geocode", {}, "t1")], 50, 5, None),
        Turn("Answer.", [], 30, 8, None),
    ])

    events = list(_harness(adapter).run_stream("flood risk", mode="harness"))
    types = [e["type"] for e in events]

    assert types[0] == "planning"
    assert "plan" in types
    plan_event = next(e for e in events if e["type"] == "plan")
    assert plan_event["plan"] == ["geocode"]
    assert plan_event["tokens"] == {"in": 200, "out": 10}
    done = events[-1]
    assert done["mode"] == "harness"
    assert done["tools_sent"] == 1                      # subset routing: only planned tool
    assert adapter.tools_formatted == [RAW_TOOLS[0]]    # exactly the planned tool was sent
    assert done["metrics"]["input_tokens"] == 200 + 50 + 30   # planning + both rounds
    assert done["cost_usd"] >= 0


def test_empty_plan_falls_back_to_all_tools(monkeypatch):
    # Planning returned nothing -> send all tools so the run still works.
    monkeypatch.setattr(harness_mod, "make_plan",
                        lambda a, p, t: PlanResult([], 120, 6))
    monkeypatch.setattr(harness_mod.mcp, "call_tool", lambda n, a: "OK")
    adapter = ScriptedAdapter([Turn("Answer.", [], 25, 4, None)])

    events = list(_harness(adapter).run_stream("flood risk", mode="harness"))
    done = events[-1]

    assert done["tools_sent"] == len(RAW_TOOLS)         # fallback: all tools
    assert adapter.tools_formatted == RAW_TOOLS
    assert done["metrics"]["input_tokens"] == 120 + 25  # planning tokens still counted


def test_invalid_mode_raises(monkeypatch):
    adapter = ScriptedAdapter([Turn("Answer.", [], 1, 1, None)])
    with pytest.raises(ValueError):
        list(_harness(adapter).run_stream("x", mode="harnes"))


def test_naive_mode_skips_planning_and_sends_all_tools(monkeypatch):
    monkeypatch.setattr(harness_mod.mcp, "call_tool", lambda n, a: "OK")
    adapter = ScriptedAdapter([Turn("Answer.", [], 40, 9, None)])

    events = list(_harness(adapter).run_stream("flood risk", mode="naive"))
    types = [e["type"] for e in events]

    assert "planning" not in types
    assert "plan" not in types
    done = events[-1]
    assert done["mode"] == "naive"
    assert done["tools_sent"] == len(RAW_TOOLS)         # all tools, no subset
    assert done["metrics"]["input_tokens"] == 40        # no planning tokens added
