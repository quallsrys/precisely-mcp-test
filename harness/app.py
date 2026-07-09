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
from pathlib import Path

import httpx
from dotenv import load_dotenv
from flask import Flask, Response, request

from harness import mcp
from harness.harness import Harness, VALID_MODELS

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


def get_available_models() -> list[dict]:
    """Report each model's availability so the UI can disable unconfigured ones."""
    out = []
    for name in VALID_MODELS:
        model_id = os.environ.get(_MODEL_ID_ENV[name], _DEFAULT_MODEL_IDS[name])
        if name == "claude":
            ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
            reason = "" if ok else "ANTHROPIC_API_KEY not set"
        elif name == "openai":
            ok = bool(os.environ.get("OPENAI_API_KEY"))
            reason = "" if ok else "OPENAI_API_KEY not set"
        elif name == "gemini":
            ok = bool(os.environ.get("GEMINI_API_KEY"))
            reason = "" if ok else "GEMINI_API_KEY not set"
        else:  # llama
            base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
            try:
                httpx.get(base.replace("/v1", "") + "/api/tags", timeout=1.5)
                ok, reason = True, ""
            except Exception:
                ok, reason = False, "Ollama not reachable"
        out.append({"name": name, "model_id": model_id, "available": ok, "reason": reason})
    return out


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return _UI_PATH.read_text(), 200, {"Content-Type": "text/html"}

    @app.get("/api/models")
    def models():
        return Response(json.dumps(get_available_models()), mimetype="application/json")

    @app.get("/api/stream")
    def stream():
        model = request.args.get("model", "claude")
        mode = request.args.get("mode", "harness")
        prompt = request.args.get("prompt", "")
        model_id = request.args.get("model_id", "").strip() or None

        def generate():
            try:
                if model not in VALID_MODELS:
                    raise ValueError(f"unknown model '{model}'")
                for event in _harness(model, model_id).run_stream(prompt, mode=mode):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'where': 'run', 'message': str(e)})}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def main() -> None:
    create_app().run(host="127.0.0.1", port=5001, threaded=True)


if __name__ == "__main__":
    main()
