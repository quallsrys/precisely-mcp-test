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

import os
from pathlib import Path

from dotenv import load_dotenv

from harness import mcp
from harness.adapters.base import ModelAdapter
from harness.loop import iter_loop
from harness.planner import make_plan

load_dotenv()

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "system_prompt.md"

VALID_MODELS = ("claude", "gemini", "openai", "llama")

# Standard (list) USD per 1M tokens (input, output), verified against provider pricing
# pages in June 2026. Keyed by EXACT model id so switching models reprices correctly.
#
# Enterprise/committed-use rates are negotiated and not published — there is no public
# per-token enterprise card. Apply your org's negotiated discount via ENTERPRISE_DISCOUNT
# (e.g. 0.30 = 30% off list). Batch API is a flat -50% and prompt caching cuts cached
# input ~75-90%, but those aren't modeled here yet (the loop doesn't batch or cache).
PRICING = {
    # Anthropic
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5": (10.00, 50.00),
    # OpenAI (gpt-5.x current; gpt-4o-mini is legacy)
    "gpt-5.5": (5.00, 30.00),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-4o-mini": (0.15, 0.60),
    # Google (Gemini 2.5 Pro shown at the <=200k-token tier; >200k is 2.50/15.00)
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    # Local — zero marginal cost
    "llama3.1:8b-16k": (0.0, 0.0),
    "llama3.1:8b": (0.0, 0.0),
    "llama3.2:latest": (0.0, 0.0),
}

# Fraction off list to apply to every cost estimate. 0.0 = list price (the verifiable,
# demo-safe default); set to your negotiated rate, e.g. 0.30, via the env var.
ENTERPRISE_DISCOUNT = float(os.environ.get("ENTERPRISE_DISCOUNT", "0.0"))


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


def _estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    """Cost in USD for this run, or None if the model id isn't in the pricing table.

    Returns None rather than a fake $0 so an unpriced model is visibly flagged instead of
    silently looking free.
    """
    rates = PRICING.get(model_id)
    if rates is None:
        return None
    in_rate, out_rate = rates
    cost = input_tokens / 1_000_000 * in_rate + output_tokens / 1_000_000 * out_rate
    return round(cost * (1 - ENTERPRISE_DISCOUNT), 6)


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

        # 3. Execute.
        result = run_loop(self.adapter, self.system_prompt, prompt, plan, tools, max_tokens)

        # 4. Annotate with routing + cost.
        m = result["metrics"]
        result["model_name"] = self.name
        result["tools_sent"] = len(subset)
        result["tools_available"] = len(self.raw_tools)
        result["cost_usd"] = _estimate_cost(self.adapter.model_id, m["input_tokens"], m["output_tokens"])
        result["cost_basis"] = "list" if ENTERPRISE_DISCOUNT == 0 else f"enterprise (-{ENTERPRISE_DISCOUNT:.0%})"
        return result
