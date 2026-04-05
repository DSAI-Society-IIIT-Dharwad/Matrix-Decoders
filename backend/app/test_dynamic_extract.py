from __future__ import annotations

import unittest

from app.dynamic_extract import extract_dynamic_json, normalize_dynamic_schema


class _FakeClient:
    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    async def stream(self, _messages):
        for chunk in self._chunks:
            yield chunk


class DynamicExtractTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_dynamic_schema_recovers_invalid_fields(self) -> None:
        normalized, issues = normalize_dynamic_schema(
            {
                "type": "array",
                "properties": {
                    "duration_days": {"type": "integer"},
                    "risk_level": {"type": "priority"},
                },
                "required": ["duration_days", "unknown_field"],
            }
        )

        self.assertEqual(normalized["type"], "object")
        self.assertEqual(normalized["properties"]["duration_days"]["type"], "integer")
        self.assertEqual(normalized["properties"]["risk_level"]["type"], "string")
        self.assertEqual(normalized["required"], ["duration_days"])
        self.assertTrue(any("Root schema type must be object" in issue for issue in issues))

    async def test_extract_dynamic_json_parses_llm_json_block(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "symptoms": {"type": "string"},
                "duration_days": {"type": "integer"},
            },
            "required": ["symptoms", "duration_days"],
        }

        result = await extract_dynamic_json(
            "Patient has fever for three days.",
            schema,
            client=_FakeClient(['```json\n{"symptoms":"fever","duration_days":"3"}\n```']),
        )

        self.assertTrue(result.used_llm)
        self.assertFalse(result.fallback_used)
        self.assertEqual(result.result["symptoms"], "fever")
        self.assertEqual(result.result["duration_days"], 3)

    async def test_extract_dynamic_json_falls_back_to_line_parser(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "symptoms": {"type": "string"},
                "risk_level": {"type": "string", "enum": ["routine", "watch", "urgent"]},
                "red_flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["symptoms", "risk_level"],
        }
        text = "symptoms: chest pain and breathlessness\nrisk_level: urgent\nred_flags: chest pain, breathlessness"

        result = await extract_dynamic_json(
            text,
            schema,
            client=_FakeClient(["[ERROR] LLM unavailable"]),
        )

        self.assertFalse(result.used_llm)
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.result["risk_level"], "urgent")
        self.assertIn("chest pain", result.result["red_flags"])

    async def test_extract_dynamic_json_defaults_missing_required_fields(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "temperature_c": {"type": "number"},
                "admit": {"type": "boolean"},
            },
            "required": ["temperature_c", "admit"],
        }

        result = await extract_dynamic_json(
            "No measurable temperature mentioned.",
            schema,
            client=_FakeClient(["not json output"]),
        )

        self.assertEqual(result.result["temperature_c"], 0.0)
        self.assertFalse(result.result["admit"])
        self.assertTrue(result.fallback_used)


if __name__ == "__main__":
    unittest.main()
