"""Disk-backed cache of full run event-streams, so identical demo prompts replay
instantly instead of re-running the LLM + live MCP tool calls.

Key   = (model, model_id, mode, normalized prompt)
Value = the ordered list of events run_stream produced (planning, plan, round,
        tool_call, tool_result, answer, done) — the whole thing the UI animates.

Stored as JSON under cache/ so it survives restarts and can be pre-warmed before
a live demo (see harness/warmup.py). Only *complete* runs (those that reached a
terminal 'done' event) are cached, so a failed/partial run never poisons the cache.
"""

import hashlib
import json
import re
import time
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "cache"

# Bump to invalidate every cached replay at once (e.g. after changing the MCP tool set,
# which the key can't otherwise see).
CACHE_VERSION = "1"
_FINGERPRINT: str | None = None


def _fingerprint() -> str:
    """Short hash of things that change a run's meaning but aren't in the raw key — the
    system prompt and CACHE_VERSION. Folded into every key so editing system_prompt.md
    automatically invalidates stale replays instead of serving them."""
    global _FINGERPRINT
    if _FINGERPRINT is None:
        sp = Path(__file__).parent.parent / "system_prompt.md"
        body = sp.read_text() if sp.exists() else ""
        _FINGERPRINT = hashlib.sha256((CACHE_VERSION + "\x1f" + body).encode("utf-8")).hexdigest()[:8]
    return _FINGERPRINT

# Per-event-type pause (seconds) used to make a cached replay feel like a live run
# rather than snapping in all at once. Multiplied by the `speed` factor at replay
# time (speed=0 -> instant, speed=2 -> half speed). tool_result is handled specially:
# it sleeps proportional to the tool's real recorded latency, capped for snappiness.
_REPLAY_DELAYS = {
    "planning": 0.45,   # model "thinking" before it returns a plan
    "plan":     0.25,
    "round":    0.50,   # each model round-trip
    "tool_call":0.15,
    "answer":   0.35,
    "done":     0.0,
}
_DEFAULT_DELAY = 0.12
_TOOL_RESULT_CAP = 0.6  # never wait longer than this to "replay" a tool call


def _normalize(prompt: str) -> str:
    """Collapse whitespace + lowercase so trivially different typing still hits cache."""
    return re.sub(r"\s+", " ", (prompt or "").strip()).lower()


def cache_key(model: str, model_id: str | None, mode: str, prompt: str) -> str:
    raw = "\x1f".join([_fingerprint(), model, model_id or "", mode, _normalize(prompt)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def is_complete(events: list[dict]) -> bool:
    """A run is cacheable only if it finished — reached 'done' with no 'error'."""
    types = {e.get("type") for e in events}
    return "done" in types and "error" not in types


def load(model: str, model_id: str | None, mode: str, prompt: str) -> list[dict] | None:
    """Return the cached event list for this run, or None on miss/corrupt file."""
    p = _path(cache_key(model, model_id, mode, prompt))
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("events")
    except (json.JSONDecodeError, OSError, AttributeError):
        return None


def save(model: str, model_id: str | None, mode: str, prompt: str, events: list[dict]) -> bool:
    """Persist a completed run. Returns True if written, False if skipped (incomplete)."""
    if not is_complete(events):
        return False
    CACHE_DIR.mkdir(exist_ok=True)
    payload = {
        "model": model, "model_id": model_id, "mode": mode,
        "prompt": prompt, "cached_at": time.time(), "events": events,
    }
    _path(cache_key(model, model_id, mode, prompt)).write_text(json.dumps(payload))
    return True


def replay_delay(event: dict, speed: float) -> float:
    """How long to pause after emitting `event` during a simulated-live replay."""
    if speed <= 0:
        return 0.0
    if event.get("type") == "tool_result":
        base = min(event.get("ms", 0) / 1000.0, _TOOL_RESULT_CAP)
    else:
        base = _REPLAY_DELAYS.get(event.get("type"), _DEFAULT_DELAY)
    return base * speed
