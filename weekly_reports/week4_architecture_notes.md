# Week 4 — Architecture Notes & Research
**Precisely MCP Server — Intern Project**
June 25, 2026

---

## The Harness Concept

A harness is the layer between the user's prompt and the LLM. It handles:
- Fetching tools from the MCP server
- Formatting them for whichever LLM is being used
- Running the agentic loop (send prompt → execute tool calls → feed results back → repeat)
- Returning a structured result

The key insight is that the agentic loop is identical regardless of which LLM is used. What changes between models is only how tools are formatted going in and how tool calls are parsed coming out. Everything else — the MCP calls, the message history, the loop — is the same code.

---

## Planning Step vs Execution Step

### How it works today
The current clients send the full prompt to the LLM and let it decide which tools to call on the fly. The LLM simultaneously has to understand the request, figure out which tools are relevant, decide the order, and execute — all in one context window. This is called an unstructured loop.

### The planning step
Splitting into two dedicated phases:

**Phase 1 — Planning call**
Send the prompt to the LLM with one job only: return an ordered task list. No tool schemas in context, no execution pressure. Just strategy.

```
"Given this request, list the Precisely MCP tools needed in order.
Rules: always geocode/verify first, property before risk, risk before summary.
Return JSON: ['tool1', 'tool2', ...]"
```

**Phase 2 — Execution loop**
The harness walks the task list one step at a time. Each tool call has a narrow context — the harness already knows what comes next, so the model only has to execute, not plan.

### Why this helps each model differently

**Gemini** benefits most. Gemini plans well but stops early — when an early tool result looks satisfying it terminates the loop before completing all necessary calls. An explicit task list committed upfront stays in context as a checklist the model can't ignore. It would see remaining tasks instead of deciding on its own that it has enough data.

**GPT-4o-mini** benefits moderately. It both plans poorly and stops early. Reducing simultaneous cognitive load (planning + execution at once) helps, but its planning ability is weaker so the task list it produces may still be incomplete.

**Llama** benefits least from planning alone — its primary problem is context overflow, not planning quality. Addressed separately below.

**Claude** benefits minimally. It already performs implicit planning before making the first tool call. Separating planning into a dedicated prompt doesn't give it new information. May slightly slow it down.

### What the planning step actually improves for benchmarking
Even where it doesn't improve model output quality, it improves observability. You can now measure planning quality and execution quality independently. Currently when GPT-4o-mini calls only 3 tools there is no way to know whether it planned wrong or executed incompletely. With an explicit plan you can see exactly where the failure occurred.

---

## Improving Model Performance After Planning Split

### Targeting models that still call fewer tools than Claude

**The feedback loop approach**
After the execution loop completes, compare the tools actually called against the planned task list. If any planned tools were skipped, prompt the model:

```
"Your plan included get_wildfire_risk_by_address but you did not call it.
Complete the remaining tasks: [list]"
```

This is called a reflection step. The model reviews its own output and fills gaps.

**Explicit completion criteria in the system prompt**
Add rules to `system_prompt.md` that define what "done" means per task type:

- Insurance adjuster summary → must include all 6 risk tools before summarizing
- Property report → must include property + building + parcel before summarizing
- Site selection → must include demographics + crime + places + flood before summarizing

This prevents early termination by giving the model a clear definition of complete.

**Verification step**
After the loop, run a lightweight check: did the response cover all the topics the prompt asked for? If not, re-prompt with what is missing. This is the same logic as the keyword check in the benchmark scoring, but applied live instead of after the fact.

---

## The Llama Problem and Why It Matters

### The core issue
llama3.1:8b running locally via Ollama fails when given more than ~10 tool schemas at once. The context fills with schema definitions before the prompt even processes, resulting in zero tool calls. This was confirmed in the full suite run — any category with more than ~8 tools produces exactly 4,095 input tokens (the cap) and no tool calls.

### Why this is worth solving
Llama running locally costs zero dollars per query. Claude costs $0.04–$0.08 per query. For an SE running 20 demo prompts a day across a team of 10, that's a meaningful cost difference. The project plan specifically calls out self-hosted LLM as a primary objective for eliminating per-token costs. If Llama can be made to perform comparably to paid models, it becomes the default for demos and internal use.

### Approaches to fix it

**1. Schema compression**
Strip verbose descriptions from tool schemas before sending to Llama. Keep only name, parameter names, and required fields. Reduces schema tokens by ~60% without losing routing information. The model uses tool names and parameter names to route — the long English descriptions are mostly for humans.

**2. Two-stage routing**
Send only the planning prompt to Llama first (no schemas, just tool names as a list). Llama picks the relevant tool names. Then send only those 4-6 schemas for execution. This solves the overflow problem at the source.

