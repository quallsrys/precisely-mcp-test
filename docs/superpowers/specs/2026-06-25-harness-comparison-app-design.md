# Harness Comparison App — Design

**Date:** 2026-06-25
**Status:** Approved (design); pending spec review
**Location:** `precisely-mcp-test/`

## Purpose

A local web app to compare, for a single prompt and a single selected model, the
**full harness** (planning + subset-routing + enforced loop) against a **naive agent
loop** (same model, all 70 MCP tool schemas, plain tool-use loop, no planning). Both
run side-by-side with live progress, so the value the harness adds — fewer/cheaper
tokens, plan completeness, tool selection — is visible directly.

This realizes the "local demo app" sketched in `weekly_reports/week4_architecture_notes.md`,
narrowed to the harness-vs-naive comparison.

## Decisions (from brainstorming)

- **Baseline = naive agent loop** (not raw-no-tools). Isolates what the planner +
  subset-routing buy, holding the model and tool access constant.
- **Layout = one model, harness vs naive**, two panels side-by-side. Model-to-model
  comparison is "switch the model and re-run," not simultaneous columns.
- **Form factor = local Flask web app + single HTML page.** Renders markdown answers
  and tables well; matches the week-4 demo-app plan.
- **Run UX = live progress stream.** Panels show steps as they happen (planning →
  each tool call/result → answer), not a spinner-then-fill.
- **Streaming approach = generator refactor (approach A).** The loop becomes an event
  generator; `Harness.run()` and the CLI consume it and keep their current contract.
  The SSE endpoint iterates the generator directly — no threads/queues to bridge.

## Architecture

```
Browser (ui/index.html)
  ├─ EventSource → /api/stream?model=claude&mode=harness
  └─ EventSource → /api/stream?model=claude&mode=naive
        │
   Flask (harness/app.py, threaded)
        │  one streaming Harness run per connection
        ▼
   Harness.run_stream(prompt, mode)  ──yields events──►  SSE frames
        │
        ├─ make_plan()        (harness mode only)
        ├─ subset routing     (harness mode only; naive sends all 70 tools)
        └─ event loop  ──►  mcp.call_tool() against live server :3000
```

Browser opens two independent SSE connections (one per panel). Flask runs with
`threaded=True` to serve both concurrently. Each connection runs one streaming
`Harness` execution and renders events into its panel. When both panels emit `done`,
the client computes a delta footer.

## Event protocol

A run emits a sequence of JSON events (sent as SSE `data:` frames):

| Event | Payload | Notes |
|---|---|---|
| `planning` | — | harness only; naive skips |
| `plan` | `{plan: [...], tokens: {in, out}}` | harness only; carries planning-call usage |
| `round` | `{n, tokens: {in, out}}` | per model round-trip |
| `tool_call` | `{name, arguments}` | one per tool the model invokes |
| `tool_result` | `{name, ms, ok, preview}` | `preview` = truncated tool output |
| `answer` | `{text}` | model's final text turn (markdown) |
| `error` | `{where, message}` | non-fatal (tool) or fatal (model/transport) |
| `done` | `{metrics, cost_usd, plan_complete, tools_called, plan_uncalled}` | terminal |

Answer is emitted when the model produces its final text turn (no token-by-token
streaming in v1 — tool calls still stream live).

## Components / files (in `precisely-mcp-test/`)

| File | Responsibility |
|---|---|
| `harness/app.py` | Flask app. Routes: `/` (serve HTML), `/api/models` (configured models), `/api/stream?model=&mode=` (one SSE run) |
| `harness/harness.py` | add `run_stream(prompt, mode)` generator; reimplement `run()` on top of it |
| `harness/loop.py` | refactor the loop into an event generator (`iter_loop`); emit events listed above |
| `ui/index.html` | single page, vanilla JS, two `EventSource` connections, `marked.js` for markdown rendering, delta footer |
| `requirements.txt` | add `flask`; add `openai` + `google-genai` (currently missing) so non-Claude panels can run |

## Two fixes folded in

These directly serve the comparison's integrity and are included in this work:

1. **Tool-error handling (review #1).** Wrap `mcp.call_tool` in try/except; emit
   `tool_result {ok: false}` and feed the error back to the model as the tool result
   so the run recovers instead of the SSE stream dying mid-panel. A naive run sending
   all 70 tools is more likely to hit a server-side-broken tool, so this is load-bearing.
2. **Planner tokens counted (review #2).** The `plan` event carries the planning
   call's token usage, folded into `metrics` and `cost_usd`. Without it the harness
   panel reports a fake-low cost (~13% undercount, measured) and the comparison lies.

## Naive mode

A run with no planning step and all 70 tool schemas sent every round. The existing
loop already supports the no-plan path (empty plan ⇒ all tools, no nudging), so naive
mode is a flag through `run_stream`, not a second loop implementation.

## Model selection & availability

Radio selector for `claude | gemini | openai | llama`. `/api/models` reports which are
usable (API key present, or Ollama reachable for llama); the UI disables the rest with
a "not configured" tag. Today only Claude is live; others light up as keys/Ollama are
added.

## Delta footer

Computed client-side once both panels emit `done`: Δ cost (%), Δ tool count, Δ input
tokens, Δ wall-time (harness relative to naive).

## Error handling

- **Tool failure:** caught, surfaced as `tool_result {ok:false}` + `error`, fed back to
  the model; run continues.
- **Model/transport failure** (auth, rate limit, network): emit fatal `error`, close the
  stream; that panel shows the error, the other panel is unaffected.
- **MCP server down:** `/api/models` / stream start surfaces a clear "MCP server not
  reachable at :3000" message.

## Testing

- Unit: `iter_loop` emits the expected event sequence for (a) a clean run, (b) a run
  whose tool call raises (asserts recovery + `ok:false`), (c) naive mode (no `planning`/
  `plan` events, all tools sent).
- Unit: planning tokens are included in `done.metrics` / `cost_usd`.
- Manual: live run against the MCP server on :3000 with Claude — both panels stream and
  the delta footer renders.

## Non-goals (v1)

- No automated correctness scoring — the two answers are eyeballed.
- No token-by-token answer streaming (tool calls stream; answer appears on completion).
- No persistence / run history.
- No simultaneous multi-model columns (one model per run).

## Notes

- The working directory is not a git repository, so this spec is written but not
  committed. If git is initialized later, commit it then.
