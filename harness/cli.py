"""Interactive CLI for the harness — ask the Precisely MCP tools anything, on any model.

    python -m harness.cli                      # interactive, starts on claude
    python -m harness.cli gemini               # interactive, starts on gemini
    python -m harness.cli claude "flood risk at 950 Josephine St, Denver CO"   # one-shot

Interactive commands:
    /model <claude|gemini|openai|llama>   switch model (keeps the session going)
    /help                                 show commands
    /quit                                 exit
"""

import sys

from harness import Harness
from harness.harness import VALID_MODELS

# Cache one Harness per model so switching back doesn't re-fetch the tool list.
_cache: dict[str, Harness] = {}


def _get(model: str) -> Harness:
    if model not in _cache:
        print(f"  (loading {model} + MCP tools…)")
        _cache[model] = Harness(model)
    return _cache[model]


def _ask(model: str, prompt: str) -> None:
    try:
        harness = _get(model)
    except Exception as e:
        print(f"  ⚠️  could not start {model}: {e}\n")
        return

    print(f"[{model}] working… (planning, then executing — Llama can take a couple minutes)")
    try:
        r = harness.run(prompt)
    except Exception as e:
        print(f"  ⚠️  error: {e}\n")
        return

    plan = " → ".join(r["plan"]) or "(planner returned nothing — sent all tools)"
    print(f"[{model}] plan: {plan}\n")
    print(r["text"] or "(no text response)")

    m = r["metrics"]
    secs = (m["model_ms"] + m["tool_ms"]) / 1000
    flag = "" if r["plan_complete"] else f"  ⚠ never called: {', '.join(r['plan_uncalled'])}"
    print("\n" + "─" * 64)
    print(
        f"tools called: {', '.join(r['tools_called']) or 'none'}\n"
        f"{m['input_tokens']:,} in / {m['output_tokens']:,} out tokens  |  "
        f"{m['rounds']} rounds  |  ${r['cost_usd']}  |  {secs:.1f}s{flag}"
    )
    print()


def _repl(model: str) -> None:
    print("Precisely MCP harness — interactive. /help for commands, /quit to exit.")
    print(f"Model: {model}")
    while True:
        try:
            line = input(f"\n{model}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return

        if not line:
            continue
        if line in ("/quit", "/exit", "/q"):
            print("bye")
            return
        if line == "/help":
            print(f"  /model <{'|'.join(VALID_MODELS)}>   switch model")
            print("  /quit                                  exit")
            continue
        if line.startswith("/model"):
            parts = line.split()
            if len(parts) == 2 and parts[1] in VALID_MODELS:
                model = parts[1]
                print(f"  switched to {model}")
            else:
                print(f"  usage: /model <{'|'.join(VALID_MODELS)}>")
            continue
        if line.startswith("/"):
            print("  unknown command — /help for options")
            continue
        _ask(model, line)


def main() -> None:
    args = sys.argv[1:]
    model = "claude"
    if args and args[0] in VALID_MODELS:
        model = args.pop(0)

    if args:  # one-shot: remaining args are the prompt
        _ask(model, " ".join(args))
    else:
        _repl(model)


if __name__ == "__main__":
    main()