**3. Larger model**
llama3.1:70b handles the full 51-tool schema set without filtering. Requires more GPU memory (at least 48GB VRAM) — feasible on an AWS g5.12xlarge instance but not on a local M2 Mac. The project plan already calls for a g5 instance for Phase 3.

**4. Fine-tuning**
The project plan stretch goal 8e describes collecting successful tool-call traces from Claude and using them to fine-tune the self-hosted model. A fine-tuned llama3.1:8b trained specifically on Precisely MCP tool-calling patterns would dramatically reduce the schema context needed because the model already knows the tools.

### Recommended path
Short term: schema compression + two-stage routing on the 8B model locally.
Phase 3: deploy llama3.1:70b on AWS g5 instance — removes the context problem entirely and makes the self-hosted model directly competitive with paid APIs.

---

## OpenRouter — Unified Model Switching

The mentor referenced a tool for making model switching easier. OpenRouter is a proxy API that accepts requests in OpenAI format and routes them to any of 200+ models. One API key, one client, model is just a string parameter.

```python
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
response = client.chat.completions.create(model="anthropic/claude-sonnet-4-6", ...)
response = client.chat.completions.create(model="google/gemini-2.5-pro", ...)
response = client.chat.completions.create(model="openai/gpt-4o-mini", ...)
```

This collapses four separate client files into one. Any behavioral differences observed in benchmarks are purely the model, not SDK implementation differences. Model switching becomes a config change, not a code change.

For the SE demo app, this means the LLM dropdown in the UI maps to a single model string passed to one backend client — no separate code paths per model.

---

## The Local Demo App Plan

Before AWS deployment, build a local Flask app that SEs can download and run in one command:

```
precisely-demo/
├── harness/
│   ├── app.py        ← Flask API with /run endpoint
│   ├── planner.py    ← planning step
│   └── clients/      ← existing 4 clients (or single OpenRouter client)
├── ui/
│   └── index.html    ← LLM selector + prompt input + results display
├── system_prompt.md
├── .env.example
├── requirements.txt
└── README.md
```

SE setup: download repo, add API keys to `.env`, run `python harness/app.py`, open `localhost:5001`.

This becomes the packageable artifact that can be distributed across the SE org before CloudNative deployment. Docker containerization makes it fully self-contained — one `docker run` command, no Python environment setup required.

---

## Dependency Order for Precisely MCP Tools

Established tool execution order based on data dependencies:

```
Tier 1 — Location establishment (always first)
  verify_address, geocode, autocomplete_address

Tier 2 — Property layer (requires verified address)
  get_property_data, get_buildings_by_address,
  get_parcels_by_address, get_address_family,
  get_replacement_cost_by_address

Tier 3 — Risk layer (requires confirmed coordinates)
  get_flood_risk_by_address, get_property_fire_risk,
  get_wildfire_risk_by_address, get_earth_risk,
  get_coastal_risk, get_historical_weather_risk

Tier 4 — Enrichment layer (context, no hard dependency)
  get_demographics, get_neighborhoods_by_address,
  get_crime_index, get_places_by_address,
  get_schools_by_address, get_psyte_geodemographics_by_address

Tier 5 — Synthesis (always last)
  summarize, any LLM-generated report
```

---

## Avoiding Model-Specific Bloat

The temptation when a specific model has a quirk (e.g., Gemini stopping early) is to add model-specific logic — keep the task list in execution context for Gemini, add a reflection loop for GPT-4o-mini, etc. This is a maintenance trap. Model-specific branches in shared code mean:
- Every new model needs its own case
- Fixes for one model can silently slow down or bloat others
- You can't tell whether a model is behaving correctly or just being compensated for

The correct approach is to put universal behavioral requirements in `system_prompt.md` as rules that all models receive equally. One sentence, ~10 tokens, applies identically to every model. Gemini follows it because it's explicit. Claude follows it naturally anyway. GPT-4o-mini either follows it or reveals a capability gap — which is a finding, not a problem to paper over.

---

## The Real Job: Prevent Skipping Upfront

The goal is not to detect skipped tools after execution and patch around them. The goal is to write instructions clear enough that models don't skip in the first place. That is a prompt engineering problem, not an architecture problem.

The most direct version of the instruction:

> "You have been given an explicit list of tools to call. Call every tool on the list. Do not skip any. Do not summarize until all tools have been called and their results are in your context."

**How to use this in the benchmark:**
1. Add this rule to `system_prompt.md`
2. Rerun failing prompts (especially Gemini insurance/financial category)
3. Models that still skip after this explicit instruction have a capability ceiling, not a prompt gap

That distinction — fixable with better instructions vs. fundamental model limitation — is a meaningful research finding for the project. It tells you where to spend engineering effort and which models are actually viable for production use.

