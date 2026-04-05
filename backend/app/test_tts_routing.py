from __future__ import annotations

import io
import unittest
import wave
from unittest.mock import patch

from app.language import segment_text_by_language
from app.tts_router import TTSSegmentInput, TTSResult, TTSRouter, _voice_path_for_language


def _build_silent_wav(sample_rate: int = 22050) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * 128)
    return buffer.getvalue()


class LanguageSegmentationTests(unittest.TestCase):
    def test_segment_text_by_language_splits_mixed_script_text(self) -> None:
        self.assertEqual(
            segment_text_by_language("मुझे fever है।", languages=["hi", "en"]),
            [("मुझे", "hi"), ("fever", "en"), ("है।", "hi")],
        )

    def test_segment_text_by_language_splits_transliterated_hinglish(self) -> None:
        self.assertEqual(
            segment_text_by_language("mujhe fever hai", languages=["hi", "en"]),
            [("mujhe", "hi"), ("fever", "en"), ("hai", "hi")],
        )

    def test_voice_lookup_does_not_fallback_to_english_for_indic_piper(self) -> None:
        with patch(
            "app.tts_router._explicit_voice_settings",
            return_value={"en": "english.onnx", "hi": "", "kn": ""},
        ):
            self.assertEqual(_voice_path_for_language("piper", "en"), "english.onnx")
            self.assertIsNone(_voice_path_for_language("piper", "hi"))


class TTSRouterSplitTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthesize_segments_expands_code_mixed_chunks(self) -> None:
        router = TTSRouter()
        calls: list[tuple[str, list[str] | None, str | None]] = []

        async def fake_synthesize(
            text: str,
            languages: list[str] | None = None,
            preferred_language: str | None = None,
        ) -> TTSResult:
            calls.append((text, languages, preferred_language))
            language = preferred_language or "en"
            return TTSResult(
                text=text,
                language=language,
                provider=f"fake-{language}",
                audio_bytes=_build_silent_wav(),
                sample_rate=22050,
            )

        with patch.object(router, "synthesize", new=fake_synthesize):
            result = await router.synthesize_segments(
                [TTSSegmentInput(text="मुझे fever है।", languages=["hi", "en"])],
                languages=["hi", "en"],
            )

        self.assertEqual(
            calls,
            [
                ("मुझे", ["hi"], "hi"),
                ("fever", ["en"], "en"),
                ("है।", ["hi"], "hi"),
            ],
        )
        self.assertEqual([segment.language for segment in result.segments], ["hi", "en", "hi"])


if __name__ == "__main__":
    unittest.main()
