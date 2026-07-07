# Harness Comparison App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Flask web app that runs one prompt on one selected model two ways — full harness vs naive loop — side-by-side with live streaming progress and a cost/tool/token delta.

**Architecture:** Refactor the loop into an event generator (`iter_loop`) that yields `planning → plan → round → tool_call → tool_result → answer → done`. `Harness.run_stream(prompt, mode)` orchestrates planning (harness mode only) then drains the generator. A Flask SSE endpoint iterates the generator directly; the browser opens two `EventSource` connections (one per panel). `Harness.run()` and the CLI keep working by consuming the same generator. Two integrity fixes fold in: tool-call errors become observations (not crashes), and planning tokens count toward metrics/cost.

**Tech Stack:** Python, Flask (new), Server-Sent Events, vanilla JS + marked.js (CDN). Existing: anthropic SDK, httpx, python-dotenv. All work happens under `precisely-mcp-test/`.

---

### Task 0: Initialize git for commits

The working directory is not a git repo, so the per-task commits below need a repo first.

- [ ] **Step 1: Initialize git and make a baseline commit**

```bash
cd /Users/nikhil/Documents/projects/AI-Harness
git init
printf '.venv/\n__pycache__/\n*.pyc\nprecisely-mcp-test/.env\nprecisely-mcp-test/logs/\n' > .gitignore
git add .gitignore
git commit -m "chore: initialize repo with gitignore"
```

Expected: a git repo with one commit. `.env` is ignored so the key is never committed.

---

### Task 1: Planner returns token usage (review fix #2)

`make_plan` currently throws away the planning call's token usage. Return it so cost accounting includes it.

**Files:**
- Modify: `precisely-mcp-test/harness/planner.py`
- Test: `precisely-mcp-test/tests/test_planner_tokens.py`

- [ ] **Step 1: Write the failing test**

Create `precisely-mcp-test/tests/test_planner_tokens.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd precisely-mcp-test && python3 -m pytest tests/test_planner_tokens.py -v`
Expected: FAIL — `ImportError: cannot import name 'PlanResult'`.

- [ ] **Step 3: Add `PlanResult` and change `make_plan` to return it**

In `precisely-mcp-test/harness/planner.py`, add the import and dataclass near the top (after the existing `import re`):

```python
from dataclasses import dataclass


@dataclass
class PlanResult:
    names: list[str]
    input_tokens: int = 0
    output_tokens: int = 0
```

Then replace the body of `make_plan` (the final `return _parse_plan(...)` line) so the whole function ends:

```python
def make_plan(adapter: ModelAdapter, prompt: str, raw_tools: list[dict], max_tokens: int = 1024) -> PlanResult:
    """Ask the model for an ordered tool plan plus the planning call's token usage.

    Returns PlanResult(names=[], ...) if planning fails — the caller falls back to
    sending all tools so the system still works.
    """
    valid_names = {t["name"] for t in raw_tools}
    tool_list = "\n".join(f"- {t['name']} — {_one_liner(t.get('description', ''))}" for t in raw_tools)

    user = PLANNING_TEMPLATE.format(prompt=prompt, tool_list=tool_list, taxonomy=TAXONOMY)
    messages = adapter.init_messages(user)
    turn = adapter.complete(PLANNING_SYSTEM, messages, tools=None, max_tokens=max_tokens)
    names = _parse_plan(turn.text, valid_names)
    return PlanResult(names=names, input_tokens=turn.input_tokens, output_tokens=turn.output_tokens)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd precisely-mcp-test && python3 -m pytest tests/test_planner_tokens.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add precisely-mcp-test/harness/planner.py precisely-mcp-test/tests/test_planner_tokens.py
git commit -m "feat(planner): return planning-call token usage in PlanResult"
```

---

### Task 2: Loop becomes an event generator with tool-error handling

Add `iter_loop` (generator) and keep `run_loop` as a thin consumer. Tool failures become `tool_result {ok: false}` observations fed back to the model. Planning tokens seed the metrics.

**Files:**
- Modify: `precisely-mcp-test/harness/loop.py`
- Test: `precisely-mcp-test/tests/test_loop_events.py`

- [ ] **Step 1: Write the failing tests**

Create `precisely-mcp-test/tests/test_loop_events.py`:

```python
"""Unit tests for the event loop — no network, no API keys (mcp.call_tool is patched)."""

import pytest

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd precisely-mcp-test && python3 -m pytest tests/test_loop_events.py -v`
Expected: FAIL — `AttributeError: module 'harness.loop' has no attribute 'iter_loop'`.

- [ ] **Step 3: Implement `iter_loop` and rewrite `run_loop` as a consumer**

Replace the entire body of `run_loop` in `precisely-mcp-test/harness/loop.py` (everything from `def run_loop(` to the end of the file) with:

```python
def iter_loop(
    adapter: ModelAdapter,
    system: str,
    prompt: str,
    plan: list[str],
    tools,
    max_tokens: int = 4096,
    plan_tokens: tuple[int, int] = (0, 0),
):
    """Execute the prompt to completion, yielding events as they happen.

    Events: round, tool_call, tool_result, answer, done. The final event is always
    'done' and carries the run result + summed metrics. `plan_tokens` seeds the metrics
    with the planning call's usage so cost accounting is honest.
    """
    if plan:
        prompt = (
            f"{prompt}\n\nYour plan for this request (call every tool, in order):\n"
            + "\n".join(f"{i}. {name}" for i, name in enumerate(plan, 1))
        )

    messages = adapter.init_messages(prompt)
    metrics = RunMetrics()
    metrics.input_tokens += plan_tokens[0]
    metrics.output_tokens += plan_tokens[1]
    planned = list(plan)
    called: set[str] = set()
    text = ""
    nudges = 0

    while metrics.rounds < MAX_ROUNDS:
        t0 = time.perf_counter()
        turn = adapter.complete(system, messages, tools, max_tokens)
        metrics.model_ms += (time.perf_counter() - t0) * 1000
        metrics.rounds += 1
        metrics.input_tokens += turn.input_tokens
        metrics.output_tokens += turn.output_tokens
        yield {"type": "round", "n": metrics.rounds,
               "tokens": {"in": turn.input_tokens, "out": turn.output_tokens}}

        if turn.text:
            text = turn.text
            yield {"type": "answer", "text": turn.text}

        if not turn.tool_calls:
            remaining = [p for p in planned if p not in called]
            if not remaining or nudges >= MAX_NUDGES:
                break
            nudges += 1
            adapter.add_user_message(messages, _nudge(remaining))
            continue

        adapter.add_assistant_turn(messages, turn)
        results = []
        for tc in turn.tool_calls:
            called.add(tc.name)
            yield {"type": "tool_call", "name": tc.name, "arguments": tc.arguments}
            t1 = time.perf_counter()
            try:
                output = mcp.call_tool(tc.name, tc.arguments)
                ok = True
            except Exception as e:                      # tool failure → observation, not crash
                output = f"ERROR calling {tc.name}: {e}"
                ok = False
            ms = (time.perf_counter() - t1) * 1000
            metrics.tool_ms += ms
            metrics.tool_calls += 1
            yield {"type": "tool_result", "name": tc.name,
                   "ms": round(ms), "ok": ok, "preview": output[:500]}
            results.append(ToolResult(call=tc, output=output))
        adapter.add_tool_results(messages, results)

    uncalled = [p for p in planned if p not in called]
    yield {
        "type": "done",
        "model": adapter.model_id,
        "text": text,
        "plan": planned,
        "tools_called": sorted(called),
        "plan_uncalled": uncalled,
        "plan_complete": not uncalled,
        "nudges": nudges,
        "metrics": metrics.as_dict(),
    }


def run_loop(
    adapter: ModelAdapter,
    system: str,
    prompt: str,
    plan: list[str],
    tools,
    max_tokens: int = 4096,
) -> dict:
    """Drain iter_loop and return the final 'done' payload (backward-compatible shape)."""
    result = {}
    for event in iter_loop(adapter, system, prompt, plan, tools, max_tokens):
        if event["type"] == "done":
            result = {k: v for k, v in event.items() if k != "type"}
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd precisely-mcp-test && python3 -m pytest tests/test_loop_events.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add precisely-mcp-test/harness/loop.py precisely-mcp-test/tests/test_loop_events.py
git commit -m "feat(loop): event-streaming iter_loop with tool-error recovery"
```

---

### Task 3: Harness.run_stream (planning + naive mode), run() on top

