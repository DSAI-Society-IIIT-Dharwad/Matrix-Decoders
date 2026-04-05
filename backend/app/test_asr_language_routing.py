from __future__ import annotations

import unittest

from app.asr.router import _merge_transcriptions
from app.language import get_dominant_language, normalize_supported_language


class LanguageRoutingTests(unittest.TestCase):
    def test_normalize_supported_language_clamps_unsupported_codes(self) -> None:
        self.assertEqual(normalize_supported_language("ru"), "en")
        self.assertEqual(normalize_supported_language("hi"), "hi")

    def test_kannada_script_prefers_indic_candidate_over_english_whisper(self) -> None:
        text, languages = _merge_transcriptions(
            "Hello how are you",
            "ನನಗೆ ಸಹಾಯ ಬೇಕು",
            "मुझे मदद चाहिए",
        )

        self.assertEqual(text, "ನನಗೆ ಸಹಾಯ ಬೇಕು")
        self.assertIn("kn", languages)
        self.assertNotIn("ru", languages)
        self.assertEqual(get_dominant_language(text, languages.copy()), "kn")

    def test_code_mixed_whisper_is_preserved(self) -> None:
        text, languages = _merge_transcriptions(
            "Mujhe help chahiye yaar",
            "मुझे मदद चाहिए",
            "",
        )

        self.assertEqual(text, "Mujhe help chahiye yaar")
        self.assertIn("hi", languages)
        self.assertIn("en", languages)


if __name__ == "__main__":
    unittest.main()
