"""Top-level harness: plan, then execute, with subset routing and cost accounting.

    from harness import Harness
    result = Harness("claude").run("Assess wildfire and flood risk for 123 Main St, Napa CA")
    print(result["text"], result["cost_usd"], result["metrics"])

The flow is identical for every model:
  1. make_plan() on the same model — an ordered tool list.
  2. Subset routing — format only the planned tools' schemas (falls back to all tools if
     planning returned nothing). This is the single biggest token saver and the same
     change that keeps Llama under its context limit.
  3. run_loop() — execute, accumulating cross-round metrics and enforcing plan completion.
  4. Attach routing + cost.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from harness import mcp
from harness.adapters.base import ModelAdapter
from harness.loop import run_loop
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
    def __init__(self, model: str, model_id: str | None = None):
        self.name = model
        self.adapter: ModelAdapter = _make_adapter(model, model_id)
        self.raw_tools = mcp.list_raw_tools()
        self.system_prompt = _SYSTEM_PROMPT_PATH.read_text() if _SYSTEM_PROMPT_PATH.exists() else ""

    def run(self, prompt: str, max_tokens: int = 4096) -> dict:
        # 1. Plan on the same model.
        plan = make_plan(self.adapter, prompt, self.raw_tools)

        # 2. Subset routing — only the planned tools' schemas (fall back to all if planning failed).
        subset = [t for t in self.raw_tools if t["name"] in set(plan)] if plan else self.raw_tools
        tools = self.adapter.format_tools(subset)

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
