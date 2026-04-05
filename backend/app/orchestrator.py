from __future__ import annotations

import asyncio

from .asr.router import ASRRouter
from .consultation import (
    build_consultation_turns,
    build_deterministic_response,
    build_follow_up_questions,
    build_structured_report_schema,
    build_structured_report,
    infer_speaker_role,
    merge_structured_report_overrides,
    normalize_consultation_mode,
    shape_assistant_response,
)
from .dynamic_extract import extract_dynamic_json
from .healthcare_resources import select_healthcare_resources
from .language import detect_scripts, get_dominant_language, split_sentences
from .logger import get_logger
from .memory import store
from .ollama_client import OllamaClient
from .prompt import build_healthcare_messages
from .response_policy import choose_response_language
from .transcript_cleaner import clean_transcript

log = get_logger("orchestrator")

ollama = OllamaClient()
asr = ASRRouter()


class Orchestrator:
    """Healthcare consultation orchestrator for typed and spoken turns."""

    async def _extract_dynamic_report(
        self,
        consultation_turns: list[dict[str, object]],
        transcript_records: list[dict[str, object]] | None = None,
        timeout_seconds: float = 6.0,
    ) -> dict[str, object]:
        transcript_records = transcript_records or []
        source_lines: list[str] = []

        for turn in consultation_turns:
            role = clean_transcript(str(turn.get("speaker_role", ""))) or "speaker"
            text = clean_transcript(str(turn.get("text", "")))
            if text:
                source_lines.append(f"{role}: {text}")

        for record in transcript_records:
            source = clean_transcript(str(record.get("source", ""))) or "transcript"
            text = clean_transcript(str(record.get("text", "")))
            if text:
                source_lines.append(f"{source}: {text}")

        source_text = "\n".join(source_lines).strip()
        if not source_text:
            return {}

        try:
            dynamic_result = await asyncio.wait_for(
                extract_dynamic_json(
                    source_text,
                    build_structured_report_schema(),
                    context=(
                        "Extract healthcare consultation fields from mixed patient, doctor, assistant, "
                        "and report text. Keep unknown fields empty."
                    ),
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            log.warning("Dynamic report extraction timed out; using heuristic report only.")
            return {}
        except Exception as exc:
            log.warning(f"Dynamic report extraction failed; using heuristic report only: {exc}")
            return {}

        if dynamic_result.issues:
            log.info(
                "Dynamic report extraction issues: "
                f"{'; '.join(dynamic_result.issues[:3])}"
            )
        return dict(dynamic_result.result)

    async def process(
        self,
        session_id: str,
        text: str,
        languages: set | None = None,
        speaker_role_hint: str | None = None,
        consultation_mode: str = "consultation",
    ):
        text = clean_transcript(text)
        if not text:
            yield {"type": "error", "error": "Empty input received."}
            return

        consultation_mode = normalize_consultation_mode(consultation_mode)
        history_before = store.get(session_id)
        speaker_role = infer_speaker_role(text, history_before, speaker_role_hint=speaker_role_hint)

        if languages is None:
            languages = detect_scripts(text)

        dominant_lang = get_dominant_language(text, languages.copy())
        code_mixed = len(languages - {"unknown"}) > 1
        store.track_languages(session_id, languages)
        fallback_language = choose_response_language(text, languages)

        yield {
            "type": "language_info",
            "languages": list(languages),
            "dominant_language": dominant_lang,
            "is_code_mixed": code_mixed,
            "speaker_role": speaker_role,
            "consultation_mode": consultation_mode,
        }

        store.add(session_id, speaker_role, text)
        session_snapshot = store.get_session_snapshot(session_id)
        consultation_turns = build_consultation_turns(session_snapshot)
        structured_report = build_structured_report(
            consultation_turns,
            transcript_records=(session_snapshot or {}).get("transcripts", []),
        )
        dynamic_structured_report = await self._extract_dynamic_report(
            consultation_turns,
            transcript_records=list((session_snapshot or {}).get("transcripts", [])),
        )
        structured_report = merge_structured_report_overrides(structured_report, dynamic_structured_report)
        knowledge_hits = select_healthcare_resources([turn.get("text", "") for turn in consultation_turns])
        suggested_questions = build_follow_up_questions(structured_report, speaker_role, consultation_mode)
        messages = build_healthcare_messages(
            history_before,
            text,
            languages=languages,
            speaker_role=speaker_role,
            consultation_mode=consultation_mode,
            structured_report=structured_report,
            knowledge_hits=knowledge_hits,
            suggested_questions=suggested_questions,
        )

        response_text = ""
        used_llm = False

        try:
            async for chunk in ollama.stream(messages):
                if chunk.startswith("[ERROR]"):
                    log.warning(f"LLM unavailable, falling back to deterministic healthcare response: {chunk}")
                    response_text = build_deterministic_response(
                        speaker_role=speaker_role,
                        consultation_mode=consultation_mode,
                        report=structured_report,
                        knowledge_hits=knowledge_hits,
                        response_language=fallback_language,
                    )
                    yield {"type": "delta", "text": response_text}
                    break

                used_llm = True
                response_text += chunk
                yield {"type": "delta", "text": chunk}
        except Exception as exc:
            log.warning(f"LLM streaming failed; using deterministic fallback: {exc}")
            response_text = build_deterministic_response(
                speaker_role=speaker_role,
                consultation_mode=consultation_mode,
                report=structured_report,
                knowledge_hits=knowledge_hits,
                response_language=fallback_language,
            )
            yield {"type": "delta", "text": response_text}

        response_text = clean_transcript(response_text)
        if not response_text:
            response_text = build_deterministic_response(
                speaker_role=speaker_role,
                consultation_mode=consultation_mode,
                report=structured_report,
                knowledge_hits=knowledge_hits,
                response_language=fallback_language,
            )
        else:
            response_text = shape_assistant_response(
                response_text,
                speaker_role=speaker_role,
                consultation_mode=consultation_mode,
                report=structured_report,
                knowledge_hits=knowledge_hits,
                response_language=fallback_language,
            )

        log.info(
            "Healthcare consultation response complete "
            f"({len(response_text)} chars, llm={'yes' if used_llm else 'no'})"
        )

        store.add(session_id, "assistant", response_text)
        final_snapshot = store.get_session_snapshot(session_id)
        final_turns = build_consultation_turns(final_snapshot)
        final_report = build_structured_report(
            final_turns,
            transcript_records=(final_snapshot or {}).get("transcripts", []),
        )
        final_dynamic_report = await self._extract_dynamic_report(
            final_turns,
            transcript_records=list((final_snapshot or {}).get("transcripts", [])),
        )
        final_report = merge_structured_report_overrides(final_report, final_dynamic_report)
        final_knowledge_hits = select_healthcare_resources([turn.get("text", "") for turn in final_turns])
        final_questions = build_follow_up_questions(final_report, speaker_role, consultation_mode)

        sentences = split_sentences(response_text)
        tts_language = choose_response_language(response_text, languages)
        tts_segments = []
        for sentence in sentences:
            sentence_languages = detect_scripts(sentence)
            sentence_languages.discard("unknown")
            if not sentence_languages:
                sentence_languages = set(languages or {"en"})
            sentence_preference = tts_language if sentence_languages == {tts_language} else None
            tts_segments.append(
                {
                    "text": sentence,
                    "languages": sorted(sentence_languages),
                    "language": choose_response_language(
                        sentence,
                        sorted(sentence_languages),
                        preferred_language=sentence_preference,
                    ),
                }
            )

        yield {
            "type": "final",
            "text": response_text,
            "language": tts_language,
            "languages": list(languages),
            "is_code_mixed": code_mixed,
            "speaker_role": speaker_role,
            "consultation_mode": consultation_mode,
            "structured_report": final_report,
            "knowledge_hits": final_knowledge_hits,
            "suggested_questions": final_questions,
            "tts_plan": sentences,
            "tts_segments": tts_segments,
            "tts_language": tts_language,
        }

    async def process_audio(
        self,
        session_id: str,
        audio_path: str,
        consultation_mode: str = "consultation",
        speaker_role_hint: str | None = None,
    ):
        log.info("Starting healthcare audio pipeline...")

        try:
            result = await asr.transcribe_full(audio_path)
            if not result.text.strip():
                yield {
                    "type": "error",
                    "error": "Could not transcribe audio. Please speak louder or more clearly.",
                }
                return

            history_before = store.get(session_id)
            speaker_role = infer_speaker_role(
                result.text,
                history_before,
                speaker_role_hint=speaker_role_hint,
            )

            yield {
                "type": "transcription",
                "text": result.text,
                "language": result.dominant_language,
                "languages": list(result.languages),
                "is_code_mixed": result.is_code_mixed,
                "segments": result.segments,
                "speaker_role": speaker_role,
                "consultation_mode": normalize_consultation_mode(consultation_mode),
            }

            async for event in self.process(
                session_id,
                result.text,
                result.languages,
                speaker_role_hint=speaker_role,
                consultation_mode=consultation_mode,
            ):
                yield event

        except Exception as exc:
            error_msg = f"Audio processing failed: {exc}"
            log.error(error_msg)
            yield {"type": "error", "error": error_msg}
