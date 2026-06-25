"""
Multi-LLM benchmark comparison — runs all 19 Cloud Native prompts through
one LLM at a time, scoring each against the Claude baseline.

Usage:
    python compare_cloudnative_prompts.py gemini
    python compare_cloudnative_prompts.py openai
    python compare_cloudnative_prompts.py llama

Pass criteria (all three must be true):
  1. Tool overlap >= 75% of Claude's unique tools for that prompt
  2. At least one tool called (no zero-call responses)
  3. Response covers the required output topics (>=3 of 5 keywords present)

Results are checkpointed after every prompt to
benchmarks/<llm>_compare.json so progress is never lost.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

TOOL_OVERLAP_THRESHOLD = 0.75
PER_PROMPT_TIMEOUT = 300  # seconds — skip prompt if it hangs this long

TOPIC_KEYWORDS = {
    "telecom_expansion_market_st":          ["demographics", "serviceability", "network", "neighborhood", "broadband"],
    "telecom_commercial_property":          ["building", "serviceability", "tenant", "units", "deployment"],
    "telecom_address_correction":           ["address", "ohio", "oh", "44022", "corrected"],
    "telecom_fraud_detection":              ["address", "risk", "residential", "verify", "property"],
    "insurance_adjuster_summary":           ["flood", "fire", "building", "property", "risk"],
    "insurance_cat_exposure":               ["flood", "earthquake", "wildfire", "hazard", "risk"],
    "insurance_storm_claim":                ["flood", "property", "risk", "damage", "storm"],
    "insurance_agent_network":              ["demographics", "density", "placement", "zip", "agent"],
    "financial_ownership_lookup":           ["ownership", "parcel", "assessed", "property", "value"],
    "financial_multifamily_report":         ["building", "parcel", "demographics", "ownership", "address"],
    "financial_hazard_mortgage":            ["flood", "earthquake", "risk", "property", "mortgage"],
    "financial_merchant_enrichment":        ["address", "verified", "tax", "location", "points"],
    "financial_loan_fraud":                 ["address", "property", "risk", "verified", "demographic"],
    "financial_branch_atm_optimization":    ["demographics", "income", "placement", "zip", "density"],
    "retail_distribution_chicago":          ["property", "flood", "crime", "demographics", "chicago"],
    "retail_commercial_intelligence_nyc":   ["building", "parcel", "property", "risk", "address"],
    "retail_site_evaluation":               ["demographics", "income", "retail", "recommendation", "density"],
    "retail_zip_expansion":                 ["demographics", "income", "density", "zip", "rank"],
    "retail_risk_profile":                  ["flood", "fire", "crime", "risk", "mitigation"],
}


def score_result(label: str, result: dict, claude_unique_tools: set) -> dict:
    tool_names = set(tc["name"] for tc in result.get("tool_calls", []))
    tool_count = len(result.get("tool_calls", []))
    text_lower = result.get("text", "").lower()

    if claude_unique_tools:
        overlap_count = len(tool_names & claude_unique_tools)
        overlap_pct = overlap_count / len(claude_unique_tools)
    else:
        overlap_count, overlap_pct = 0, 1.0

    criterion_1 = overlap_pct >= TOOL_OVERLAP_THRESHOLD
    criterion_2 = tool_count > 0

    keywords = TOPIC_KEYWORDS.get(label, [])
    keywords_hit = [kw for kw in keywords if kw in text_lower]
    criterion_3 = len(keywords_hit) >= 3

    return {
        "passed": criterion_1 and criterion_2 and criterion_3,
        "tool_names": sorted(tool_names),
        "tool_count": tool_count,
        "overlap_count": overlap_count,
        "overlap_pct": round(overlap_pct * 100, 1),
        "criterion_1_tool_overlap": criterion_1,
        "criterion_2_tool_called": criterion_2,
        "criterion_3_topics_covered": criterion_3,
        "keywords_hit": keywords_hit,
        "text": result.get("text", ""),
        "latency_ms": result.get("latency_ms", 0),
        "usage": result.get("usage", {}),
    }


def ask_with_timeout(client, name: str, prompt: str) -> dict:
    """Call client.ask() and raise TimeoutError if it exceeds PER_PROMPT_TIMEOUT."""
    import threading

    result_box = [None]
    error_box = [None]

    def target():
        try:
            if name == "llama":
                result_box[0] = client.ask(prompt, max_tokens=4096)
            else:
                result_box[0] = client.ask(prompt, max_tokens=8192)
        except Exception as e:
            error_box[0] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=PER_PROMPT_TIMEOUT)

    if t.is_alive():
        raise TimeoutError(f"prompt timed out after {PER_PROMPT_TIMEOUT}s")
    if error_box[0]:
        raise error_box[0]
    return result_box[0]


def run_llm(name: str, prompts: list, claude_baselines: dict, output_dir: Path) -> list:
    # Load existing checkpoint if present (resume after interruption)
    checkpoint_path = output_dir / f"{name}_compare.json"
    if checkpoint_path.exists():
        with open(checkpoint_path) as f:
            existing = json.load(f)
        completed_labels = {r["label"] for r in existing["results"]}
        results = existing["results"]
        print(f"Resuming — {len(completed_labels)} prompts already done.")
    else:
        completed_labels = set()
        results = []

    # Import client lazily so we only load what we need
    if name == "gemini":
        from clients.gemini_client import GeminiClient
        client = GeminiClient()
        delay = float(os.environ.get("GEMINI_DELAY_SECONDS", "10"))
    elif name == "openai":
        from clients.openai_client import OpenAIClient
        client = OpenAIClient()
        delay = float(os.environ.get("OPENAI_DELAY_SECONDS", "10"))
    elif name == "llama":
        from clients.llama_client import LlamaClient
        client = LlamaClient()
        delay = 2.0
    else:
        raise ValueError(f"Unknown LLM: {name}")

    print(f"\n{'='*60}")
    print(f"Running {len(prompts)} prompts on {name} (delay={delay}s, timeout={PER_PROMPT_TIMEOUT}s)")
    print(f"{'='*60}\n")

    for i, (category, label, prompt) in enumerate(prompts, 1):
        if label in completed_labels:
            print(f"[{i:02d}/{len(prompts)}] SKIP (already done): {label}")
            continue

        print(f"[{i:02d}/{len(prompts)}] {name} / {label}")
        time.sleep(delay)

        try:
            result = ask_with_timeout(client, name, prompt)
            status = "ok"
        except TimeoutError as e:
            result = {"text": f"TIMEOUT: {e}", "tool_calls": [], "latency_ms": PER_PROMPT_TIMEOUT * 1000, "usage": {}}
            status = "timeout"
            print(f"         ⚠️  TIMEOUT after {PER_PROMPT_TIMEOUT}s — skipping\n")
        except Exception as e:
            result = {"text": f"ERROR: {e}", "tool_calls": [], "latency_ms": 0, "usage": {}}
            status = f"error"
            print(f"         ⚠️  ERROR: {e}\n")

        claude_unique = claude_baselines.get(label, set())
        scored = score_result(label, result, claude_unique)
        scored.update({"category": category, "label": label, "prompt": prompt, "status": status, "llm": name})

        verdict = "PASS ✅" if scored["passed"] else "FAIL ❌"
        print(f"         {verdict}  tools={scored['tool_count']}  overlap={scored['overlap_pct']}%  topics={len(scored['keywords_hit'])}/5")
        print(f"         tools: {', '.join(scored['tool_names']) or 'none'}\n")

        results.append(scored)

        # Checkpoint after every prompt
        with open(checkpoint_path, "w") as f:
            json.dump({"llm": name, "run_at": datetime.now().isoformat(), "results": results}, f, indent=2)

    passed = sum(1 for r in results if r["passed"])
    print(f"\n{name.upper()} COMPLETE: {passed}/{len(results)} passed ({passed/len(results)*100:.0f}%)")
    return results


def build_report(output_dir: Path, claude_baselines: dict, prompts: list):
    """Merge all per-LLM checkpoint files into a single comparison report."""
    all_results = {}
    for name in ("gemini", "openai", "llama"):
        p = output_dir / f"{name}_compare.json"
        if p.exists():
            with open(p) as f:
                all_results[name] = json.load(f)["results"]

    md_path = output_dir / "comparison_results.md"
    with open(md_path, "w") as f:
        f.write("# Cloud Native Benchmark — Multi-LLM Comparison\n\n")
        f.write(f"**Run:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  \n")
        f.write(f"**Baseline:** Claude Sonnet 4.6  \n")
        f.write(f"**Pass criteria:** ≥75% tool overlap with Claude + ≥1 tool called + ≥3/5 topic keywords\n\n---\n\n")

        f.write("## Pass Rate Summary\n\n")
        f.write("| LLM | Passed | Failed | Pass Rate |\n")
        f.write("|---|---|---|---|\n")
        for name, results in all_results.items():
            passed = sum(1 for r in results if r["passed"])
            f.write(f"| {name} | {passed} | {len(results)-passed} | {passed/len(results)*100:.0f}% |\n")

        f.write("\n---\n\n## Per-Prompt Scorecard\n\n")
        f.write("| # | Label | Gemini | OpenAI | Llama |\n")
        f.write("|---|---|---|---|---|\n")
        by_label = {name: {r["label"]: r for r in results} for name, results in all_results.items()}
        for i, (_, label, _) in enumerate(prompts, 1):
            def fmt(r):
                if not r:
                    return "—"
                return f"{'✅' if r['passed'] else '❌'} {r['overlap_pct']}% / {r['tool_count']} tools"
            f.write(f"| {i} | {label} | {fmt(by_label.get('gemini', {}).get(label))} | {fmt(by_label.get('openai', {}).get(label))} | {fmt(by_label.get('llama', {}).get(label))} |\n")

        for name, results in all_results.items():
            f.write(f"\n---\n\n## {name.title()} — Detailed Results\n\n")
            for r in results:
                verdict = "✅ PASS" if r["passed"] else "❌ FAIL"
                in_tok = r["usage"].get("input_tokens", 0) or 0
                out_tok = r["usage"].get("output_tokens", 0) or 0
                f.write(f"### {r['label']} — {verdict}\n\n")
                f.write(f"- **Tool overlap:** {r['overlap_count']} / {len(claude_baselines.get(r['label'], set()))} ({r['overlap_pct']}%) — {'✅' if r['criterion_1_tool_overlap'] else '❌'}\n")
                f.write(f"- **Tools called:** {r['tool_count']} — {'✅' if r['criterion_2_tool_called'] else '❌'}\n")
                f.write(f"- **Topics covered:** {len(r['keywords_hit'])}/5 ({', '.join(r['keywords_hit']) or 'none'}) — {'✅' if r['criterion_3_topics_covered'] else '❌'}\n")
                f.write(f"- **Tokens:** {in_tok:,} in / {out_tok:,} out | **Latency:** {r['latency_ms']:,}ms\n")
                f.write(f"- **Tools:** {', '.join(r['tool_names']) or 'none'}\n\n")
                f.write(f"**Response:**\n\n{r['text']}\n\n")

    print(f"Report saved: {md_path}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("gemini", "openai", "llama", "report"):
        print("Usage: python compare_cloudnative_prompts.py <gemini|openai|llama|report>")
        sys.exit(1)

    target = sys.argv[1]
    output_dir = Path(__file__).parent

    with open(output_dir / "cloudnative_results.json") as f:
        claude_data = json.load(f)

    claude_baselines = {r["label"]: set(r["tool_names"]) for r in claude_data["results"]}
    prompts = [(r["category"], r["label"], r["prompt"]) for r in claude_data["results"]]

    if target == "report":
        build_report(output_dir, claude_baselines, prompts)
    else:
        run_llm(target, prompts, claude_baselines, output_dir)
        build_report(output_dir, claude_baselines, prompts)


if __name__ == "__main__":
    main()
