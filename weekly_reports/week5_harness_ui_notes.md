# Week 5 — Harness UI & Comparison App
**Precisely MCP Server — Intern Project**
July 7, 2026

---

## What Was Built

This week the harness gained a local web UI for live side-by-side comparison. The full
implementation was merged via PR #1 (`harness-comparison-ui` branch).

New files:
- `harness/app.py` — Flask SSE server (port 5001)
- `ui/index.html` — two-panel comparison page
- `harness/loop.py` — refactored into an event generator (`iter_loop`)
- `harness/planner.py` — planning call now returns token usage (`PlanResult`)

---

## How to Run It

Three things need to be running simultaneously:

**Terminal 1 — Precisely MCP HTTP server**
```
cd /Users/rystan.qualls/precisely-mcp-server/dis-locate-apis-v2
.venv/bin/python -m mcp_servers --transport http --port 3000
```

**Terminal 2 — Flask UI backend**
```
cd /Users/rystan.qualls/Desktop/precisely-mcp-test
source .venv/bin/activate
python3 -m harness.app
```

Then open `http://localhost:5001` in a browser.

---

## What the UI Does

Single-page dark-themed app. Type a prompt, select a model (grayed out if the API key
isn't configured), hit **Run comparison**. Two panels fill in simultaneously:

- **Left — Harness**: planning → subset routing → enforced execution loop
- **Right — Naive**: no planning, all 51 tool schemas every round, no enforcement

Each panel streams live: step log (planning, each tool call, each result), then the final
answer rendered as markdown, then metrics (tokens, cost, rounds, time, tools sent/available).

When both panels finish a **delta bar** appears showing the % difference in cost and input
tokens between harness and naive. That single number is the business case on one screen.

---

## Naive Mode — What It Is and Why It Matters

**Naive mode is what most LLM integrations look like before any optimization.** It's the
baseline that a prospect's existing Claude/GPT-4/Gemini integration probably resembles today:

1. Dump all 51 tool schemas into the context every round
2. Ask the model to answer the prompt
3. Accept whatever tools it decides to call (or skip)
4. Stop when the model stops

No planning step, no subset routing, no enforce-to-terminate. Just a raw tool-use loop.

**The harness adds three layers on top:**
1. Planning call first — model picks ~5-8 of 51 tools before execution starts
2. Only the planned tools' schemas are sent — ~85% of tool-definition tokens removed
3. Refuse-to-terminate enforcement — nudges the model if it tries to stop with uncalled tools

Same model, same prompt, same MCP server. The delta is purely what the harness buys.

**Why this matters for the customer story:** the naive panel shows the current cost; the
harness panel shows what it costs after optimization. The comparison makes the value of
the harness visible in a single run without any explanation needed.

---

## Architecture: How Streaming Works

The loop was refactored from a blocking function into an event generator. Instead of
waiting until the full run completes and returning one result dict, `iter_loop` yields a
small JSON event for each step as it happens:

```
planning → plan → round → tool_call → tool_result → answer → done
```

The Flask `/api/stream` endpoint drives this generator and sends each event as an SSE
frame (`data: {...}\n\n`) over an open HTTP connection. The browser opens **two**
independent SSE connections simultaneously (one per panel) via `EventSource`, which is
why both panels stream in parallel rather than sequentially.

`Harness.run()` (used by the CLI) now simply drains `run_stream()` — same result, same
interface, no CLI behavior change.

---

## Bug Fixed Post-Merge

The merged `harness.py` had leftover dead code in `run()` (lines referencing `run_loop`,
`plan`, `tools`, `subset` — none defined in the new version). This would have crashed
both the CLI and the app on first use. Fixed immediately after merge:
- Removed the dead code block
- Fixed `_estimate_cost` to use `self.adapter.model_id` instead of `self.name` (cost was
  always returning None because "claude" is not a key in the pricing table)
- Added `cost_basis` back to the `done` event so the CLI footer doesn't break

---

## Multi-LLM Results So Far (from CLI testing)

| Model | Single-tool task | Cost | Speed | Notes |
|---|---|---|---|---|
| Claude (sonnet-4-6) | ✅ Correct | ~$0.013 | ~8s | Best formatted output |
| OpenAI (gpt-4o-mini) | ✅ Correct | ~$0.0003 | ~5s | Cheapest, faster, sometimes more tools |
| Gemini (2.5-pro) | ✅ Correct | ~$0.0025 | ~67s | Very slow, terse output, 503s under load |
| Llama (3.1:8b-16k) | ❌ Narration | $0.00 | ~130s | Writes tool calls as text, not API calls |

**Llama findings:**
- Context overflow (stock 4k → fixed with 16k Modelfile) — resolved
- Tool-call narration — model writes `{"name": "...", "parameters": {...}}` as text body
  instead of using the structured `tool_calls` API field. A format-compliance limitation
  of the 8B model, not a code issue.
- Safety refusals on legitimate tasks (phone numbers, addresses) — small-model over-caution
- When planning fails (vague prompt), all 51 schemas flood the 16k context → overflow again

**Key takeaway:** free local models are not production-ready for Precisely's tools at the
8B scale. The narration and safety issues are model capability ceilings, not fixable with
prompting alone.

---

## Gemini Timeout Fix

Gemini 2.5 Pro is a thinking model — single tool calls can take 60+ seconds. The SDK's
default HTTP timeout was shorter than that. Added `http_options=types.HttpOptions(timeout=300_000)`
(5 minutes in ms) to the Gemini client so long-running thinking calls don't time out
mid-stream.

---

## Next Steps

- [ ] Run 19-prompt benchmark through the new harness (old results are stale — different
      token counts, no planning step, no subset routing)
- [ ] Redesign pass metric — drop "75% tool overlap with Claude"; move toward
      required-minimal-toolset per prompt + plan completion as the diagnostic signal
- [ ] Fix Llama narration — try llama3.2, stronger execution instruction in system prompt
- [ ] Standardize OpenAI model — drop legacy gpt-4o-mini, pick from gpt-5.x lineup
- [ ] Get Precisely's enterprise discount rate for accurate cost demos
