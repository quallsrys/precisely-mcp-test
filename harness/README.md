# Harness

A model-agnostic agent harness for the Precisely MCP toolset. One shared agentic loop
drives Claude, Gemini, GPT, or local Llama — the per-model code is a thin adapter that
only formats tools going in and parses responses coming out.

## Usage

```python
from harness import Harness

result = Harness("claude").run(
    "Assess wildfire and flood risk for 123 Main St, Napa CA, and summarize for an adjuster."
)

print(result["text"])           # the answer
print(result["plan"])           # ordered tools the planner chose
print(result["tools_called"])   # tools actually executed
print(result["plan_uncalled"])  # planned but skipped (capability signal; usually empty)
print(result["metrics"])        # rounds, tool_calls, input/output tokens, model_ms, tool_ms
print(result["cost_usd"])       # estimated $ for this run
```

Models: `"claude"`, `"gemini"`, `"openai"`, `"llama"`. Keys come from `../.env`.

## How a run works

```
Harness.run(prompt)
  │
  ├─ 1. make_plan()      same model, NO tool schemas — just names + one-line summaries.
  │                      Returns an ordered tool list. (Empty plan → fall back to all tools.)
  │
  ├─ 2. subset routing   format ONLY the planned tools' schemas. Biggest token saver,
  │                      and what keeps Llama under its context limit.
  │
  └─ 3. run_loop()       execute round by round. Accumulates metrics across EVERY round,
                         and will not terminate while planned tools remain uncalled
                         (capped at MAX_NUDGES, then records the gap).
```

## Design decisions

- **Planning runs on every model, on the same model that executes.** No model depends on
  another — a customer can run the whole flow on their existing stack.
- **One universal system prompt** (`../system_prompt.md`), loaded once by the harness.
  The "call every tool in your plan" rule lives there, not in per-model code.
- **No scenario playbooks.** The planner reasons about completeness from tool descriptions
  + a structural taxonomy, so it generalizes to any request instead of overfitting the
  known benchmark prompts (which stay a blind test set).
- **No code-fabricated tool calls.** Enforcement is refuse-to-terminate: the loop nudges
  the model to finish its plan; the model still produces every argument.
- **Metrics are summed across all rounds**, unlike the old per-client code that reported
  only the final round.

## Files

| File | Responsibility |
|---|---|
| `mcp.py` | JSON-RPC transport to the MCP server (shared) |
| `schema.py` | flatten JSON-Schema combinators (shared) |
| `adapters/base.py` | `ModelAdapter` interface + `Turn`/`ToolCall`/`ToolResult` |
| `adapters/{claude,gemini,openai,llama}.py` | per-model format-in / parse-out |
| `planner.py` | universal planning step |
| `loop.py` | shared agentic loop, metrics, refuse-to-terminate |
| `harness.py` | top-level orchestration, subset routing, cost |

## Not yet implemented (see `weekly_reports/week4_architecture_notes.md`)

Prompt caching, tool-result trimming, execution-time schema compression, planning
self-critique. The loop and adapters are structured so these slot in without touching
the model-specific code.
