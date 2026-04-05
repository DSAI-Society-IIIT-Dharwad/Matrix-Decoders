import asyncio
import re
from dataclasses import dataclass, field
from typing import Set

from .indic_asr import transcribe_indic
from .segmenter import create_segment_dir, segment_audio
from .whisper_asr import transcribe_english
from ..language import detect_scripts, get_dominant_language, is_code_mixed
from ..logger import get_logger
from ..transcript_cleaner import build_segment_metadata, clean_transcript

log = get_logger("asr.router")


@dataclass
class CodeMixedResult:
    """Result from code-mixed ASR pipeline."""

    text: str
    languages: Set[str] = field(default_factory=lambda: {"en"})
    is_code_mixed: bool = False
    dominant_language: str = "en"
    segments: list = field(default_factory=list)


def _score_text(text: str) -> int:
    """Score transcription quality based on length and cleanliness."""
    text = clean_transcript(text)
    if not text:
        return 0

    length_score = len(text)
    weird_chars = len(re.findall(r"[^\w\s.,!?'\"-]", text))
    penalty = weird_chars * 2

    return max(0, length_score - penalty)


def _merge_transcriptions(whisper_text: str, hi_text: str, kn_text: str) -> tuple[str, Set[str]]:
    """Pick the best transcription candidate for a single segment."""
    scores = {
        "whisper": _score_text(whisper_text),
        "hi": _score_text(hi_text),
        "kn": _score_text(kn_text),
    }

    log.info(
        f"Scores - Whisper: {scores['whisper']}, Hindi: {scores['hi']}, Kannada: {scores['kn']}"
    )

    whisper_text = clean_transcript(whisper_text)
    hi_text = clean_transcript(hi_text)
    kn_text = clean_transcript(kn_text)

    whisper_langs = detect_scripts(whisper_text) if whisper_text else set()
    hi_langs = detect_scripts(hi_text) if hi_text else set()
    kn_langs = detect_scripts(kn_text) if kn_text else set()

    if whisper_text and is_code_mixed(whisper_text):
        log.info("Code-mixed speech detected in Whisper output")
        return whisper_text, whisper_langs

    script_candidates = []
    if hi_text and (hi_langs - {"en"}):
        script_candidates.append((hi_text, hi_langs, scores["hi"]))
    if kn_text and (kn_langs - {"en"}):
        script_candidates.append((kn_text, kn_langs, scores["kn"]))

    if script_candidates:
        best_text, best_langs, _ = max(script_candidates, key=lambda item: item[2])
        return best_text, best_langs

    if scores["whisper"] > max(scores["hi"], scores["kn"]) * 1.5:
        return whisper_text, whisper_langs

    if scores["hi"] >= scores["kn"] and scores["hi"] > scores["whisper"] * 0.7:
        return hi_text, hi_langs

    if scores["kn"] > scores["hi"] and scores["kn"] > scores["whisper"] * 0.7:
        return kn_text, kn_langs

    best = max(
        [
            (whisper_text, whisper_langs),
            (hi_text, detect_scripts(hi_text)),
            (kn_text, detect_scripts(kn_text)),
        ],
        key=lambda x: len(x[0].strip()) if x[0] else 0,
    )
    return clean_transcript(best[0]), best[1]


class ASRRouter:
    """Routes audio to the best ASR engine(s) and handles code-mixed speech."""

    async def _transcribe_segment(self, audio_path: str) -> tuple[str, Set[str], str]:
        loop = asyncio.get_event_loop()

        whisper_text = await loop.run_in_executor(None, transcribe_english, audio_path)
        whisper_text = clean_transcript(whisper_text)

        hi_text = await loop.run_in_executor(None, transcribe_indic, audio_path, "hi")
        kn_text = await loop.run_in_executor(None, transcribe_indic, audio_path, "kn")
        hi_text = clean_transcript(hi_text)
        kn_text = clean_transcript(kn_text)

        best_text, languages = _merge_transcriptions(whisper_text, hi_text, kn_text)
        languages.discard("unknown")
        if not languages:
            languages = {"en"}

        if best_text == hi_text and hi_text:
            engine = "indic_hi"
        elif best_text == kn_text and kn_text:
            engine = "indic_kn"
        else:
            engine = "whisper"

        return clean_transcript(best_text), languages, engine

    async def transcribe(self, audio_path: str) -> tuple:
        """Transcribe audio, handling code-mixed Hindi-English-Kannada."""
        result = await self.transcribe_full(audio_path)
        return result.text, result.dominant_language

    async def transcribe_full(self, audio_path: str) -> CodeMixedResult:
        """Segment audio first, then run ASR routing per segment."""
        with create_segment_dir() as segment_dir:
            audio_segments = segment_audio(audio_path, segment_dir)

            if not audio_segments:
                log.warning(f"No audio segments detected for {audio_path}")
                return CodeMixedResult(
                    text="",
                    languages={"en"},
                    is_code_mixed=False,
                    dominant_language="en",
                    segments=[],
                )

            log.info(f"Segmented audio into {len(audio_segments)} chunk(s)")

            merged_text_parts: list[str] = []
            all_languages: Set[str] = set()
            transcript_segments: list[dict] = []

            for audio_segment in audio_segments:
                text, languages, engine = await self._transcribe_segment(audio_segment.path)
                text = clean_transcript(text)
                if not text:
                    continue

                merged_text_parts.append(text)
                all_languages.update(languages)

                segment_languages = sorted(lang for lang in languages if lang != "unknown")
                if not segment_languages:
                    segment_languages = ["en"]

                transcript_segments.append(
                    {
                        "index": audio_segment.index,
                        "text": text,
                        "language": segment_languages[0],
                        "languages": segment_languages,
                        "dominant_language": get_dominant_language(text, set(segment_languages)),
                        "engine": engine,
                        "is_code_mixed": is_code_mixed(text),
                        "is_final": True,
                        "start_ms": audio_segment.start_ms,
                        "end_ms": audio_segment.end_ms,
                    }
                )

        merged_text = clean_transcript(" ".join(merged_text_parts))
        if not merged_text and transcript_segments:
            merged_text = clean_transcript(" ".join(segment["text"] for segment in transcript_segments))

        all_languages.discard("unknown")
        if not all_languages and merged_text:
            all_languages = detect_scripts(merged_text)
            all_languages.discard("unknown")
        if not all_languages:
            all_languages = {"en"}

        dominant = get_dominant_language(merged_text, all_languages.copy()) if merged_text else "en"
        mixed = len(all_languages) > 1 or any(segment["is_code_mixed"] for segment in transcript_segments)

        if not transcript_segments and merged_text:
            transcript_segments = build_segment_metadata(merged_text)

        result = CodeMixedResult(
            text=merged_text,
            languages=all_languages,
            is_code_mixed=mixed,
            dominant_language=dominant,
            segments=transcript_segments,
        )

        log.info(
            f"Final: '{result.text[:80]}' | "
            f"Languages: {result.languages} | "
            f"Code-mixed: {result.is_code_mixed}"
        )

        return result
