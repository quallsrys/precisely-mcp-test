"""Unit tests for the Flask app — model availability + SSE plumbing, no live model."""

import json

from harness import app as app_mod


def test_available_models_reports_claude_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    models = app_mod.get_available_models()
    by_name = {m["name"]: m for m in models}
    assert by_name["claude"]["available"] is True
    assert by_name["openai"]["available"] is False
    assert "reason" in by_name["openai"]


def test_models_endpoint_returns_json():
    client = app_mod.create_app().test_client()
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert {m["name"] for m in data} == {"claude", "gemini", "openai", "llama"}


def test_stream_endpoint_emits_sse_done_event(monkeypatch):
    # Replace the harness factory with a fake that yields one done event.
    def fake_factory(model):
        class FakeHarness:
            def run_stream(self, prompt, mode="harness", max_tokens=4096):
                yield {"type": "done", "text": "hi", "mode": mode, "metrics": {}, "cost_usd": 0.0}
        return FakeHarness()
    monkeypatch.setattr(app_mod, "_harness", fake_factory)

    client = app_mod.create_app().test_client()
    resp = client.get("/api/stream?model=claude&mode=harness&prompt=hello")
    body = resp.get_data(as_text=True)
    assert "data:" in body
    # The last data frame parses as the done event.
    frames = [line[len("data:"):].strip() for line in body.splitlines() if line.startswith("data:")]
    last = json.loads(frames[-1])
    assert last["type"] == "done"
    assert last["mode"] == "harness"
