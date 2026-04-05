from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_stream_state(channel: str, session_id: str) -> dict[str, Any]:
    return {
        "channel": channel,
        "session_id": session_id,
        "stream_id": f"{channel}-{uuid4().hex[:12]}",
        "event_index": 0,
    }


def enrich_stream_event(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    state["event_index"] = int(state.get("event_index", 0)) + 1
    event = dict(payload)
    event["stream_id"] = str(state.get("stream_id", ""))
    event["session_id"] = str(state.get("session_id", ""))
    event["channel"] = str(state.get("channel", ""))
    event["event_index"] = int(state["event_index"])
    event["emitted_at"] = utc_now_iso()
    return event


def build_stream_started_event(state: dict[str, Any], details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"type": "stream_started", "status": "started"}
    if isinstance(details, dict) and details:
        payload["details"] = details
    return enrich_stream_event(state, payload)


def build_stream_complete_event(
    state: dict[str, Any],
    status: str,
    latency_ms: int | float,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "type": "stream_complete",
        "status": status,
        "latency_ms": int(latency_ms),
    }
    if isinstance(details, dict) and details:
        payload["details"] = details
    return enrich_stream_event(state, payload)
