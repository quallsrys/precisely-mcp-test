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

from pathlib import Path

from dotenv import load_dotenv

from harness import mcp
from harness.adapters.base import ModelAdapter
from harness.loop import run_loop
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
        result["cost_usd"] = _estimate_cost(self.name, m["input_tokens"], m["output_tokens"])
        return result