Add streaming orchestration and a `naive` mode. Make `Harness` injectable so it's unit-testable without the live server or keys.

**Files:**
- Modify: `precisely-mcp-test/harness/harness.py`
- Test: `precisely-mcp-test/tests/test_run_stream.py`

- [ ] **Step 1: Write the failing tests**

Create `precisely-mcp-test/tests/test_run_stream.py`:

```python
"""Unit tests for Harness.run_stream — adapter and raw_tools injected, mcp patched."""

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
    assert done["metrics"]["input_tokens"] == 200 + 50 + 30   # planning + both rounds
    assert done["cost_usd"] >= 0


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd precisely-mcp-test && python3 -m pytest tests/test_run_stream.py -v`
Expected: FAIL — `TypeError` on `Harness(... adapter=...)` (keyword not accepted) / `AttributeError: 'Harness' has no attribute 'run_stream'`.

- [ ] **Step 3: Rewrite `harness.py`**

Replace `precisely-mcp-test/harness/harness.py` entirely with:

```python
"""Top-level harness: plan, then execute, with subset routing, streaming, and cost.

    from harness import Harness
    h = Harness("claude")
    result = h.run("Assess flood risk for 123 Main St")          # blocking, full dict
    for event in h.run_stream("...", mode="harness"):            # streaming events
        ...

Modes:
  - "harness": plan (same model) → subset-route → execute. Planning tokens are counted.
  - "naive":   no planning, all tools sent every round. Baseline for comparison.
"""

from pathlib import Path

from dotenv import load_dotenv

from harness import mcp
from harness.adapters.base import ModelAdapter
from harness.loop import iter_loop
from harness.planner import make_plan

load_dotenv()

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "system_prompt.md"

VALID_MODELS = ("claude", "gemini", "openai", "llama")

# $ per 1M tokens (input, output). Llama runs locally — zero marginal cost.
PRICING = {
    "claude": (3.00, 15.00),
    "gemini": (1.25, 10.00),
    "openai": (0.15, 0.60),
    "llama": (0.0, 0.0),
}


def _make_adapter(model: str, model_id: str | None) -> ModelAdapter:
    if model == "claude":
        from harness.adapters.claude import ClaudeAdapter
        return ClaudeAdapter(model_id)
    if model == "gemini":
        from harness.adapters.gemini import GeminiAdapter
        return GeminiAdapter(model_id)
    if model == "openai":
        from harness.adapters.openai import OpenAIAdapter
        return OpenAIAdapter(model_id)
    if model == "llama":
        from harness.adapters.llama import LlamaAdapter
        return LlamaAdapter(model_id)
    raise ValueError(f"Unknown model '{model}'. Choose from: {', '.join(VALID_MODELS)}")


def _estimate_cost(name: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = PRICING.get(name, (0.0, 0.0))
    return round(input_tokens / 1_000_000 * in_rate + output_tokens / 1_000_000 * out_rate, 6)


class Harness:
    def __init__(self, model: str, model_id: str | None = None, *,
                 adapter: ModelAdapter | None = None, raw_tools: list[dict] | None = None):
        self.name = model
        self.adapter = adapter or _make_adapter(model, model_id)
        self.raw_tools = raw_tools if raw_tools is not None else mcp.list_raw_tools()
        self.system_prompt = _SYSTEM_PROMPT_PATH.read_text() if _SYSTEM_PROMPT_PATH.exists() else ""

    def run_stream(self, prompt: str, mode: str = "harness", max_tokens: int = 4096):
        """Yield events for one run. mode is 'harness' (plan + subset) or 'naive' (all tools)."""
        if mode == "harness":
            yield {"type": "planning"}
            pr = make_plan(self.adapter, prompt, self.raw_tools)
            yield {"type": "plan", "plan": pr.names,
                   "tokens": {"in": pr.input_tokens, "out": pr.output_tokens}}
            subset = [t for t in self.raw_tools if t["name"] in set(pr.names)] if pr.names else self.raw_tools
            plan_names = pr.names
            plan_tokens = (pr.input_tokens, pr.output_tokens)
        else:  # naive
            subset = self.raw_tools
            plan_names = []
            plan_tokens = (0, 0)

        tools = self.adapter.format_tools(subset)
        for event in iter_loop(self.adapter, self.system_prompt, prompt,
                               plan_names, tools, max_tokens, plan_tokens=plan_tokens):
            if event["type"] == "done":
                m = event["metrics"]
                event["cost_usd"] = _estimate_cost(self.name, m["input_tokens"], m["output_tokens"])
                event["model_name"] = self.name
                event["tools_sent"] = len(subset)
                event["tools_available"] = len(self.raw_tools)
                event["mode"] = mode
            yield event

    def run(self, prompt: str, max_tokens: int = 4096, mode: str = "harness") -> dict:
        """Blocking run — drains run_stream and returns the final 'done' payload."""
        result = {}
        for event in self.run_stream(prompt, mode=mode, max_tokens=max_tokens):
            if event["type"] == "done":
                result = {k: v for k, v in event.items() if k != "type"}
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd precisely-mcp-test && python3 -m pytest tests/test_run_stream.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Verify the CLI still works (no regression)**

Run: `cd precisely-mcp-test && python3 -c "from harness import Harness; from harness.cli import _ask; print('imports OK')"`
Expected: prints `imports OK` (cli.py uses `r["plan"]`, `r["text"]`, `r["metrics"]`, `r["plan_complete"]`, `r["plan_uncalled"]`, `r["tools_called"]`, `r["cost_usd"]` — all still present in the run() dict).

- [ ] **Step 6: Commit**

```bash
git add precisely-mcp-test/harness/harness.py precisely-mcp-test/tests/test_run_stream.py
git commit -m "feat(harness): run_stream with naive mode and injectable deps"
```

---

### Task 4: Flask app — model list + SSE stream

**Files:**
- Create: `precisely-mcp-test/harness/app.py`
- Modify: `precisely-mcp-test/requirements.txt`
- Test: `precisely-mcp-test/tests/test_app.py`

- [ ] **Step 1: Add dependencies**

Append to `precisely-mcp-test/requirements.txt`:

```
flask>=3.0.0
openai>=1.0.0
google-genai>=0.3.0
```

Then install Flask now (the other two are for future non-Claude panels):

```bash
cd precisely-mcp-test && python3 -m pip install "flask>=3.0.0"
```

- [ ] **Step 2: Write the failing test**

Create `precisely-mcp-test/tests/test_app.py`:

```python
"""Unit tests for the Flask app — model availability + SSE plumbing, no live model."""

