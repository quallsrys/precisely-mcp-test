"""
Builds a plain side-by-side comparison of Claude vs Gemini vs OpenAI
for every Cloud Native benchmark prompt.
Output: benchmarks/side_by_side.md
"""

import json
from pathlib import Path

output_dir = Path(__file__).parent

with open(output_dir / "cloudnative_results.json") as f:
    claude_list = json.load(f)["results"]
    claude = {r["label"]: r for r in claude_list}
    prompt_order = [r["label"] for r in claude_list]

with open(output_dir / "gemini_compare.json") as f:
    gemini = {r["label"]: r for r in json.load(f)["results"]}

with open(output_dir / "openai_compare.json") as f:
    openai = {r["label"]: r for r in json.load(f)["results"]}

CATEGORY_LABELS = {
    "telecom": "Telecom",
    "insurance": "P&C Insurance",
    "financial": "Financial Services",
    "retail": "Retail",
}

lines = []
lines.append("# Cloud Native Benchmark — Side-by-Side Comparison")
lines.append("")
lines.append("Claude Sonnet 4.6 is the baseline. Gemini 2.5 Pro and GPT-4o-mini are scored against it.")
lines.append("Pass threshold: ≥75% tool overlap with Claude + ≥1 tool called + ≥3/5 topic keywords.")
lines.append("")
lines.append("---")
lines.append("")

current_category = None

for label in prompt_order:
    c = claude.get(label, {})
    g = gemini.get(label, {})
    o = openai.get(label, {})

    category = c.get("category", "")
    if category != current_category:
        current_category = category
        lines.append(f"## {CATEGORY_LABELS.get(category, category.title())}")
        lines.append("")

    # Prompt header
    lines.append(f"### {label.replace('_', ' ').title()}")
    lines.append("")
    lines.append(f"**Prompt:** {c.get('prompt', '')}")
    lines.append("")

    # Tool comparison table
    claude_tools = sorted(set(c.get("tool_names", [])))
    gemini_tools = sorted(set(g.get("tool_names", [])))
    openai_tools = sorted(set(o.get("tool_names", [])))

    all_tools = sorted(set(claude_tools) | set(gemini_tools) | set(openai_tools))

    lines.append("#### Tools Called")
    lines.append("")
    lines.append("| Tool | Claude | Gemini | OpenAI |")
    lines.append("|---|---|---|---|")
    for tool in all_tools:
        c_mark = "✅" if tool in claude_tools else "—"
        g_mark = "✅" if tool in gemini_tools else "—"
        o_mark = "✅" if tool in openai_tools else "—"
        lines.append(f"| `{tool}` | {c_mark} | {g_mark} | {o_mark} |")
    lines.append("")

    # Score summary
    g_pass = "✅ PASS" if g.get("passed") else "❌ FAIL"
    o_pass = "✅ PASS" if o.get("passed") else "❌ FAIL"
    g_overlap = g.get("overlap_pct", 0)
    o_overlap = o.get("overlap_pct", 0)
    g_topics = len(g.get("keywords_hit", []))
    o_topics = len(o.get("keywords_hit", []))

    lines.append("#### Score")
    lines.append("")
    lines.append("| | Claude | Gemini | OpenAI |")
    lines.append("|---|---|---|---|")
    lines.append(f"| Unique tools | {len(claude_tools)} (baseline) | {len(gemini_tools)} ({g_overlap}% overlap) | {len(openai_tools)} ({o_overlap}% overlap) |")
    lines.append(f"| Topics covered | — | {g_topics}/5 | {o_topics}/5 |")

    c_tok_in = c.get("usage", {}).get("input_tokens", 0) or 0
    g_tok_in = g.get("usage", {}).get("input_tokens", 0) or 0
    o_tok_in = o.get("usage", {}).get("input_tokens", 0) or 0
    lines.append(f"| Input tokens | {c_tok_in:,} | {g_tok_in:,} | {o_tok_in:,} |")
    lines.append(f"| Latency | {c.get('latency_ms',0):,}ms | {g.get('latency_ms',0):,}ms | {o.get('latency_ms',0):,}ms |")
    lines.append(f"| Result | baseline | {g_pass} | {o_pass} |")
    lines.append("")

    # Responses
    lines.append("#### Claude Response")
    lines.append("")
    lines.append(c.get("text", "*(no response)*"))
    lines.append("")
    lines.append("#### Gemini Response")
    lines.append("")
    lines.append(g.get("text", "*(no response)*") or "*(no response)*")
    lines.append("")
    lines.append("#### OpenAI Response")
    lines.append("")
    lines.append(o.get("text", "*(no response)*") or "*(no response)*")
    lines.append("")
    lines.append("---")
    lines.append("")

out_path = output_dir / "side_by_side.md"
out_path.write_text("\n".join(lines))
print(f"Saved: {out_path}")
print(f"Prompts: {len(prompt_order)}")
