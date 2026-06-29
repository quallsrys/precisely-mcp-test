"""Top-level harness: plan, then execute, with subset routing, streaming, and cost.

    from harness import Harness
    h = Harness("claude")
    result = h.run("Assess flood risk for 123 Main St")          # blocking, full dict
    for event in h.run_stream("...", mode="harness"):            # streaming events
        ...

Modes:
  - "harness": plan (same model) -> subset-route -> execute. Planning tokens are counted.
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


VALID_MODES = ("harness", "naive")


def _make_adapter(model: str, model_id: str | None) -> ModelAdapter:
    """Import only the SDK for the requested model (paid SDKs aren't needed for a local Llama run)."""
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
        self.adapter: ModelAdapter = adapter or _make_adapter(model, model_id)
        self.raw_tools = raw_tools if raw_tools is not None else mcp.list_raw_tools()
        self.system_prompt = _SYSTEM_PROMPT_PATH.read_text() if _SYSTEM_PROMPT_PATH.exists() else ""

    def run_stream(self, prompt: str, mode: str = "harness", max_tokens: int = 4096):
        """Yield events for one run. mode is 'harness' (plan + subset) or 'naive' (all tools)."""
        if mode not in VALID_MODES:
            raise ValueError(f"Unknown mode '{mode}'. Choose from: {', '.join(VALID_MODES)}")
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
