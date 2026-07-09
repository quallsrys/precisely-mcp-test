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

Single-page app (light-mode Precisely branding — see "UI Design Language" below). Type a prompt,
select a model and its specific model ID from the card dropdown (grayed out if the API key isn't
configured), hit **Run comparison**. Two panels fill in simultaneously:

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

## UI Design Language (Precisely Brand, Light Mode)

The UI was moved off the original dark theme to a **light-mode Precisely-branded** look so it
matches the company's visual identity in customer-facing demos. The design is defined entirely
with CSS variables at the top of `ui/index.html`:

**Palette**
- Purple `#7F16E0` — primary/accent (harness panel, selected states, buttons)
- Navy `#001B4C` — headings and primary text
- Amber `#FAB511` / tint `#FFF9E6` — the naive panel accent (amber = "unoptimized")
- Magenta `#E5007E` — errors / cost-increase pills
- Backgrounds: app `#F5F6FA`, surfaces white `#FFFFFF`, borders `#E2E4EE`

**Conventions**
- System font stack (`-apple-system, system-ui`); monospace (`SF Mono`) for step logs, metrics, and model IDs
- Card-based controls with rounded corners (10–12px), soft focus rings, subtle hover transitions
- Harness = purple, Naive = amber, applied consistently across headers, badges, and tool tags
- Pills for deltas: green (`pill-savings`) for reductions, magenta (`pill-cost`) for increases, neutral gray for no change

---

## New Features This Week

### 1. Tool-level comparison (not just counts)
The delta bar previously only reported *how many more* tools the harness used. It now also lists
the **exact tool names** that differ, in two color-coded groups:
- **harness only** (purple tags) — tools the harness called that naive didn't
- **naive only** (amber tags) — tools naive called that the harness skipped

The diff row is hidden entirely when the two tool sets are identical. This makes it obvious at a
glance *which* tools each mode chose, not just the raw delta.

### 2. Choose LLM **and** model
Each provider card now has a **dropdown of that provider's available models** (verified live
against each provider's API before wiring them in), defaulting to the configured model. Selecting
a different model applies to both the harness and naive runs. The chosen `model_id` flows through
the SSE URL → `app.py` → `Harness(model_id=...)`.

Curated model lists (checked against each provider's `models.list()`):
- **Claude**: sonnet-4-6, sonnet-5, opus-4-8/4-7, haiku-4-5, fable-5
- **OpenAI**: gpt-4o(-mini), gpt-4.1(-mini/-nano), gpt-5, gpt-5.4(-mini), gpt-5.5
- **Gemini**: 2.5-pro, 2.5-flash(-lite), 2.0-flash, 3-pro-preview, 3.1-pro-preview, 3.5-flash
- **Llama**: 3.1:8b-16k, 3.1:8b, 3.2:latest

### 3. Expanded, verified pricing table
`PRICING` in `harness.py` was extended to cover every model in the dropdowns so cost no longer
shows `n/a`. Gemini rates were pulled from the official pricing page
(`ai.google.dev/gemini-api/docs/pricing`), including the newer 3.1-pro-preview ($2/$12 per 1M at
the ≤200k tier) and 3.5-flash ($1.50/$9). Preview models with no published price still correctly
show `n/a` rather than a fabricated number. Cost scales linearly, so it's accurate at the 50–100k
token volumes we actually run.

### 4. `plan_warning` event
When the planner returns no tools and the harness falls back to sending the full tool set, it now
emits a `plan_warning` event that surfaces as a ⚠ line in the harness step log — so a silent
degradation to "all tools" is now visible instead of hidden.

### 5. Planner prompt tuning
Reworded the planning instruction to keep dimension-based decomposition and a coverage bias, but
add the key qualifier: *include a tool only if the request clearly calls for that dimension, and
don't add tools for dimensions the request doesn't mention.* This curbs over-selection without a
hard cap.

---

## Errors Encountered & How We Solved Them

| Error / symptom | Root cause | Fix |
|---|---|---|
| `'NoneType' object is not iterable` (Gemini, intermittent) | Gemini returned `content.parts = None` (blocked/thinking-only turn) and the loop iterated it | Guard: `for part in content.parts or []` in `gemini.py` |
| GPT-5 models: `Unsupported parameter: 'max_tokens' ... use 'max_completion_tokens'` | GPT-5 / o-series dropped `max_tokens` | Conditional key in `openai.py`: use `max_completion_tokens` for `gpt-5*`/`o1`/`o3`/`o4`, else `max_tokens` |
| Cost showed `n/a` for Gemini & OpenAI models | Those model IDs weren't in the `PRICING` table | Added all dropdown models with verified list prices |
| **Gemini harness sent all 51 tools** (no routing, +12% cost vs naive) | **Gemini 2.5 Pro is a thinking model; it spent ~1021 of the 1024 planning-output tokens on "thoughts", hit `MAX_TOKENS`, returned an empty plan → fallback to all tools.** Confirmed by diagnostic (6/6 runs `finish=MAX_TOKENS`, `parts=None`) | Cap thinking on planning calls only: when `tools is None`, add `ThinkingConfig(thinking_budget=128)` in `gemini.py`. Verified 4/4 valid plans (~5–8 tools) afterward |
| GPT-5.5 harness produced no output | Same empty-plan / fallback family as above | Addressed by the planning-token fix + `plan_warning` visibility |
| Llama card "Ollama not reachable" | The Ollama server wasn't running (installed at `/opt/homebrew/bin/ollama`, but no process on :11434) | Started `ollama serve`; all three models already pulled. For persistence use `brew services start ollama` |

**Note on the empty-plan bug:** this was the important architectural find of the week. The harness
plumbing was always correct (planning sends one-line summaries with `tools=None`; execution sends
only the planned subset's full schemas). The failure was upstream — the planning *call itself*
returned nothing because thinking consumed the output budget. It's a general risk for any thinking
model asked for a short structured output.

---

## Next Steps

- [ ] Run 19-prompt benchmark through the new harness (old results are stale — different
      token counts, no planning step, no subset routing)
- [ ] Redesign pass metric — drop "75% tool overlap with Claude"; move toward
      required-minimal-toolset per prompt + plan completion as the diagnostic signal
- [ ] Fix Llama narration — try llama3.2, stronger execution instruction in system prompt
- [ ] Standardize OpenAI model — drop legacy gpt-4o-mini, pick from gpt-5.x lineup
- [ ] Get Precisely's enterprise discount rate for accurate cost demos
