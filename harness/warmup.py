"""Pre-warm the demo cache: run every (prompt x model x mode) combination once so
the cache is populated before a live presentation. After this, every click in the
UI replays from disk instantly and never depends on API latency in the room.

    cd precisely-mcp-test
    python3 -m harness.warmup                 # warm the defaults below
    python3 -m harness.warmup --force         # re-run even if already cached

Edit PROMPTS / MODELS below to match exactly what you plan to demo. MODES defaults
to both so the Harness-vs-Naive view is fully covered (Showdown uses 'harness').
"""

import sys

from harness import cache
from harness.harness import Harness

# ── Configure your demo here ─────────────────────────────────────────────────
PROMPTS = [
    "Assess wildfire and flood risk for 950 Josephine St, Denver CO, for an insurance adjuster.",
]

# (model, model_id) pairs to warm. model_id="" uses the adapter default.
MODELS = [
    ("claude", "claude-sonnet-4-6"),
]

MODES = ("harness", "naive")
# ──────────────────────────────────────────────────────────────────────────────


def warm_one(model: str, model_id: str, mode: str, prompt: str, *, force: bool) -> str:
    mid = model_id or None
    if not force and cache.load(model, mid, mode, prompt) is not None:
        return "skip (cached)"
    events = list(Harness(model, model_id=mid).run_stream(prompt, mode=mode))
    return "saved" if cache.save(model, mid, mode, prompt, events) else "NOT saved (run incomplete)"


def main() -> None:
    force = "--force" in sys.argv
    total = len(PROMPTS) * len(MODELS) * len(MODES)
    i = 0
    for prompt in PROMPTS:
        for model, model_id in MODELS:
            for mode in MODES:
                i += 1
                label = f"[{i}/{total}] {model}/{model_id or 'default'} {mode}: {prompt[:50]}..."
                print(label, flush=True)
                try:
                    print(f"    -> {warm_one(model, model_id, mode, prompt, force=force)}", flush=True)
                except Exception as e:
                    print(f"    -> ERROR: {e}", flush=True)
    print(f"\nDone. Cache dir: {cache.CACHE_DIR}")


if __name__ == "__main__":
    main()