import json

from harness import app as app_mod


def test_available_models_reports_claude_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    models = app_mod.get_available_models()
    by_name = {m["name"]: m for m in models}
    assert by_name["claude"]["available"] is True
    assert by_name["openai"]["available"] is False
    assert "reason" in by_name["openai"]


def test_models_endpoint_returns_json():
    client = app_mod.create_app().test_client()
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert {m["name"] for m in data} == {"claude", "gemini", "openai", "llama"}


def test_stream_endpoint_emits_sse_done_event(monkeypatch):
    # Replace the harness factory with a fake that yields one done event.
    def fake_factory(model):
        class FakeHarness:
            def run_stream(self, prompt, mode="harness", max_tokens=4096):
                yield {"type": "done", "text": "hi", "mode": mode, "metrics": {}, "cost_usd": 0.0}
        return FakeHarness()
    monkeypatch.setattr(app_mod, "_harness", fake_factory)

    client = app_mod.create_app().test_client()
    resp = client.get("/api/stream?model=claude&mode=harness&prompt=hello")
    body = resp.get_data(as_text=True)
    assert "data:" in body
    # The last data frame parses as the done event.
    frames = [line[len("data:"):].strip() for line in body.splitlines() if line.startswith("data:")]
    last = json.loads(frames[-1])
    assert last["type"] == "done"
    assert last["mode"] == "harness"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd precisely-mcp-test && python3 -m pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness.app'`.

- [ ] **Step 4: Implement the Flask app**

Create `precisely-mcp-test/harness/app.py`:

```python
"""Flask app: compare a model's full-harness run vs a naive-loop run, side-by-side.

    cd precisely-mcp-test && python3 -m harness.app
    open http://localhost:5001

Routes:
    GET /                     serve the single-page UI
    GET /api/models           which models are configured/usable
    GET /api/stream?model=&mode=&prompt=   one streaming run (Server-Sent Events)
"""

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from flask import Flask, Response, request

from harness import mcp
from harness.harness import Harness, VALID_MODELS

load_dotenv()

_UI_PATH = Path(__file__).parent.parent / "ui" / "index.html"
_RAW_TOOLS: list[dict] | None = None


def _get_raw_tools() -> list[dict]:
    """Fetch the MCP tool list once and cache it for the process."""
    global _RAW_TOOLS
    if _RAW_TOOLS is None:
        _RAW_TOOLS = mcp.list_raw_tools()
    return _RAW_TOOLS


def _harness(model: str) -> Harness:
    """Build a Harness sharing the cached tool list (overridable in tests)."""
    return Harness(model, raw_tools=_get_raw_tools())


def get_available_models() -> list[dict]:
    """Report each model's availability so the UI can disable unconfigured ones."""
    out = []
    for name in VALID_MODELS:
        if name == "claude":
            ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
            reason = "" if ok else "ANTHROPIC_API_KEY not set"
        elif name == "openai":
            ok = bool(os.environ.get("OPENAI_API_KEY"))
            reason = "" if ok else "OPENAI_API_KEY not set"
        elif name == "gemini":
            ok = bool(os.environ.get("GEMINI_API_KEY"))
            reason = "" if ok else "GEMINI_API_KEY not set"
        else:  # llama
            base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
            try:
                httpx.get(base.replace("/v1", "") + "/api/tags", timeout=1.5)
                ok, reason = True, ""
            except Exception:
                ok, reason = False, "Ollama not reachable"
        out.append({"name": name, "available": ok, "reason": reason})
    return out


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return _UI_PATH.read_text(), 200, {"Content-Type": "text/html"}

    @app.get("/api/models")
    def models():
        return Response(json.dumps(get_available_models()), mimetype="application/json")

    @app.get("/api/stream")
    def stream():
        model = request.args.get("model", "claude")
        mode = request.args.get("mode", "harness")
        prompt = request.args.get("prompt", "")

        def generate():
            try:
                if model not in VALID_MODELS:
                    raise ValueError(f"unknown model '{model}'")
                for event in _harness(model).run_stream(prompt, mode=mode):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'where': 'run', 'message': str(e)})}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def main() -> None:
    create_app().run(host="127.0.0.1", port=5001, threaded=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd precisely-mcp-test && python3 -m pytest tests/test_app.py -v`
Expected: PASS (3 tests). Note: `test_stream_endpoint_emits_sse_done_event` patches `_harness`, so no live model/server is needed.

- [ ] **Step 6: Commit**

```bash
git add precisely-mcp-test/harness/app.py precisely-mcp-test/tests/test_app.py precisely-mcp-test/requirements.txt
git commit -m "feat(app): Flask SSE endpoints for model availability and streaming runs"
```

---

### Task 5: Single-page UI

