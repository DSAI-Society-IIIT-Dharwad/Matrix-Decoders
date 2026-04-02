from .memory import store
from .language import detect_scripts, is_code_mixed, get_dominant_language, split_sentences
from .prompt import build_messages
from .ollama_client import OllamaClient
from .asr.router import ASRRouter
from .logger import get_logger
from .response_policy import choose_response_language
from .transcript_cleaner import clean_transcript

log = get_logger("orchestrator")

ollama = OllamaClient()
asr = ASRRouter()


class Orchestrator:
    """Orchestrates the full pipeline: ASR → Language Detection → LLM → Response."""

    async def process(self, session_id: str, text: str, languages: set = None):
        """Process text input through the pipeline.

        Yields streaming events:
        - {"type": "language_info", ...}: Detected language information
        - {"type": "delta", "text": ...}: Streaming LLM chunk
        - {"type": "final", ...}: Complete response with TTS plan
        - {"type": "error", ...}: Error information

        Args:
            session_id: Conversation session identifier.
            text: User input text.
            languages: Pre-detected languages (from ASR). Auto-detected if None.
        """
        text = clean_transcript(text)
        if not text:
            yield {"type": "error", "error": "Empty input received."}
            return

        log.info(f"Processing text: '{text[:80]}...'")

        # Detect languages if not provided
        if languages is None:
            languages = detect_scripts(text)

        dominant_lang = get_dominant_language(text, languages.copy())
        code_mixed = len(languages - {"unknown"}) > 1

        # Track languages in session
        store.track_languages(session_id, languages)

        # Emit language info event
        yield {
            "type": "language_info",
            "languages": list(languages),
            "dominant_language": dominant_lang,
            "is_code_mixed": code_mixed,
        }

        # Get conversation history
        history = store.get(session_id)

        # Build prompt with language context
        messages = build_messages(history, text, languages)

        response_text = ""
        log.info("Sending to LLM...")

        # Stream LLM response
        try:
            async for chunk in ollama.stream(messages):
                # Check for error response from Ollama client
                if chunk.startswith("[ERROR]"):
                    log.error(f"LLM error: {chunk}")
                    yield {"type": "error", "error": chunk}
                    return

                response_text += chunk
                yield {"type": "delta", "text": chunk}

        except Exception as e:
            error_msg = f"LLM streaming failed: {e}"
            log.error(error_msg)
            yield {"type": "error", "error": error_msg}
            return

        log.info(f"LLM response complete ({len(response_text)} chars)")

        # Save conversation to memory
        store.add(session_id, "user", text)
        store.add(session_id, "assistant", response_text)

        # Prepare TTS chunks
        response_text = clean_transcript(response_text)
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
        """Process audio through ASR → LLM pipeline.

        Runs the full code-mixed ASR pipeline, then passes the
        transcription to the text processing pipeline.
        """
        log.info("Starting audio pipeline...")

        try:
            # Run full code-mixed ASR
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

            # Emit transcription event
            yield {
                "type": "transcription",
                "text": result.text,
                "language": result.dominant_language,
                "languages": list(result.languages),
                "is_code_mixed": result.is_code_mixed,
                "segments": result.segments,
            }

            # Pass to main text pipeline with pre-detected languages
            async for event in self.process(session_id, result.text, result.languages):
                yield event

        except Exception as e:
            error_msg = f"Audio processing failed: {e}"
            log.error(error_msg)
            yield {"type": "error", "error": error_msg}
