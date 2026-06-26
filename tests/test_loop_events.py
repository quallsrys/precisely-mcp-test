"""Unit tests for the event loop — no network, no API keys (mcp.call_tool is patched)."""

from harness import loop
from harness.adapters.base import ModelAdapter, ToolCall, Turn


class ScriptedAdapter(ModelAdapter):
    """Returns a pre-scripted list of Turns, one per complete() call."""
    name = "fake"
    model_id = "fake-1"

    def __init__(self, turns):
        self._turns = list(turns)

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
        return self._turns.pop(0)


def _turn(text="", tool_calls=None, tin=10, tout=5):
    return Turn(text=text, tool_calls=tool_calls or [], input_tokens=tin, output_tokens=tout, raw=None)


def test_clean_run_emits_expected_event_sequence(monkeypatch):
    monkeypatch.setattr(loop.mcp, "call_tool", lambda name, args: "TOOL OK")
    adapter = ScriptedAdapter([
        _turn(tool_calls=[ToolCall(name="geocode", arguments={"a": 1}, id="t1")]),
        _turn(text="Final answer."),
    ])

    events = list(loop.iter_loop(adapter, "sys", "do it", ["geocode"], tools=[]))
    types = [e["type"] for e in events]

    assert types == ["round", "tool_call", "tool_result", "round", "answer", "done"]
    tr = next(e for e in events if e["type"] == "tool_result")
    assert tr["ok"] is True and tr["name"] == "geocode"
    done = events[-1]
    assert done["plan_complete"] is True
    assert done["tools_called"] == ["geocode"]
    assert done["text"] == "Final answer."


def test_tool_failure_is_recorded_and_run_recovers(monkeypatch):
    def boom(name, args):
        raise RuntimeError("schema error")
    monkeypatch.setattr(loop.mcp, "call_tool", boom)
    adapter = ScriptedAdapter([
        _turn(tool_calls=[ToolCall(name="validate_phones", arguments={}, id="t1")]),
        _turn(text="Recovered."),
    ])

    events = list(loop.iter_loop(adapter, "sys", "do it", ["validate_phones"], tools=[]))

    tr = next(e for e in events if e["type"] == "tool_result")
    assert tr["ok"] is False
    assert "ERROR" in tr["preview"]
    done = events[-1]
    assert done["type"] == "done"          # run reached completion, did not crash
    assert done["text"] == "Recovered."


def test_planning_tokens_seed_metrics(monkeypatch):
    monkeypatch.setattr(loop.mcp, "call_tool", lambda name, args: "OK")
    adapter = ScriptedAdapter([_turn(text="Answer.", tin=100, tout=20)])

    events = list(loop.iter_loop(adapter, "sys", "do it", [], tools=[], plan_tokens=(2000, 30)))
    done = events[-1]

    # metrics include the planning call's tokens (2000+100 in, 30+20 out)
    assert done["metrics"]["input_tokens"] == 2100
    assert done["metrics"]["output_tokens"] == 50