---

## Planning Strategy — Generalization Over Playbooks
*(refines the "Explicit completion criteria" idea under "Improving Model Performance" above)*

Considered, then rejected, scenario playbooks (e.g., "insurance question → these 8 tools"). Two reasons:

1. **It overfits.** Playbooks only work for anticipated question types. Client #20 asks something off-script and the playbook adds nothing. The goal is for the model to figure out the best answer for ANY question from the tools available — not to recall a canned list.

2. **It poisons the evaluation.** The 19 Cloud Native prompts are a held-out TEST SET (built by the mentor months ago to show MCP capabilities). Building playbooks around them means we can no longer tell whether the system generalizes or just memorized the answer key. Keeping those 19 prompts blind is what makes them a valid measurement.

The deeper point: the project goal is to prove free / cheaper models can REASON over Precisely's tools as well as paid ones. Hardcoding scenarios would prove the playbook works, not the model — and it would collapse on the first unanticipated question. **The generic approach isn't a compromise; it is the test.**

### The three levers that generalize

1. **Tool descriptions (foundation).** The model's raw material. If descriptions are good, a capable model reasons about completeness and disambiguation on its own, for any phrasing.

2. **A planning prompt that teaches a PROCESS, not answers.** Teach decomposition: *"Break the request into the dimensions a complete answer requires. For each dimension, include every tool that contributes. Prefer more coverage over less."* Meta-level guidance transfers to questions we never imagined.

3. **A tool taxonomy as a MAP, not a script.** The dependency tiers (location → property → risk → enrichment → synthesis) describe the structure of the tool space — true regardless of the question. A map helps you navigate anywhere; a script only works for the trip it was written for. Ideally this lives in tool metadata, not a hardcoded table to maintain.

*Optional amplifier:* a planning self-critique — one cheap no-tools call (*"Does this plan cover every dimension of the request? What's missing?"*). A generalizable way to "predict a need" without a lookup table.

### Tool description audit (June 25) — descriptions are NOT the bottleneck

Pulled all 51 descriptions from `tools/list` (names + descriptions only, no schemas):

- Count: **51** | Avg: **983 chars (~250 tokens)** | Median: 683 | Min: 408 | Max: 4,688
- **Zero** tools with a thin (<100 char) description

The descriptions are already high quality — positive guidance ("Use this when…"), negative guidance ("Do NOT use when… use X instead"), cross-references to sibling tools, output schemas, and worked request examples.

**Two implications:**

1. **Plan quality is achievable from descriptions alone.** A capable model already has what it needs to reason about which tools give a complete picture and to disambiguate similar tools. This validates the no-playbook approach — the raw material for generalization is in place. The bottleneck, if any, is the planning *prompt*, not the tool metadata.

2. **This is exactly why Llama overflows.** 51 descriptions ≈ **12,750 tokens** before schemas, system prompt, or user prompt load. Llama capped at **4,095** input tokens — suspiciously close to Ollama's default `num_ctx` of 4096. The richness that makes Claude and Gemini smart is precisely what blows the 8B model's context. Confirms **two-stage routing is mandatory for Llama**, not optional:
   - **Planning call** sends SHORT summaries only (the first sentence of each description is a clean one-liner — auto-derivable, no manual maintenance).
   - **Execution call** loads full schemas for the planned subset only.
   - *Also worth testing:* bump Ollama `num_ctx` 4096 → 16384 (llama3.1 supports up to 128k). Complementary to two-stage routing, not a replacement — sending 12.7k tokens of descriptions to an 8B model is slow and dilutes attention even when it fits.

---

## Metrics & Instrumentation

### What already exists
Every client returns `latency_ms` and `usage` (`input_tokens`, `output_tokens`) per `ask()`.

### The counting bug — fix before trusting any token number
The agentic loop calls the model once per tool-use round, but the clients read `usage` only from the **final** response. A task with 10 tool calls makes 10+ round-trips and discards 9 of them. Because the message history *grows* each round (every tool result is appended and re-sent), the true billed input is the **sum** across rounds — often 3–5× the final call alone. Current numbers undercount, which weakens the cost story rather than strengthening it.

