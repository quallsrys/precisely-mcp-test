"""Interactive CLI for the harness — ask the Precisely MCP tools anything, on any model.

    python -m harness.cli                                   # interactive, claude (default model)
    python -m harness.cli gemini                            # interactive, gemini (default model)
    python -m harness.cli claude --id claude-opus-4-8       # interactive, a specific model id
    python -m harness.cli openai --id gpt-5.4-mini "flood risk at 950 Josephine St, Denver CO"

Interactive commands:
    /model <claude|gemini|openai|llama> [exact-model-id]   switch model (and optionally pin the id)
    /help                                                  show commands
    /quit                                                  exit

Default model ids live in .env (CLAUDE_MODEL, OPENAI_MODEL, GEMINI_MODEL, LLAMA_MODEL).
Pass an exact id here to override per session. Cost uses list price unless ENTERPRISE_DISCOUNT
is set in .env.
"""

import sys

from harness import Harness
from harness.harness import VALID_MODELS

# Cache one Harness per (provider, model_id) so switching back doesn't re-fetch the tool list.
_cache: dict[tuple, Harness] = {}


def _get(model: str, model_id: str | None) -> Harness:
    key = (model, model_id)
    if key not in _cache:
        label = f"{model}:{model_id}" if model_id else f"{model} (default model)"
        print(f"  (loading {label} + MCP tools…)")
        _cache[key] = Harness(model, model_id)
    return _cache[key]


def _ask(model: str, model_id: str | None, prompt: str) -> None:
    try:
        harness = _get(model, model_id)
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
    if r["cost_usd"] is None:
        cost = f"cost n/a ({r['model']} not in pricing table)"
    else:
        cost = f"${r['cost_usd']} ({r['cost_basis']})"
    flag = "" if r["plan_complete"] else f"  ⚠ never called: {', '.join(r['plan_uncalled'])}"

    print("\n" + "─" * 64)
    print(f"model: {r['model']}")
    print(f"tools called: {', '.join(r['tools_called']) or 'none'}")
    print(
        f"{m['input_tokens']:,} in / {m['output_tokens']:,} out tokens  |  "
        f"{m['rounds']} rounds  |  {cost}  |  {secs:.1f}s{flag}"
    )
    print()


def _repl(model: str, model_id: str | None) -> None:
    print("Precisely MCP harness — interactive. /help for commands, /quit to exit.")
    print(f"Model: {model}" + (f" ({model_id})" if model_id else " (default)"))
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
            print(f"  /model <{'|'.join(VALID_MODELS)}> [exact-model-id]   switch model")
            print("  /quit                                                  exit")
            continue
        if line.startswith("/model"):
            parts = line.split()
            if len(parts) >= 2 and parts[1] in VALID_MODELS:
                model = parts[1]
                model_id = parts[2] if len(parts) >= 3 else None
                print(f"  switched to {model}" + (f":{model_id}" if model_id else " (default model)"))
            else:
                print(f"  usage: /model <{'|'.join(VALID_MODELS)}> [exact-model-id]")
            continue
        if line.startswith("/"):
            print("  unknown command — /help for options")
            continue
        _ask(model, model_id, line)


def main() -> None:
    args = sys.argv[1:]
    model = "claude"
    model_id = None

    if args and args[0] in VALID_MODELS:
        model = args.pop(0)
    if args and args[0] == "--id":
        args.pop(0)
        model_id = args.pop(0) if args else None

    if args:  # remaining args are a one-shot prompt
        _ask(model, model_id, " ".join(args))
    else:
        _repl(model, model_id)


if __name__ == "__main__":
    main()
