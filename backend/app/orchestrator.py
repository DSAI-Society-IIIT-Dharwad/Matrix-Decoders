from .asr.router import ASRRouter
from .language import detect_scripts, get_dominant_language, split_sentences
from .logger import get_logger
from .memory import store
from .ollama_client import OllamaClient
from .prompt import build_messages
from .response_policy import choose_response_language
from .transcript_cleaner import clean_transcript

log = get_logger("orchestrator")

ollama = OllamaClient()
asr = ASRRouter()


class Orchestrator:
    """Orchestrates the full pipeline: ASR -> language detection -> LLM -> response."""

    async def process(self, session_id: str, text: str, languages: set = None):
        """Process text input through the pipeline."""
        text = clean_transcript(text)
        if not text:
            yield {"type": "error", "error": "Empty input received."}
            return

        log.info(f"Processing text: '{text[:80]}...'")

        if languages is None:
            languages = detect_scripts(text)

        dominant_lang = get_dominant_language(text, languages.copy())
        code_mixed = len(languages - {"unknown"}) > 1

        store.track_languages(session_id, languages)

        yield {
            "type": "language_info",
            "languages": list(languages),
            "dominant_language": dominant_lang,
            "is_code_mixed": code_mixed,
        }

        history = store.get(session_id)
        messages = build_messages(history, text, languages)

        response_text = ""
        log.info("Sending to LLM...")

        try:
            async for chunk in ollama.stream(messages):
                if chunk.startswith("[ERROR]"):
                    log.error(f"LLM error: {chunk}")
                    yield {"type": "error", "error": chunk}
                    return

                response_text += chunk
                yield {"type": "delta", "text": chunk}

        except Exception as exc:
            error_msg = f"LLM streaming failed: {exc}"
            log.error(error_msg)
            yield {"type": "error", "error": error_msg}
            return

        response_text = clean_transcript(response_text)
        log.info(f"LLM response complete ({len(response_text)} chars)")

        store.add(session_id, "user", text)
        store.add(session_id, "assistant", response_text)

        sentences = split_sentences(response_text)
        tts_language = choose_response_language(response_text, languages)
        tts_segments = []
        for sentence in sentences:
            sentence_languages = detect_scripts(sentence)
            sentence_languages.discard("unknown")
            if not sentence_languages:
                sentence_languages = set(languages or {"en"})
            tts_segments.append(
                {
                    "text": sentence,
                    "languages": sorted(sentence_languages),
                    "language": choose_response_language(
                        sentence,
                        sorted(sentence_languages),
                        preferred_language=tts_language,
                    ),
                }
            )

        yield {
            "type": "final",
            "text": response_text,
            "language": dominant_lang,
            "languages": list(languages),
            "is_code_mixed": code_mixed,
            "tts_plan": sentences,
            "tts_segments": tts_segments,
            "tts_language": tts_language,
        }

    async def process_audio(self, session_id: str, audio_path: str):
        """Process audio through the ASR -> LLM pipeline."""
        log.info("Starting audio pipeline...")

        try:
            result = await asr.transcribe_full(audio_path)

            log.info(
                f"ASR result: '{result.text[:80]}' | "
                f"Languages: {result.languages} | "
                f"Code-mixed: {result.is_code_mixed}"
            )

            if not result.text.strip():
                yield {
                    "type": "error",
                    "error": "Could not transcribe audio. Please speak louder or more clearly.",
                }
                return

            yield {
                "type": "transcription",
                "text": result.text,
                "language": result.dominant_language,
                "languages": list(result.languages),
                "is_code_mixed": result.is_code_mixed,
                "segments": result.segments,
            }

            async for event in self.process(session_id, result.text, result.languages):
                yield event

        except Exception as exc:
            error_msg = f"Audio processing failed: {exc}"
            log.error(error_msg)
            yield {"type": "error", "error": error_msg}