A front-end page; verified manually (no unit test — it's browser JS).

**Files:**
- Create: `precisely-mcp-test/ui/index.html`

- [ ] **Step 1: Create the UI**

Create `precisely-mcp-test/ui/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Harness Comparison — Precisely MCP</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    :root { font-family: -apple-system, system-ui, sans-serif; }
    body { margin: 0; background: #0f1116; color: #e6e8eb; }
    header { padding: 16px 24px; border-bottom: 1px solid #232733; }
    h1 { font-size: 18px; margin: 0; }
    .controls { padding: 16px 24px; display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
    textarea { flex: 1; min-width: 320px; min-height: 56px; background: #161922; color: #e6e8eb;
               border: 1px solid #2a2f3a; border-radius: 8px; padding: 10px; font-size: 14px; }
    .models { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
    label.model { font-size: 13px; opacity: 0.9; }
    label.model[aria-disabled="true"] { opacity: 0.4; }
    button { background: #3b82f6; color: white; border: 0; border-radius: 8px; padding: 10px 18px;
             font-size: 14px; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .panels { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 0 24px 24px; }
    .panel { background: #161922; border: 1px solid #2a2f3a; border-radius: 10px; padding: 16px; }
    .panel h2 { font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; margin: 0 0 10px; color: #9aa4b2; }
    .steps { font-size: 12px; font-family: ui-monospace, monospace; color: #9aa4b2; max-height: 180px;
             overflow: auto; border: 1px solid #232733; border-radius: 6px; padding: 8px; margin-bottom: 12px; }
    .step.err { color: #f87171; }
    .step.ok { color: #34d399; }
    .answer { font-size: 14px; line-height: 1.5; }
    .answer table { border-collapse: collapse; }
    .answer th, .answer td { border: 1px solid #2a2f3a; padding: 4px 8px; }
    .metrics { margin-top: 12px; font-size: 12px; color: #9aa4b2; font-family: ui-monospace, monospace; }
    .delta { padding: 12px 24px; font-size: 13px; color: #cbd5e1; }
    .pill { display: inline-block; background: #232733; border-radius: 999px; padding: 2px 8px; margin: 2px; font-size: 12px; }
  </style>
</head>
<body>
  <header><h1>Harness vs Naive — Precisely MCP comparison</h1></header>

  <div class="controls">
    <textarea id="prompt" placeholder="e.g. Assess wildfire and flood risk for 950 Josephine St, Denver CO, for an insurance adjuster."></textarea>
    <div>
      <div class="models" id="models"></div>
      <button id="run">Run comparison</button>
    </div>
  </div>

  <div class="delta" id="delta"></div>

  <div class="panels">
    <div class="panel"><h2>Harness</h2><div class="steps" id="steps-harness"></div>
      <div class="answer" id="answer-harness"></div><div class="metrics" id="metrics-harness"></div></div>
    <div class="panel"><h2>Naive</h2><div class="steps" id="steps-naive"></div>
      <div class="answer" id="answer-naive"></div><div class="metrics" id="metrics-naive"></div></div>
  </div>

  <script>
    const doneState = {};

    async function loadModels() {
      const res = await fetch('/api/models');
      const models = await res.json();
      const box = document.getElementById('models');
      models.forEach((m, i) => {
        const lab = document.createElement('label');
        lab.className = 'model';
        if (!m.available) lab.setAttribute('aria-disabled', 'true');
        const firstAvailable = models.find(x => x.available);
        const checked = m.available && m === firstAvailable ? 'checked' : '';
        const dis = m.available ? '' : 'disabled';
        const tag = m.available ? '' : ` (${m.reason})`;
        lab.innerHTML = `<input type="radio" name="model" value="${m.name}" ${checked} ${dis}> ${m.name}${tag}`;
        box.appendChild(lab);
      });
    }

    function step(panel, text, cls) {
      const el = document.getElementById('steps-' + panel);
      const d = document.createElement('div');
      d.className = 'step' + (cls ? ' ' + cls : '');
      d.textContent = text;
      el.appendChild(d);
      el.scrollTop = el.scrollHeight;
    }

    function handle(panel, ev) {
      if (ev.type === 'planning') step(panel, '⋯ planning');
      else if (ev.type === 'plan') step(panel, '✓ plan: ' + ev.plan.join(' → '));
      else if (ev.type === 'round') step(panel, '↻ round ' + ev.n + '  (' + ev.tokens.in + ' in / ' + ev.tokens.out + ' out)');
      else if (ev.type === 'tool_call') step(panel, '→ ' + ev.name);
      else if (ev.type === 'tool_result') step(panel, (ev.ok ? '✓ ' : '✗ ') + ev.name + '  ' + ev.ms + 'ms', ev.ok ? 'ok' : 'err');
      else if (ev.type === 'answer') document.getElementById('answer-' + panel).innerHTML = marked.parse(ev.text || '');
      else if (ev.type === 'error') step(panel, '✗ ERROR: ' + ev.message, 'err');
      else if (ev.type === 'done') {
        const m = ev.metrics || {};
        const secs = ((m.model_ms || 0) + (m.tool_ms || 0)) / 1000;
        document.getElementById('metrics-' + panel).textContent =
          `tools: ${(ev.tools_called || []).join(', ') || 'none'}  |  ` +
          `${(m.input_tokens || 0).toLocaleString()} in / ${(m.output_tokens || 0).toLocaleString()} out  |  ` +
          `${m.rounds || 0} rounds  |  $${ev.cost_usd}  |  ${secs.toFixed(1)}s  |  sent ${ev.tools_sent}/${ev.tools_available} tools`;
        doneState[panel] = ev;
        renderDelta();
      }
    }

    function renderDelta() {
      if (!doneState.harness || !doneState.naive) return;
      const h = doneState.harness, n = doneState.naive;
      const pct = (a, b) => b ? Math.round((a - b) / b * 100) : 0;
      const dCost = pct(h.cost_usd, n.cost_usd);
      const dTok = pct(h.metrics.input_tokens, n.metrics.input_tokens);
      const dTools = (h.tools_called || []).length - (n.tools_called || []).length;
      document.getElementById('delta').innerHTML =
        `<b>Delta (harness vs naive):</b> ` +
        `<span class="pill">cost ${dCost >= 0 ? '+' : ''}${dCost}%</span>` +
        `<span class="pill">input tokens ${dTok >= 0 ? '+' : ''}${dTok}%</span>` +
        `<span class="pill">tools ${dTools >= 0 ? '+' : ''}${dTools}</span>`;
    }

    function openStream(panel, model, prompt) {
      const url = `/api/stream?model=${encodeURIComponent(model)}&mode=${panel}&prompt=${encodeURIComponent(prompt)}`;
      const es = new EventSource(url);
      es.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        handle(panel, ev);
        if (ev.type === 'done' || ev.type === 'error') es.close();
      };
      es.onerror = () => es.close();
    }

    document.getElementById('run').addEventListener('click', () => {
      const prompt = document.getElementById('prompt').value.trim();
      const model = (document.querySelector('input[name=model]:checked') || {}).value;
      if (!prompt || !model) return;
      ['harness', 'naive'].forEach(p => {
        document.getElementById('steps-' + p).innerHTML = '';
        document.getElementById('answer-' + p).innerHTML = '';
        document.getElementById('metrics-' + p).textContent = '';
        delete doneState[p];
      });
      document.getElementById('delta').innerHTML = '';
      openStream('harness', model, prompt);
      openStream('naive', model, prompt);
    });

    loadModels();
  </script>
</body>
</html>
```

- [ ] **Step 2: Manual smoke test (UI loads)**

Start the MCP server if not running (separate terminal):
```bash
cd /Users/nikhil/precisely-mcp-server/dis-locate-apis-v2 && .venv/bin/python -m mcp_servers --transport http --port 3000
```
Start the app:
```bash
cd /Users/nikhil/Documents/projects/AI-Harness/precisely-mcp-test && python3 -m harness.app
```
Open http://localhost:5001 — confirm the page loads, the prompt box and a "claude" radio appear, other models show "(… not set)".

- [ ] **Step 3: Commit**

```bash
git add precisely-mcp-test/ui/index.html
git commit -m "feat(ui): side-by-side harness-vs-naive comparison page"
```

---

### Task 6: End-to-end verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full unit suite**

Run: `cd precisely-mcp-test && python3 -m pytest tests/test_planner_tokens.py tests/test_loop_events.py tests/test_run_stream.py tests/test_app.py -v`
Expected: all PASS, no live server or keys required.

- [ ] **Step 2: Live comparison run**

With the MCP server on :3000 and `ANTHROPIC_API_KEY` in `precisely-mcp-test/.env`, open http://localhost:5001, select claude, enter:
`Assess wildfire and flood risk for 950 Josephine St, Denver CO, and summarize for an insurance adjuster.`
Click Run.

Expected:
- Harness panel: `planning` → `plan: verify_address → …` → tool calls stream → answer renders → metrics show `sent 3/70 tools`.
- Naive panel: no planning line → likely more/different tool calls → `sent 70/70 tools`.
- Delta footer shows cost/token/tool differences once both finish.
- If naive routes to a known-broken tool, the panel shows a red `✗ <tool>` line but the run still completes (tool-error recovery).

- [ ] **Step 3: Confirm cost honesty**

Verify the harness panel's `$cost` is higher than the old pre-fix number for the same prompt (planning tokens now included). This is the visible proof of review fix #2.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "docs: comparison app verified end-to-end"
```

---

## Notes for the implementer

- All unit tests avoid the network and API keys by injecting a scripted adapter and monkeypatching `mcp.call_tool` / `make_plan`. Only Task 5 Step 2 and Task 6 Step 2 need the live server + key.
- `EventSource` only does GET, so the prompt rides in the query string — fine for demo-length prompts.
- The MCP server's default port is 8000; this app and harness assume **3000**. Start the server with `--port 3000` (Task 5 Step 2).
- Do not commit `precisely-mcp-test/.env` — it holds the API key and is gitignored in Task 0.
