"""
Benchmark runner — executes all 20 Cloud Native prompts through ClaudeClient
and saves results to benchmarks/cloudnative_results.json and cloudnative_results.md
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))
from clients.claude_client import ClaudeClient


PROMPTS = [
    # Telecom
    (
        "telecom",
        "telecom_expansion_market_st",
        "Analyze the area around 1600 Market St, Denver, CO for telecom expansion potential. Use a travel boundary to define the service area, then pull demographics, housing density, income levels, broadband serviceability, and property data to identify high-value neighborhoods for network buildout.",
    ),
    (
        "telecom",
        "telecom_commercial_property",
        "Analyze the commercial property at 1700 California St, Denver, CO 80202. Pull building characteristics, property attributes, address family to identify all units, places/tenants at the location, and broadband serviceability data to assess this building for network deployment.",
    ),
    (
        "telecom",
        "telecom_address_correction",
        "I have this address: '411 ? ??????-????? OH 44022'. Please fix this using Precisely MCP.",
    ),
    (
        "telecom",
        "telecom_fraud_detection",
        "Run fraud detection and identity validation for a new subscriber application at 1615 SW 107th Ave, Miami, FL 33165-7344. Verify the address, pull property attributes, building data, demographics, and neighborhood information to assess whether this is a legitimate residential or commercial location and generate a risk profile.",
    ),
    # P&C Insurance
    (
        "insurance",
        "insurance_adjuster_summary",
        "Generate an adjuster summary for the property at 2755 Milwaukee St, Denver, CO 80205. Include property characteristics, lot size, building details, flood risk assessment, fire risk, and nearby hazard information to support the claims process.",
    ),
    (
        "insurance",
        "insurance_cat_exposure",
        "Analyze catastrophe exposure for properties in the 80219 ZIP code area of Denver. Assess flood risk zones, earthquake proximity, wildfire risk, and provide a comprehensive hazard profile for portfolio accumulation management.",
    ),
    (
        "insurance",
        "insurance_storm_claim",
        "Help me triage a storm damage claim for the property at 789 Grape St, Denver, CO 80220. Pull the property details, assess environmental risks, check flood zone status, and provide data to support severity prediction and fraud detection.",
    ),
    (
        "insurance",
        "insurance_agent_network",
        "Analyze the Denver metropolitan area for insurance agent network optimization. Look at population density, demographics, property values, and points of interest around 80202, 80203, and 80204 ZIP codes to recommend optimal agent placement.",
    ),
    # Financial Services
    (
        "financial",
        "financial_ownership_lookup",
        "Look up property ownership information for 1200 Larimer St, Denver, CO and identify any common ownership patterns. Include assessed values, property types, and ownership details to help identify related holdings.",
    ),
    (
        "financial",
        "financial_multifamily_report",
        "Generate a comprehensive property report for the multi-family property at 1200 Larimer St, Denver, CO 80204. Include property ownership, assessed value, building characteristics, parcel and lot details, address family hierarchy, and surrounding area demographics and points of interest.",
    ),
    (
        "financial",
        "financial_hazard_mortgage",
        "Assess natural hazard risks and their potential impact on commercial real estate near 1999 Broadway, Denver, CO 80202. Include flood risk, earthquake risk, environmental hazards, and property valuation data to evaluate mortgage portfolio exposure.",
    ),
    (
        "financial",
        "financial_merchant_enrichment",
        "Resolve and enrich a merchant location at 500 16th St Mall, Denver, CO 80202. Validate the address, pull property and business data, identify nearby points of interest, and provide location context for card transaction enrichment.",
    ),
    (
        "financial",
        "financial_loan_fraud",
        "Run fraud detection and identity validation for a loan applicant at 321 Pine St, Denver, CO 80203. Cross-reference address verification, phone validation, property ownership records, and demographic data to generate a comprehensive risk assessment.",
    ),
    (
        "financial",
        "financial_branch_atm_optimization",
        "Analyze the Denver metro area for branch and ATM network optimization. Evaluate demographics, points of interest, population density, income levels, and neighborhood characteristics around ZIP codes 80202, 80203, 80204, and 80205 to recommend optimal placement.",
    ),
    # Retail
    (
        "retail",
        "retail_distribution_chicago",
        "Analyze these distribution locations: 1) 1000 S Canal St, Chicago, IL 60607, 2) 8500 W Bryn Mawr Ave, Chicago, IL 60631, 3) 2600 S Throop St, Chicago, IL 60608, 4) 9715 S Cottage Grove Ave, Chicago, IL 60628, 5) 5555 Touhy Ave, Skokie, IL 60077",
    ),
    (
        "retail",
        "retail_commercial_intelligence_nyc",
        "Generate a comprehensive Commercial Property Intelligence Report for 1290 Avenue of the Americas, New York, NY 10104. Include full property attributes, building specifications and number of stories, total parcel size and lot dimensions, ownership details, assessed valuation, the parent PreciselyID (PBKEY) and all child PBKEYs within the address family hierarchy, a complete tenant directory of all businesses operating at the property, and a location risk and demographic profile.",
    ),
    (
        "retail",
        "retail_site_evaluation",
        "Evaluate 500 16th St Mall, Denver, CO 80202 as a potential retail site. Analyze the surrounding demographics, income levels, population density, nearby points of interest and competitors, property details, and neighborhood characteristics to recommend whether this location is suitable for a new retail store.",
    ),
    (
        "retail",
        "retail_zip_expansion",
        "Analyze ZIP codes 80202, 80203, and 80204 in Denver for retail expansion opportunities. Compare demographics, household income, population density, housing characteristics, and existing points of interest across these areas to rank them by retail market potential.",
    ),
    (
        "retail",
        "retail_risk_profile",
        "Build a comprehensive risk profile for the retail location at 2000 E Colfax Ave, Denver, CO 80206. Include property characteristics, building details, flood zone, wildfire risk, fire risk, crime index, and nearby tenant exposure analysis. Summarize the overall risk posture with specific mitigation recommendations.",
    ),
]


def run_benchmarks():
    client = ClaudeClient()
    results = []
    output_dir = Path(__file__).parent

    print(f"Running {len(PROMPTS)} Cloud Native benchmark prompts...\n")

    for i, (category, label, prompt) in enumerate(PROMPTS, 1):
        print(f"[{i:02d}/{len(PROMPTS)}] {category} / {label}")
        t0 = time.perf_counter()
        try:
            result = client.ask(prompt, max_tokens=8192)
            status = "ok"
        except Exception as e:
            result = {"text": "", "tool_calls": [], "latency_ms": 0, "usage": {}, "model": ""}
            status = f"error: {e}"

        tool_names = [tc["name"] for tc in result.get("tool_calls", [])]
        usage = result.get("usage", {})
        input_tok = usage.get("input_tokens", 0) or 0
        output_tok = usage.get("output_tokens", 0) or 0

        print(f"         tools={len(tool_names)} ({', '.join(tool_names) or 'none'})")
        print(f"         tokens={input_tok:,} in / {output_tok:,} out  latency={result.get('latency_ms', 0):,}ms\n")

        results.append({
            "category": category,
            "label": label,
            "prompt": prompt,
            "status": status,
            "model": result.get("model", ""),
            "tool_calls": result.get("tool_calls", []),
            "tool_names": tool_names,
            "tool_count": len(tool_names),
            "text": result.get("text", ""),
            "latency_ms": result.get("latency_ms", 0),
            "usage": usage,
        })

    # Save JSON
    json_path = output_dir / "cloudnative_results.json"
    with open(json_path, "w") as f:
        json.dump({"run_at": datetime.now().isoformat(), "results": results}, f, indent=2)

    # Save markdown report
    md_path = output_dir / "cloudnative_results.md"
    with open(md_path, "w") as f:
        f.write(f"# Cloud Native Benchmark Results\n")
        f.write(f"**Model:** Claude Sonnet 4.6  \n")
        f.write(f"**Run:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  \n")
        f.write(f"**Prompts:** {len(results)}\n\n---\n\n")

        # Summary table
        f.write("## Summary\n\n")
        f.write("| # | Category | Label | Tools Called | Tokens In | Tokens Out | Latency |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(results, 1):
            tools_str = ", ".join(r["tool_names"]) if r["tool_names"] else "none"
            in_tok = r["usage"].get("input_tokens", 0) or 0
            out_tok = r["usage"].get("output_tokens", 0) or 0
            f.write(f"| {i} | {r['category']} | {r['label']} | {tools_str} ({r['tool_count']}) | {in_tok:,} | {out_tok:,} | {r['latency_ms']:,}ms |\n")

        # Full responses
        f.write("\n---\n\n## Full Responses\n\n")
        for i, r in enumerate(results, 1):
            f.write(f"### {i}. {r['label']}\n\n")
            f.write(f"**Category:** {r['category']}  \n")
            f.write(f"**Prompt:** {r['prompt']}\n\n")
            f.write(f"**Tools called ({r['tool_count']}):** {', '.join(r['tool_names']) or 'none'}  \n")
            in_tok = r["usage"].get("input_tokens", 0) or 0
            out_tok = r["usage"].get("output_tokens", 0) or 0
            f.write(f"**Tokens:** {in_tok:,} in / {out_tok:,} out  \n")
            f.write(f"**Latency:** {r['latency_ms']:,}ms\n\n")
            f.write(f"**Response:**\n\n{r['text']}\n\n---\n\n")

    print(f"Results saved to:\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    run_benchmarks()
