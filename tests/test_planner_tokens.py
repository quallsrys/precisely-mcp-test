"""Unit tests for the planner — runs with no network and no API keys."""

from harness.adapters.base import ModelAdapter, Turn
from harness.planner import make_plan, PlanResult


class FakePlannerAdapter(ModelAdapter):
    name = "fake"
    model_id = "fake-1"

    def __init__(self, turn):
        self._turn = turn

    def format_tools(self, raw_tools):
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
        return self._turn


def test_make_plan_returns_names_and_token_usage():
    turn = Turn(
        text='["geocode", "get_flood_risk_by_address"]',
        tool_calls=[],
        input_tokens=2693,
        output_tokens=31,
        raw=None,
    )
    adapter = FakePlannerAdapter(turn)
    raw_tools = [
        {"name": "geocode", "description": "Geocode an address."},
        {"name": "get_flood_risk_by_address", "description": "Flood risk for an address."},
    ]

    result = make_plan(adapter, "flood risk at 1 Main St", raw_tools)

    assert isinstance(result, PlanResult)
    assert result.names == ["geocode", "get_flood_risk_by_address"]
    assert result.input_tokens == 2693
    assert result.output_tokens == 31
