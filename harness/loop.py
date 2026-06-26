"""Shared agentic execution loop. Drives any ModelAdapter; never branches on the model.

Owns two things the per-client code did not:
  - Metrics accumulation across EVERY round. The old clients reported only the final
    round's token usage; this sums input/output tokens and times for all rounds.
  - The refuse-to-terminate rule. The loop will not end while planned tools remain
    uncalled — it nudges the model to finish its plan. Capped at MAX_NUDGES so a model
    that simply won't comply still terminates, and the unfinished tools are recorded as
    a capability signal rather than silently dropped. The harness never fabricates tool
    arguments; the model still produces every call.
"""

import time
from dataclasses import dataclass

from harness import mcp
from harness.adapters.base import ModelAdapter, ToolResult

MAX_ROUNDS = 25   # hard ceiling on model round-trips, guards against non-terminating loops
MAX_NUDGES = 3    # times we re-ask a model to finish its plan before giving up


@dataclass
class RunMetrics:
    rounds: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model_ms: float = 0.0
    tool_ms: float = 0.0

    def as_dict(self) -> dict:
        return {
            "rounds": self.rounds,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model_ms": round(self.model_ms),
            "tool_ms": round(self.tool_ms),
        }


def _nudge(remaining: list[str]) -> str:
    return (
        "You have not yet called these tools from your plan: "
        + ", ".join(remaining)
        + ". Call them now, or state explicitly why each cannot be called."
    )


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
            except Exception as e:                      # tool failure -> observation, not crash
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
