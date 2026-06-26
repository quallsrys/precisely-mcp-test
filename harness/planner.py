"""Universal planning step — runs on the SAME model that will execute.

Sends the request plus a name + one-line summary of every tool (cheap — never the full
schemas, which is also what keeps Llama under its context limit), a structural taxonomy
of the tool space, and a decomposition instruction. Returns an ordered list of tool names.

No scenario playbooks: the model reasons about completeness itself, so the plan
generalizes to any request rather than memorizing anticipated ones.
"""

import json
import re
from dataclasses import dataclass

from harness.adapters.base import ModelAdapter


@dataclass
class PlanResult:
    names: list[str]
    input_tokens: int = 0
    output_tokens: int = 0

TAXONOMY = """\
The Precisely MCP tools fall into dependency tiers; earlier tiers feed later ones:
  1. Location    — verify_address, geocode, reverse_geocode, autocomplete_address (establish/confirm the location first)
  2. Property    — get_property_data, get_buildings_by_address, get_parcels_by_address, get_address_family, get_replacement_cost_by_address
  3. Risk/Hazard — get_flood_risk_by_address, get_property_fire_risk, get_wildfire_risk_by_address, get_earth_risk, get_coastal_risk, get_historical_weather_risk
  4. Enrichment  — get_demographics, get_neighborhoods_by_address, get_crime_index, get_places_by_address, get_schools_by_address, get_psyte_geodemographics_by_address
  5. Synthesis   — summarize (always last)
This is a MAP of how the tools relate, not a script. Pick only the tools the request needs."""

PLANNING_SYSTEM = """\
You are a planning assistant for the Precisely location-intelligence toolset.
Your only job is to decide which tools to call, and in what order, to fully answer a request.
You do not call tools or write the answer — you produce a plan."""

PLANNING_TEMPLATE = """\
Request:
{prompt}

Available tools (name — what it does):
{tool_list}

{taxonomy}

Think about what a COMPLETE answer requires:
- Break the request into the distinct dimensions it asks about (location, property, each kind of risk, demographics, etc.).
- For each dimension, include every tool that contributes. A risk question usually spans several hazard tools; a property question spans physical, legal, and ownership data.
- Prefer more coverage over less — anticipate data the user would reasonably need next.
- Respect the tier order: establish location before property/risk; synthesize last.

Return ONLY a JSON array of tool names in execution order, nothing else.
Example: ["verify_address", "get_property_data", "get_flood_risk_by_address", "summarize"]"""


def _one_liner(description: str, limit: int = 140) -> str:
    """First sentence of a tool description — enough to route on, cheap on tokens."""
    text = " ".join(description.split())
    match = re.search(r"(.+?\.)\s", text)
    sentence = match.group(1) if match else text
    return sentence[:limit].rstrip()


def _parse_plan(text: str, valid_names: set[str]) -> list[str]:
    """Extract a JSON array of tool names from the model's planning text."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        names = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    seen, plan = set(), []
    for n in names:
        if isinstance(n, str) and n in valid_names and n not in seen:
            seen.add(n)
            plan.append(n)
    return plan


def make_plan(adapter: ModelAdapter, prompt: str, raw_tools: list[dict], max_tokens: int = 1024) -> PlanResult:
    """Ask the model for an ordered tool plan plus the planning call's token usage.

    Returns PlanResult(names=[], ...) if planning fails — the caller falls back to
    sending all tools so the system still works.
    """
    valid_names = {t["name"] for t in raw_tools}
    tool_list = "\n".join(f"- {t['name']} — {_one_liner(t.get('description', ''))}" for t in raw_tools)

    user = PLANNING_TEMPLATE.format(prompt=prompt, tool_list=tool_list, taxonomy=TAXONOMY)
    messages = adapter.init_messages(user)
    turn = adapter.complete(PLANNING_SYSTEM, messages, tools=None, max_tokens=max_tokens)
    names = _parse_plan(turn.text, valid_names)
    return PlanResult(names=names, input_tokens=turn.input_tokens, output_tokens=turn.output_tokens)