### What to add
1. **Accumulate usage across every loop iteration** — sum input + output tokens, count API round-trips. This is what's actually billed.
2. **Split timing** — model latency per round vs. MCP tool latency per call. Shows whether time goes to model reasoning or data retrieval (the latter is Precisely's value, not overhead).
3. **Cost estimate** — tokens × per-model rate = dollars per task. The headline customer number. (Llama local = $0.)
4. **Run-level rollup** — total tokens, cost, wall-time per model across the 19 prompts.

### Where it lives
The **shared loop owns accumulation** — the adapter reports per-call usage/latency, the loop sums them into a run-level metrics object. Written once, not four times.

---

## Token Efficiency

**Key insight:** all 51 tool schemas are re-sent on *every* iteration of the loop (~15–20k tokens with parameter schemas). A 10-round task pays that 10× — 150–200k input tokens just for tool definitions the model already saw.

Prioritized:

1. **Subset routing (highest impact — and it's the same mechanism that fixed Llama).** Plan with tool *names*, then execute sending only the ~6 planned schemas. ~85% off the tool-definition payload on every round, compounding across rounds. The Llama context fix and the #1 paid-model cost saver are the same change. *(Safety valve: if planning returns an empty/invalid plan, fall back to sending all tools so the system still works.)*

2. **Prompt caching (near-free).** Tools + system prompt are byte-identical across rounds. Claude caches at 0.1× read / 1.25× write; Gemini has context caching; OpenAI caches automatically. A 10-round loop goes from 10× full price on the static prefix to 1× write + 9×0.1. Stacks with subset routing. *(Deferred past v1 — provider-specific.)*

3. **Trim tool results before re-sending.** MCP outputs can be huge (GeoJSON FeatureCollections, WMS payloads). The full raw blob is re-sent in context every subsequent round. Cap size or extract the fields actually used — carefully, so needed data isn't dropped. *(Deferred past v1.)*

4. **Execution-time schema compression.** During execution the model already chose the tool — it needs the parameters, not the 400–4,700-char "when to use / Do NOT use / examples" prose. Keep rich descriptions for *planning*, strip them for *execution*. *(Deferred past v1.)*

5. **Iteration cap.** Claude ran 34 tool calls on some prompts — plan-driven execution naturally bounds this instead of running open-ended.

Rough combined effect: subset routing + caching ≈ ~90% off tool-definition input cost, the dominant line item on multi-step tasks.

---

## Pricing — List vs. Enterprise (research, June 25)

**Key finding: no provider publishes an enterprise per-token rate.** Enterprise pricing is a confidential, negotiated discount off list, plus published discount *mechanisms*. So the harness can't hardcode a "true enterprise" number — it uses verified **list rates** (the only publicly verifiable, demo-safe anchor) keyed by exact model id, with a configurable `ENTERPRISE_DISCOUNT` knob to plug in Precisely's actual negotiated rate.

### Verified list rates (USD per 1M tokens, in → out)

| Provider | Model | Input | Output |
|---|---|---|---|
| Anthropic | Opus 4.8 | 5.00 | 25.00 |
| Anthropic | Sonnet 4.6 | 3.00 | 15.00 |
| Anthropic | Haiku 4.5 | 1.00 | 5.00 |
| OpenAI | gpt-5.5 | 5.00 | 30.00 |
| OpenAI | gpt-5.4 | 2.50 | 15.00 |
| OpenAI | gpt-5.4-mini | 0.75 | 4.50 |
| OpenAI | gpt-5.4-nano | 0.20 | 1.25 |
| OpenAI | gpt-4o-mini *(legacy)* | 0.15 | 0.60 |
| Google | Gemini 2.5 Pro (≤200k) | 1.25 | 10.00 |
| Google | Gemini 2.5 Pro (>200k) | 2.50 | 15.00 |
| Google | Gemini 2.5 Flash | 0.30 | 2.50 |
| Local | Llama (self-hosted) | 0 | 0 |

### Published enterprise levers (these are real and countable)

- **Batch API: −50%** across all three providers (for async/non-interactive workloads).
- **Prompt caching:** Claude cached input −90% (read 0.1×, write 1.25×); OpenAI cached input ≈ −75% (pay 25% of input rate); Gemini context caching available.
- **Committed / provisioned throughput:** Vertex CUDs and Azure OpenAI PTUs run −20% to −65% with 1-month / 1-year commits.
- **Negotiated volume:** reported ~25–45% off list for committed spend (e.g., OpenAI ~30% off above ~$10k/mo) — via sales, confidential.

### Implications

- `gpt-4o-mini` (what the benchmark used) is **legacy**; 2026 OpenAI models are gpt-5.x. Standardize the lineup before re-baselining.
- The biggest enterprise lever for *our* workload is **prompt caching** — because the harness re-sends tool schemas every round, caching the static prefix is where the savings are. Ties directly to the Token Efficiency section above.
- For customer demos, show **list price** (verifiable) and note that Precisely's negotiated rate would be lower; set `ENTERPRISE_DISCOUNT` to model it.

*Sources: provider pricing pages (platform.claude.com, developers.openai.com, ai.google.dev) and the cached claude-api model table, June 2026.*

---

*Notes compiled June 25, 2026*
