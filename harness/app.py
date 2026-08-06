"""Flask app: compare a model's full-harness run vs a naive-loop run, side-by-side.

    cd precisely-mcp-test && python3 -m harness.app
    open http://localhost:5001

Routes:
    GET /                     serve the single-page UI
    GET /api/models           which models are configured/usable
    GET /api/stream?model=&mode=&prompt=   one streaming run (Server-Sent Events)
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from dotenv import load_dotenv
from flask import Flask, Response, request

from harness import cache, mcp
from harness.harness import Harness, PRICING, VALID_MODELS

load_dotenv()

_UI_PATH = Path(__file__).parent.parent / "ui" / "index.html"
_RAW_TOOLS: list[dict] | None = None


def _get_raw_tools() -> list[dict]:
    """Fetch the MCP tool list once and cache it for the process."""
    global _RAW_TOOLS
    if _RAW_TOOLS is None:
        _RAW_TOOLS = mcp.list_raw_tools()
    return _RAW_TOOLS


def _harness(model: str, model_id: str | None = None) -> Harness:
    """Build a Harness sharing the cached tool list (overridable in tests)."""
    return Harness(model, model_id=model_id or None, raw_tools=_get_raw_tools())


# Candidate model ids offered in the dropdown, per provider. This is the single
# source of truth — the UI builds each <select> from what /api/models returns here,
# and every id is live-validated (see _validate_model) so a retired id shows up as a
# disabled option instead of silently 404ing into a null result at run time.
#
# Pruned 2026-08-05: gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.0-flash and
# gemini-3-pro-preview all now return 404 "no longer available" for this project — they
# still appear in Google's list-models endpoint but fail on generateContent, so they are
# removed here. Validation would disable them anyway; pruning keeps the menu clean.
PROVIDER_MODEL_CANDIDATES = {
    "claude": [
        "claude-sonnet-4-6", "claude-sonnet-5", "claude-opus-4-8",
        "claude-opus-4-7", "claude-haiku-4-5-20251001", "claude-fable-5",
    ],
    "openai": [
        "gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
        "gpt-5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.5",
    ],
    "gemini": [
        "gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-3.5-flash",
    ],
    "llama": ["llama3.1:8b-16k", "llama3.1:8b", "llama3.2:latest"],
}

# Guard: every dropdown model must be in PRICING, or its cost silently shows "n/a".
# Warn loudly at import instead of discovering it mid-demo. (See harness.PRICING.)
_UNPRICED = [mid for ids in PROVIDER_MODEL_CANDIDATES.values() for mid in ids if mid not in PRICING]
if _UNPRICED:
    import sys as _sys
    print(f"WARNING: dropdown models missing from PRICING (cost will show n/a): {_UNPRICED}", file=_sys.stderr)

_DEFAULT_MODEL_IDS = {
    "claude": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-pro",
    "llama":  "llama3.1:8b-16k",
}

_MODEL_ID_ENV = {
    "claude": "CLAUDE_MODEL",
    "openai": "OPENAI_MODEL",
    "gemini": "GEMINI_MODEL",
    "llama":  "LLAMA_MODEL",
}

# A validated id is trusted for this long before it's re-probed. Providers retire models
# without warning, so a short TTL keeps the menu honest without a live call every load.
_VALIDATE_TTL = float(os.environ.get("MODEL_VALIDATE_TTL", "600"))
_MODEL_STATUS: dict[tuple[str, str], tuple[float, bool, str]] = {}  # (provider,id) -> (ts, usable, reason)


def _short_reason(exc: Exception) -> str:
    """Boil a provider SDK error down to a one-line, human-readable cause."""
    msg = str(exc)
    low = msg.lower()
    if "no longer available" in low or "not found" in low or "404" in msg:
        return "retired by provider"
    if "401" in msg or "403" in msg or "api key" in low or "permission" in low or "authentication" in low:
        return "auth / key problem"
    if "429" in msg or "quota" in low or "rate" in low:
        return "rate limited / quota"
    if "503" in msg or "overloaded" in low or "unavailable" in low:
        return "temporarily unavailable"
    return msg[:80]


def _probe(provider: str, model_id: str) -> tuple[bool, str]:
    """One minimal live call to confirm a model id actually works right now.

    Cheap on purpose — a ~16-token completion — but it catches exactly what a presence
    check misses: retired ids, revoked keys, exhausted quota. Llama is checked against the
    locally-pulled Ollama tags (no token cost).
    """
    try:
        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            tk = "max_completion_tokens" if model_id.startswith(("gpt-5", "o1", "o3", "o4")) else "max_tokens"
            client.chat.completions.create(
                model=model_id, messages=[{"role": "user", "content": "hi"}], **{tk: 16})
        elif provider == "gemini":
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            # No thinking override: 2.5-pro / 3.x-pro are thinking-only and reject budget=0.
            client.models.generate_content(
                model=model_id,
                contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
                config=types.GenerateContentConfig(max_output_tokens=32),
            )
        elif provider == "claude":
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            client.messages.create(model=model_id, max_tokens=16, messages=[{"role": "user", "content": "hi"}])
        elif provider == "llama":
            base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").replace("/v1", "")
            tags = httpx.get(base + "/api/tags", timeout=2.0).json().get("models", [])
            if model_id not in {m["name"] for m in tags}:
                return False, "not pulled in Ollama"
        return True, ""
    except Exception as e:
        return False, _short_reason(e)


def _validate_model(provider: str, model_id: str, fresh: bool = False) -> tuple[bool, str]:
    """Cached wrapper around _probe. Re-probes only when the cache entry is stale."""
    key = (provider, model_id)
    now = time.time()
    if not fresh:
        hit = _MODEL_STATUS.get(key)
        if hit and now - hit[0] < _VALIDATE_TTL:
            return hit[1], hit[2]
    usable, reason = _probe(provider, model_id)
    _MODEL_STATUS[key] = (now, usable, reason)
    return usable, reason


def _provider_configured(name: str) -> tuple[bool, str]:
    """Cheap provider-level gate: is this provider even set up? (No token cost.)"""
    if name == "claude":
        ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
        return ok, "" if ok else "ANTHROPIC_API_KEY not set"
    if name == "openai":
        ok = bool(os.environ.get("OPENAI_API_KEY"))
        return ok, "" if ok else "OPENAI_API_KEY not set"
    if name == "gemini":
        ok = bool(os.environ.get("GEMINI_API_KEY"))
        return ok, "" if ok else "GEMINI_API_KEY not set"
    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    try:
        httpx.get(base.replace("/v1", "") + "/api/tags", timeout=1.5)
        return True, ""
    except Exception:
        return False, "Ollama not reachable"


def get_available_models(validate: bool = False, fresh: bool = False) -> list[dict]:
    """Report each provider's candidate models so the UI can offer only what works.

    Two layers, deliberately separated so the cheap one never needs the network:
      - `available` (per provider) is a pure presence/reachability check — is the key set,
        is Ollama up. No API call, so unit tests and offline use stay fast and deterministic.
      - `validate=True` additionally live-probes every candidate id (cached) and fills each
        `models[].usable`/`reason`, so retired ids can be shown disabled. The UI opts into
        this; the plain endpoint and tests don't pay for it.

    Each provider entry carries a `models` list of {id, usable, reason} and a `model_id`
    default that is guaranteed to be a usable id whenever validation found one.
    """
    configured = {name: _provider_configured(name) for name in VALID_MODELS}

    results: dict[tuple[str, str], tuple[bool, str]] = {}
    if validate:
        # Live-validate every candidate of every configured provider, concurrently + cached.
        jobs = [(name, mid) for name in VALID_MODELS if configured[name][0]
                for mid in PROVIDER_MODEL_CANDIDATES[name]]
        if jobs:
            with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as ex:
                futs = {ex.submit(_validate_model, n, m, fresh): (n, m) for n, m in jobs}
                for fut in as_completed(futs):
                    results[futs[fut]] = fut.result()

    out = []
    for name in VALID_MODELS:
        is_config, why = configured[name]
        models = []
        for mid in PROVIDER_MODEL_CANDIDATES[name]:
            if not is_config:
                usable, reason = False, why
            elif validate:
                usable, reason = results.get((name, mid), (False, why))
            else:
                usable, reason = True, ""   # unchecked — assumed usable until validated
            models.append({"id": mid, "usable": usable, "reason": reason})

        usable_ids = [m["id"] for m in models if m["usable"]]
        env_default = os.environ.get(_MODEL_ID_ENV[name], _DEFAULT_MODEL_IDS[name])
        default_id = env_default if env_default in usable_ids else (usable_ids[0] if usable_ids else env_default)
        # A card is available if configured; when validating, also require a usable model.
        available = is_config and (bool(usable_ids) if validate else True)
        reason = "" if available else (why if not is_config else "no usable models")
        out.append({"name": name, "model_id": default_id, "available": available,
                    "reason": reason, "models": models})
    return out


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return _UI_PATH.read_text(), 200, {"Content-Type": "text/html"}

    @app.get("/api/models")
    def models():
        # `validate=1` live-probes each model (the UI opts in); `fresh=1` also bypasses
        # the validation cache and re-probes. Plain GET stays cheap and network-free.
        validate = request.args.get("validate", "").lower() in ("1", "true", "yes")
        fresh = request.args.get("fresh", "").lower() in ("1", "true", "yes")
        return Response(json.dumps(get_available_models(validate, fresh)), mimetype="application/json")

    @app.get("/api/stream")
    def stream():
        model = request.args.get("model", "claude")
        mode = request.args.get("mode", "harness")
        prompt = request.args.get("prompt", "")
        model_id = request.args.get("model_id", "").strip() or None
        # Demo caching: identical prompts replay from disk instead of re-running the
        # LLM. `fresh=1` forces a genuine live run; `speed` scales the replay pacing
        # (0 = instant, 1 = default simulated-live, 2 = slower). Env vars set defaults.
        fresh = request.args.get("fresh", "").lower() in ("1", "true", "yes")
        speed_raw = request.args.get("speed", os.environ.get("CACHE_REPLAY_SPEED", "1.0"))

        def generate():
            try:
                try:
                    speed = float(speed_raw)
                except (TypeError, ValueError):
                    speed = 1.0  # bad ?speed= value shouldn't 500 the stream
                if model not in VALID_MODELS:
                    raise ValueError(f"unknown model '{model}'")

                cached = None if fresh else cache.load(model, model_id, mode, prompt)
                if cached is not None:
                    for event in cached:
                        yield f"data: {json.dumps(event)}\n\n"
                        d = cache.replay_delay(event, speed)
                        if d:
                            time.sleep(d)
                    return

                recorded = []
                for event in _harness(model, model_id).run_stream(prompt, mode=mode):
                    recorded.append(event)
                    yield f"data: {json.dumps(event)}\n\n"
                cache.save(model, model_id, mode, prompt, recorded)
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'where': 'run', 'message': str(e)})}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def main() -> None:
    create_app().run(host="127.0.0.1", port=5001, threaded=True)


if __name__ == "__main__":
    main()
