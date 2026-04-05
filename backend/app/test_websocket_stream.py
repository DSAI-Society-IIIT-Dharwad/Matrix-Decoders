from __future__ import annotations

import unittest

from app.websocket_stream import (
    build_stream_complete_event,
    build_stream_started_event,
    enrich_stream_event,
    new_stream_state,
    utc_now_iso,
)


class WebSocketStreamTests(unittest.TestCase):
    def test_utc_now_iso_is_zulu_timestamp(self) -> None:
        stamp = utc_now_iso()
        self.assertTrue(stamp.endswith("Z"))
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T")

    def test_enrich_stream_event_adds_metadata_and_monotonic_index(self) -> None:
        state = new_stream_state("text", "session-1")
        first = enrich_stream_event(state, {"type": "delta", "text": "hello"})
        second = enrich_stream_event(state, {"type": "delta", "text": "world"})

        self.assertEqual(first["stream_id"], second["stream_id"])
        self.assertEqual(first["session_id"], "session-1")
        self.assertEqual(first["channel"], "text")
        self.assertEqual(first["event_index"], 1)
        self.assertEqual(second["event_index"], 2)
        self.assertIn("emitted_at", first)
        self.assertIn("emitted_at", second)

    def test_start_and_complete_events_are_enriched(self) -> None:
        state = new_stream_state("tts", "session-2")
        started = build_stream_started_event(state, {"segment_count": 2})
        completed = build_stream_complete_event(state, "ok", 123, {"provider": "indic"})

        self.assertEqual(started["type"], "stream_started")
        self.assertEqual(started["status"], "started")
        self.assertEqual(started["event_index"], 1)
        self.assertEqual(started["details"]["segment_count"], 2)

        self.assertEqual(completed["type"], "stream_complete")
        self.assertEqual(completed["status"], "ok")
        self.assertEqual(completed["latency_ms"], 123)
        self.assertEqual(completed["event_index"], 2)
        self.assertEqual(completed["details"]["provider"], "indic")


if __name__ == "__main__":
    unittest.main()
