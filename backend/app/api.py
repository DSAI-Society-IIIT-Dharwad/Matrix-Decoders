from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import wave
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile, WebSocket
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect, WebSocketState

from .asr.router import ASRRouter
from .audio_utils import AudioFormatConfig, trim_pcm16_silence
from .consultation import (
    build_opening_assistant_prompt,
    derive_consultation_snapshot,
    infer_speaker_role,
    normalize_consultation_mode,
)
from .document_parser import SUPPORTED_REPORT_SUFFIXES, extract_document_text
from .dynamic_extract import extract_dynamic_json
from .healthcare_resources import select_healthcare_resources
from .logger import get_logger
from .memory import store
from .ollama_client import OllamaClient
from .orchestrator import Orchestrator
from .runtime_validation import collect_runtime_validation_report
from .schemas import (
    ChatRequest,
    ChatResponse,
    DynamicExtractRequest,
    DynamicExtractResponse,
    HealthResponse,
    ReportExtractResponse,
    SessionDetailResponse,
    SessionListResponse,
    StartConsultationRequest,
    TTSRequest,
    TTSResponse,
    TranscribeResponse,
)
from .training.archive import archive_training_audio
from .transcript_cleaner import clean_transcript
from .tts_router import TTSSegmentInput, tts_router
from .websocket_stream import (
    build_stream_complete_event,
    build_stream_started_event,
    enrich_stream_event,
    new_stream_state,
    utc_now_iso,
)

log = get_logger("api")

router = APIRouter()
orch = Orchestrator()
asr_router = ASRRouter()
ollama_client = OllamaClient()

_start_time = time.time()
_ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _build_tts_segment_inputs(
    raw_segments,
    fallback_text: str,
    fallback_languages=None,
    fallback_language=None,
) -> list[TTSSegmentInput]:
    inputs: list[TTSSegmentInput] = []

    for segment in raw_segments or []:
        if isinstance(segment, str) and segment.strip():
            inputs.append(
                TTSSegmentInput(
                    text=segment.strip(),
                    language=fallback_language,
                    languages=fallback_languages,
                )
            )
        elif isinstance(segment, dict):
            text = clean_transcript(str(segment.get("text", "")))
            if text:
                languages = segment.get("languages")
                if not isinstance(languages, list):
                    languages = fallback_languages
                inputs.append(
                    TTSSegmentInput(
                        text=text,
                        language=segment.get("language") or segment.get("dominant_language") or fallback_language,
                        languages=languages,
                    )
                )

    if inputs:
        return inputs

    return [
        TTSSegmentInput(
            text=fallback_text,
            language=fallback_language,
            languages=fallback_languages,
        )
    ]


def _augment_session_snapshot(snapshot: dict | None) -> dict | None:
    if not snapshot:
        return snapshot
    consultation = derive_consultation_snapshot(snapshot)
    snapshot.update(consultation)
    return snapshot


@router.get("/api/health", response_model=HealthResponse)
async def health_check():
    ollama_ok = await ollama_client.is_available()
    validation_report = collect_runtime_validation_report(run_command_probes=False)
    available_tts_providers = tts_router.available_providers()
    available_real_tts_providers = tts_router.available_real_speech_providers()
    tts_ready = bool(available_tts_providers)
    tts_real_ready = bool(available_real_tts_providers)
    health_status = "ok"
    if not ollama_ok or (bool(validation_report.settings_summary["enable_tts"]) and not tts_ready):
        health_status = "degraded"

    return HealthResponse(
        status=health_status,
        model=ollama_client.model,
        uptime_seconds=round(time.time() - _start_time, 1),
        sessions_active=store.session_count(),
        tts_enabled=bool(validation_report.settings_summary["enable_tts"]),
        tts_ready=tts_ready,
        tts_providers=available_tts_providers,
        tts_real_speech_ready=tts_real_ready,
        tts_real_providers=available_real_tts_providers,
        errors=[issue.message for issue in validation_report.issues if issue.level == "error"],
        warnings=[issue.message for issue in validation_report.issues if issue.level != "error"],
    )


@router.post("/api/consultation/start", response_model=ChatResponse)
async def start_consultation(request: StartConsultationRequest):
    consultation_mode = normalize_consultation_mode(request.consultation_mode)
    response_language = request.response_language if request.response_language in {"en", "hi", "kn"} else "en"
    opening_prompt = build_opening_assistant_prompt(consultation_mode, response_language=response_language)
    store.add(request.session_id, "assistant", opening_prompt)
    store.set_selected_language(request.session_id, response_language)
    snapshot = _augment_session_snapshot(store.get_session_snapshot(request.session_id)) or {}
    return ChatResponse(
        text=opening_prompt,
        language=response_language,
        languages=list(snapshot.get("languages", [response_language])),
        is_code_mixed=False,
        session_id=request.session_id,
        speaker_role="assistant",
        consultation_mode=consultation_mode,
        structured_report=snapshot.get("structured_report", {}),
        knowledge_hits=snapshot.get("knowledge_hits", []),
        suggested_questions=snapshot.get("suggested_questions", []),
    )


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    started_at = time.perf_counter()
    cleaned_text = clean_transcript(request.text)
    if not cleaned_text:
        message = "Text input cannot be empty."
        store.record_error(request.session_id, "api.chat", message)
        store.record_latency(request.session_id, "api.chat", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=400, content={"error": message})

    response_text = ""
    final_event = None
    pipeline_error = None

    async for event in orch.process(
        request.session_id,
        cleaned_text,
        speaker_role_hint=request.speaker_role,
        consultation_mode=request.consultation_mode,
        preferred_response_language=request.response_language,
    ):
        if event["type"] == "delta":
            response_text += event["text"]
        elif event["type"] == "final":
            final_event = event
        elif event["type"] == "error":
            pipeline_error = event["error"]

    if pipeline_error:
        store.record_error(request.session_id, "api.chat", pipeline_error)
        store.record_latency(request.session_id, "api.chat", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=500, content={"error": pipeline_error})

    final_event = final_event or {}
    if final_event.get("languages"):
        store.track_languages(request.session_id, set(final_event["languages"]))
    if final_event.get("language"):
        store.set_selected_language(request.session_id, final_event["language"])
    store.record_latency(
        request.session_id,
        "api.chat",
        _elapsed_ms(started_at),
        status="ok",
        details={
            "response_language": final_event.get("language", ""),
            "speaker_role": final_event.get("speaker_role", ""),
            "consultation_mode": final_event.get("consultation_mode", ""),
        },
    )

    return ChatResponse(
        text=final_event.get("text", response_text),
        language=final_event.get("language", "en"),
        languages=final_event.get("languages", []),
        is_code_mixed=bool(final_event.get("is_code_mixed", False)),
        session_id=request.session_id,
        speaker_role=final_event.get("speaker_role", "patient"),
        consultation_mode=final_event.get("consultation_mode", normalize_consultation_mode(request.consultation_mode)),
        structured_report=final_event.get("structured_report", {}),
        knowledge_hits=final_event.get("knowledge_hits", []),
        suggested_questions=final_event.get("suggested_questions", []),
    )


@router.post("/api/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(file: UploadFile = File(...), session_id: str | None = Form(default=None)):
    started_at = time.perf_counter()
    filename = file.filename or "upload.wav"
    suffix = Path(filename).suffix.lower()
    if suffix and suffix not in _ALLOWED_AUDIO_EXTENSIONS:
        message = f"Unsupported audio format '{suffix}'. Expected one of {sorted(_ALLOWED_AUDIO_EXTENSIONS)}."
        return JSONResponse(status_code=400, content={"error": message})

    temp_dir = Path("temp_audio")
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"upload_{int(time.time() * 1000)}{suffix or '.wav'}"

    try:
        contents = await file.read()
        if not contents:
            return JSONResponse(status_code=400, content={"error": "Uploaded audio file is empty."})

        temp_path.write_bytes(contents)
        result = await asr_router.transcribe_full(str(temp_path))
        history = store.get(session_id) if session_id else []
        speaker_role = infer_speaker_role(result.text, history)

        if session_id:
            store.record_transcript(
                session_id=session_id,
                source="api.transcribe",
                text=result.text,
                dominant_language=result.dominant_language,
                languages=result.languages,
                is_code_mixed=result.is_code_mixed,
                segments=result.segments,
                details={
                    "filename": filename,
                    "content_type": file.content_type or "",
                    "speaker_role": speaker_role,
                },
            )
            archive_training_audio(
                audio_path=str(temp_path),
                text=result.text,
                dominant_language=result.dominant_language,
                languages=result.languages,
                is_code_mixed=result.is_code_mixed,
                source="api.transcribe",
                session_id=session_id,
                details={"filename": filename, "speaker_role": speaker_role},
            )

        snapshot = _augment_session_snapshot(store.get_session_snapshot(session_id)) if session_id else None
        store.record_latency(
            session_id,
            "api.transcribe",
            _elapsed_ms(started_at),
            status="ok",
            details={"filename": filename, "speaker_role": speaker_role},
        )
        return TranscribeResponse(
            text=result.text,
            language=result.dominant_language,
            languages=list(result.languages),
            is_code_mixed=result.is_code_mixed,
            segments=result.segments,
            speaker_role=speaker_role,
            structured_report=(snapshot or {}).get("structured_report", {}),
            knowledge_hits=(snapshot or {}).get("knowledge_hits", select_healthcare_resources([result.text])),
            suggested_questions=(snapshot or {}).get("suggested_questions", []),
        )
    except Exception as exc:
        log.error(f"Transcription failed: {exc}")
        store.record_error(session_id, "api.transcribe", str(exc), details={"filename": filename})
        store.record_latency(session_id, "api.transcribe", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=500, content={"error": str(exc)})
    finally:
        if temp_path.exists():
            temp_path.unlink()


@router.post("/api/extract/dynamic", response_model=DynamicExtractResponse)
async def dynamic_extract(request: DynamicExtractRequest):
    started_at = time.perf_counter()
    cleaned_text = clean_transcript(request.text)
    if not cleaned_text:
        return JSONResponse(status_code=400, content={"error": "Dynamic extraction input cannot be empty."})

    try:
        result = await extract_dynamic_json(
            cleaned_text,
            request.schema,
            context=clean_transcript(request.context),
        )
    except Exception as exc:
        session_id = request.session_id if request.session_id else None
        store.record_error(session_id, "api.extract.dynamic", str(exc))
        store.record_latency(session_id, "api.extract.dynamic", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=500, content={"error": str(exc)})

    session_id = request.session_id if request.session_id else None
    store.record_latency(
        session_id,
        "api.extract.dynamic",
        _elapsed_ms(started_at),
        status="ok",
        details={
            "used_llm": result.used_llm,
            "fallback_used": result.fallback_used,
            "issues": len(result.issues),
        },
    )
    return DynamicExtractResponse(
        result=result.result,
        normalized_schema=result.normalized_schema,
        issues=result.issues,
        used_llm=result.used_llm,
        fallback_used=result.fallback_used,
    )


@router.post("/api/report/extract", response_model=ReportExtractResponse)
async def extract_report(
    file: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    schema_json: str | None = Form(default=None),
):
    filename = file.filename or "report"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_REPORT_SUFFIXES:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unsupported report format '{suffix or 'unknown'}'."},
        )

    tmp_handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp_handle.name)
    tmp_handle.close()

    try:
        tmp_path.write_bytes(await file.read())
        extracted_text = extract_document_text(str(tmp_path))
        knowledge_hits = select_healthcare_resources([extracted_text])
        document_record = {"role": "document", "content": extracted_text}
        structured_report = derive_consultation_snapshot(
            {
                "messages": [document_record],
                "transcripts": [],
            }
        )["structured_report"]
        dynamic_json: dict[str, object] = {}
        dynamic_issues: list[str] = []
        dynamic_used_llm = False
        dynamic_fallback_used = False

        if schema_json and schema_json.strip():
            try:
                parsed_schema = json.loads(schema_json)
            except json.JSONDecodeError:
                return JSONResponse(status_code=400, content={"error": "schema_json must be valid JSON."})

            if not isinstance(parsed_schema, dict):
                return JSONResponse(status_code=400, content={"error": "schema_json must be a JSON object schema."})

            dynamic_result = await extract_dynamic_json(
                extracted_text,
                parsed_schema,
                context="Extract fields from uploaded healthcare report text.",
            )
            dynamic_json = dict(dynamic_result.result)
            dynamic_issues = list(dynamic_result.issues)
            dynamic_used_llm = dynamic_result.used_llm
            dynamic_fallback_used = dynamic_result.fallback_used

        if session_id:
            store.record_transcript(
                session_id=session_id,
                source="report.upload",
                text=extracted_text,
                dominant_language="en",
                languages=["en"],
                is_code_mixed=False,
                segments=[],
                details={
                    "filename": filename,
                    "structured_report": structured_report,
                    "dynamic_json": dynamic_json,
                    "dynamic_issues": dynamic_issues,
                },
            )

        return ReportExtractResponse(
            filename=filename,
            text=extracted_text,
            structured_report=structured_report,
            knowledge_hits=knowledge_hits,
            dynamic_json=dynamic_json,
            dynamic_issues=dynamic_issues,
            dynamic_used_llm=dynamic_used_llm,
            dynamic_fallback_used=dynamic_fallback_used,
        )
    except Exception as exc:
        log.error(f"Report extraction failed: {exc}")
        return JSONResponse(status_code=500, content={"error": str(exc)})
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.post("/api/tts", response_model=TTSResponse)
async def synthesize_speech(request: TTSRequest):
    started_at = time.perf_counter()
    cleaned_text = clean_transcript(request.text)
    if not cleaned_text:
        return JSONResponse(status_code=400, content={"error": "TTS input cannot be empty."})

    try:
        segments = _build_tts_segment_inputs(
            None,
            cleaned_text,
            fallback_languages=request.languages,
            fallback_language=request.language,
        )
        result = await tts_router.synthesize_segments(
            segments,
            languages=request.languages,
            preferred_language=request.language,
        )
    except Exception as exc:
        store.record_error(None, "api.tts", str(exc))
        store.record_latency(None, "api.tts", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=500, content={"error": str(exc)})

    store.record_latency(
        None,
        "api.tts",
        _elapsed_ms(started_at),
        status="ok",
        details={
            "language": result.language,
            "provider": result.provider,
            "segment_count": len(result.segments),
        },
    )
    return TTSResponse(
        text=result.text,
        language=result.language,
        provider=result.provider,
        mime_type=result.mime_type,
        sample_rate=result.sample_rate,
        audio_b64=result.audio_b64,
    )


@router.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    store.clear(session_id)
    return {"status": "cleared", "session_id": session_id}


@router.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions():
    items = store.list_session_summaries()
    return {"sessions": [item["session_id"] for item in items], "count": len(items), "items": items}


@router.get("/api/session/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str):
    snapshot = _augment_session_snapshot(store.get_session_snapshot(session_id))
    if not snapshot:
        return JSONResponse(status_code=404, content={"error": "Session not found."})
    return snapshot


@router.websocket("/ws/{session_id}")
async def text_ws(ws: WebSocket, session_id: str):
    await ws.accept()
    log.info(f"Text consultation WebSocket connected: session={session_id}")

    try:
        while True:
            raw = await ws.receive_text()
            started_at = time.perf_counter()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json(
                    {
                        "type": "error",
                        "error": "Invalid JSON",
                        "session_id": session_id,
                        "channel": "text",
                        "emitted_at": utc_now_iso(),
                    }
                )
                continue

            if msg.get("type") == "ping":
                await ws.send_json(
                    {
                        "type": "pong",
                        "session_id": session_id,
                        "channel": "text",
                        "emitted_at": utc_now_iso(),
                    }
                )
                continue

            if msg.get("type") != "input":
                await ws.send_json(
                    {
                        "type": "error",
                        "error": "Expected {type: 'input', text: '...'}",
                        "session_id": session_id,
                        "channel": "text",
                        "emitted_at": utc_now_iso(),
                    }
                )
                continue

            cleaned_text = clean_transcript(msg.get("text", ""))
            if not cleaned_text:
                await ws.send_json(
                    {
                        "type": "error",
                        "error": "Text input cannot be empty.",
                        "session_id": session_id,
                        "channel": "text",
                        "emitted_at": utc_now_iso(),
                    }
                )
                continue

            stream_state = new_stream_state("text", session_id)
            await ws.send_json(
                build_stream_started_event(
                    stream_state,
                    {
                        "consultation_mode": normalize_consultation_mode(msg.get("consultation_mode")),
                        "speaker_role_hint": msg.get("speaker_role") or "",
                        "response_language": msg.get("response_language") or "",
                    },
                )
            )

            final_event = None
            pipeline_error = None
            async for event in orch.process(
                session_id,
                cleaned_text,
                speaker_role_hint=msg.get("speaker_role"),
                consultation_mode=msg.get("consultation_mode", "consultation"),
                preferred_response_language=msg.get("response_language"),
            ):
                enriched_event = enrich_stream_event(stream_state, event)
                await ws.send_json(enriched_event)
                if event["type"] == "final":
                    final_event = event
                elif event["type"] == "error":
                    pipeline_error = event.get("error", "Unknown text websocket error")

            latency_ms = _elapsed_ms(started_at)
            if pipeline_error:
                store.record_error(session_id, "ws.text", pipeline_error)
                store.record_latency(session_id, "ws.text", latency_ms, status="error")
                await ws.send_json(
                    build_stream_complete_event(
                        stream_state,
                        "error",
                        latency_ms,
                        {"error": pipeline_error},
                    )
                )
                continue

            if final_event:
                store.record_latency(
                    session_id,
                    "ws.text",
                    latency_ms,
                    status="ok",
                    details={
                        "speaker_role": final_event.get("speaker_role", ""),
                        "consultation_mode": final_event.get("consultation_mode", ""),
                    },
                )
                await ws.send_json(
                    build_stream_complete_event(
                        stream_state,
                        "ok",
                        latency_ms,
                        {
                            "speaker_role": final_event.get("speaker_role", ""),
                            "consultation_mode": final_event.get("consultation_mode", ""),
                        },
                    )
                )
            else:
                await ws.send_json(
                    build_stream_complete_event(stream_state, "incomplete", latency_ms)
                )
    except WebSocketDisconnect:
        log.info(f"Text consultation WebSocket disconnected: session={session_id}")
    except Exception as exc:
        log.error(f"Text consultation WebSocket error [{session_id}]: {exc}")
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "error", "error": str(exc)})
                await ws.close(code=1011, reason=str(exc))
        except Exception:
            pass


@router.websocket("/ws/audio/{session_id}")
async def audio_ws(ws: WebSocket, session_id: str):
    await ws.accept()
    log.info(f"Audio consultation WebSocket connected: session={session_id}")

    audio_buffer = bytearray()
    audio_config = AudioFormatConfig()
    last_audio_time = time.time()
    commit_driven_mode = False
    consultation_mode = "consultation"
    speaker_role_hint = None
    silence_timeout: float | None = None
    preferred_response_language = None
    transcription_only = False

    async def flush_audio_buffer():
        nonlocal audio_buffer

        stream_state = new_stream_state("audio", session_id)

        if not audio_buffer:
            await ws.send_json(
                enrich_stream_event(
                    stream_state,
                    {"type": "audio_skipped", "reason": "empty"},
                )
            )
            await ws.send_json(build_stream_complete_event(stream_state, "skipped", 0))
            return

        raw_bytes = len(audio_buffer)
        await ws.send_json(
            build_stream_started_event(
                stream_state,
                {
                    "raw_audio_bytes": raw_bytes,
                    "sample_rate": audio_config.sample_rate,
                    "channels": audio_config.channels,
                    "consultation_mode": consultation_mode,
                    "commit_driven_mode": commit_driven_mode,
                    "transcription_only": transcription_only,
                },
            )
        )

        pcm_audio = trim_pcm16_silence(bytes(audio_buffer), channels=audio_config.channels)
        audio_buffer.clear()
        if not pcm_audio:
            await ws.send_json(
                enrich_stream_event(
                    stream_state,
                    {"type": "audio_skipped", "reason": "silence"},
                )
            )
            await ws.send_json(build_stream_complete_event(stream_state, "skipped", 0))
            return

        temp_dir = Path("temp_audio")
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"{session_id}_{int(time.time() * 1000)}.wav"
        started_at = time.perf_counter()

        try:
            with wave.open(str(temp_path), "wb") as wf:
                wf.setnchannels(audio_config.channels)
                wf.setsampwidth(audio_config.sample_width)
                wf.setframerate(audio_config.sample_rate)
                wf.writeframes(pcm_audio)

            transcription_event = None
            final_event = None
            pipeline_error = None

            if transcription_only:
                result = await asr_router.transcribe_full(str(temp_path))
                if not result.text.strip():
                    pipeline_error = "Could not transcribe audio. Please speak louder or more clearly."
                else:
                    transcription_event = {
                        "type": "transcription",
                        "text": result.text,
                        "language": result.dominant_language,
                        "detected_input_language": result.detected_input_language,
                        "languages": list(result.languages),
                        "is_code_mixed": result.is_code_mixed,
                        "segments": result.segments,
                        "speaker_role": "",
                        "consultation_mode": consultation_mode,
                    }
                    await ws.send_json(enrich_stream_event(stream_state, transcription_event))
            else:
                async for event in orch.process_audio(
                    session_id,
                    str(temp_path),
                    consultation_mode=consultation_mode,
                    speaker_role_hint=speaker_role_hint,
                    preferred_response_language=preferred_response_language,
                ):
                    if event["type"] == "transcription":
                        transcription_event = event
                    elif event["type"] == "final":
                        final_event = event
                    elif event["type"] == "error":
                        pipeline_error = event.get("error", "Unknown audio pipeline error")
                    await ws.send_json(enrich_stream_event(stream_state, event))

            if transcription_event:
                store.record_transcript(
                    session_id=session_id,
                    source="ws.audio",
                    text=str(transcription_event.get("text", "")),
                    dominant_language=transcription_event.get("language"),
                    languages=transcription_event.get("languages") or [],
                    is_code_mixed=bool(transcription_event.get("is_code_mixed", False)),
                    segments=transcription_event.get("segments") or [],
                    details={
                        "sample_rate": audio_config.sample_rate,
                        "channels": audio_config.channels,
                        "speaker_role": transcription_event.get("speaker_role", ""),
                        "consultation_mode": consultation_mode,
                        "transcription_only": transcription_only,
                    },
                )
                archive_training_audio(
                    audio_path=str(temp_path),
                    text=str(transcription_event.get("text", "")),
                    dominant_language=transcription_event.get("language"),
                    languages=transcription_event.get("languages") or [],
                    is_code_mixed=bool(transcription_event.get("is_code_mixed", False)),
                    source="ws.audio",
                    session_id=session_id,
                    details={
                        "speaker_role": transcription_event.get("speaker_role", ""),
                        "transcription_only": transcription_only,
                    },
                )

            latency_ms = _elapsed_ms(started_at)
            if pipeline_error:
                store.record_error(session_id, "ws.audio", pipeline_error)
                store.record_latency(session_id, "ws.audio", latency_ms, status="error")
                await ws.send_json(
                    build_stream_complete_event(
                        stream_state,
                        "error",
                        latency_ms,
                        {"error": pipeline_error},
                    )
                )
            elif final_event:
                store.record_latency(
                    session_id,
                    "ws.audio",
                    latency_ms,
                    status="ok",
                    details={
                        "speaker_role": final_event.get("speaker_role", ""),
                        "consultation_mode": final_event.get("consultation_mode", ""),
                    },
                )
                await ws.send_json(
                    build_stream_complete_event(
                        stream_state,
                        "ok",
                        latency_ms,
                        {
                            "speaker_role": final_event.get("speaker_role", ""),
                            "consultation_mode": final_event.get("consultation_mode", ""),
                        },
                    )
                )
            else:
                await ws.send_json(build_stream_complete_event(stream_state, "incomplete", latency_ms))
        except Exception as exc:
            log.error(f"Audio processing error: {exc}")
            store.record_error(session_id, "ws.audio", str(exc))
            latency_ms = _elapsed_ms(started_at)
            store.record_latency(session_id, "ws.audio", latency_ms, status="error")
            await ws.send_json(
                enrich_stream_event(stream_state, {"type": "error", "error": str(exc)})
            )
            await ws.send_json(
                build_stream_complete_event(stream_state, "error", latency_ms, {"error": str(exc)})
            )
        finally:
            if temp_path.exists():
                temp_path.unlink()

    try:
        while True:
            try:
                data = await asyncio.wait_for(ws.receive(), timeout=0.1)
            except asyncio.TimeoutError:
                data = None

            if data is None:
                current_time = time.time()
                max_buffer_size = audio_config.max_buffer_bytes()
                timed_out = silence_timeout is not None and current_time - last_audio_time > silence_timeout
                should_flush = timed_out
                if not commit_driven_mode:
                    should_flush = should_flush or len(audio_buffer) >= max_buffer_size
                if audio_buffer and should_flush:
                    await flush_audio_buffer()
                continue

            if "bytes" in data and data["bytes"] is not None:
                chunk = data["bytes"]
                max_chunk_bytes = audio_config.max_chunk_bytes()
                if len(chunk) > max_chunk_bytes:
                    await ws.send_json({"type": "error", "error": f"Audio chunk too large ({len(chunk)} bytes)."})
                    continue
                if len(chunk) % audio_config.frame_size != 0:
                    await ws.send_json({"type": "error", "error": "Invalid PCM frame received."})
                    continue
                audio_buffer.extend(chunk)
                last_audio_time = time.time()
            elif "text" in data and data["text"] is not None:
                raw_text = data["text"].strip()
                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError:
                    payload = None

                if isinstance(payload, dict):
                    message_type = str(payload.get("type", "")).lower()
                    if message_type in {"start", "config"}:
                        audio_config = AudioFormatConfig.from_message(payload)
                        commit_driven_mode = True
                        consultation_mode = normalize_consultation_mode(payload.get("consultation_mode"))
                        speaker_role_hint = payload.get("speaker_role")
                        preferred_response_language = payload.get("response_language")
                        transcription_only = _coerce_bool(payload.get("transcription_only"))
                        raw_turn_timeout = payload.get("turn_timeout_seconds")
                        if raw_turn_timeout in {None, ""}:
                            silence_timeout = None
                        else:
                            try:
                                silence_timeout = max(0.35, min(float(raw_turn_timeout), 3.0))
                            except (TypeError, ValueError):
                                silence_timeout = None
                        await ws.send_json(
                            {
                                "type": "audio_config",
                                "sample_rate": audio_config.sample_rate,
                                "channels": audio_config.channels,
                                "sample_width": audio_config.sample_width,
                                "encoding": audio_config.encoding,
                                "max_chunk_bytes": audio_config.max_chunk_bytes(),
                                "consultation_mode": consultation_mode,
                                "response_language": preferred_response_language or "",
                                "transcription_only": transcription_only,
                                "turn_timeout_seconds": silence_timeout,
                                "session_id": session_id,
                                "channel": "audio",
                                "emitted_at": utc_now_iso(),
                            }
                        )
                        continue
                    if message_type == "commit":
                        await flush_audio_buffer()
                        continue
                    if message_type == "reset":
                        audio_buffer.clear()
                        await ws.send_json(
                            {
                                "type": "audio_reset",
                                "session_id": session_id,
                                "channel": "audio",
                                "emitted_at": utc_now_iso(),
                            }
                        )
                        continue
                    if message_type == "ping":
                        await ws.send_json(
                            {
                                "type": "pong",
                                "session_id": session_id,
                                "channel": "audio",
                                "emitted_at": utc_now_iso(),
                            }
                        )
                        continue

                command = raw_text.lower()
                if command == "commit":
                    await flush_audio_buffer()
                    continue
                if command == "reset":
                    audio_buffer.clear()
                    await ws.send_json(
                        {
                            "type": "audio_reset",
                            "session_id": session_id,
                            "channel": "audio",
                            "emitted_at": utc_now_iso(),
                        }
                    )
                    continue
                if command == "ping":
                    await ws.send_json(
                        {
                            "type": "pong",
                            "session_id": session_id,
                            "channel": "audio",
                            "emitted_at": utc_now_iso(),
                        }
                    )
                    continue
                await ws.send_json({"type": "error", "error": "Unsupported audio control message."})
                continue

    except WebSocketDisconnect:
        log.info(f"Audio consultation WebSocket disconnected: session={session_id}")
    except Exception as exc:
        log.error(f"Audio consultation WebSocket error [{session_id}]: {exc}")
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.close(code=1011, reason=str(exc))
        except Exception:
            pass


@router.websocket("/ws/tts/{session_id}")
async def tts_ws(ws: WebSocket, session_id: str):
    await ws.accept()
    log.info(f"TTS WebSocket connected: session={session_id}")

    try:
        while True:
            raw = await ws.receive_text()
            started_at = time.perf_counter()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json(
                    {
                        "type": "error",
                        "error": "Invalid JSON",
                        "session_id": session_id,
                        "channel": "tts",
                        "emitted_at": utc_now_iso(),
                    }
                )
                continue

            if msg.get("type") == "ping":
                await ws.send_json(
                    {
                        "type": "pong",
                        "session_id": session_id,
                        "channel": "tts",
                        "emitted_at": utc_now_iso(),
                    }
                )
                continue

            if msg.get("type") != "synthesize":
                await ws.send_json(
                    {
                        "type": "error",
                        "error": "Expected {type: 'synthesize', text: '...'}",
                        "session_id": session_id,
                        "channel": "tts",
                        "emitted_at": utc_now_iso(),
                    }
                )
                continue

            cleaned_text = clean_transcript(msg.get("text", ""))
            if not cleaned_text:
                await ws.send_json(
                    {
                        "type": "error",
                        "error": "TTS input cannot be empty.",
                        "session_id": session_id,
                        "channel": "tts",
                        "emitted_at": utc_now_iso(),
                    }
                )
                continue

            segments = _build_tts_segment_inputs(
                msg.get("segments"),
                cleaned_text,
                fallback_languages=msg.get("languages"),
                fallback_language=msg.get("language"),
            )
            stream_state = new_stream_state("tts", session_id)
            await ws.send_json(
                build_stream_started_event(
                    stream_state,
                    {
                        "segment_count": len(segments),
                        "preferred_language": msg.get("language") or "",
                        "languages": msg.get("languages") or [],
                    },
                )
            )
            await ws.send_json(
                enrich_stream_event(
                    stream_state,
                    {
                        "type": "tts_info",
                        "segment_count": len(segments),
                        "available_providers": tts_router.available_providers(),
                    },
                )
            )

            try:
                result = await tts_router.synthesize_segments(
                    segments,
                    languages=msg.get("languages"),
                    preferred_language=msg.get("language"),
                )
            except Exception as exc:
                store.record_error(session_id, "ws.tts", str(exc))
                latency_ms = _elapsed_ms(started_at)
                store.record_latency(session_id, "ws.tts", latency_ms, status="error")
                await ws.send_json(
                    enrich_stream_event(stream_state, {"type": "error", "error": str(exc)})
                )
                await ws.send_json(
                    build_stream_complete_event(stream_state, "error", latency_ms, {"error": str(exc)})
                )
                continue

            for segment_result in result.segments:
                await ws.send_json(
                    enrich_stream_event(
                        stream_state,
                        {
                            "type": "audio_chunk",
                            "segment_index": segment_result.index,
                            "text": segment_result.text,
                            "language": segment_result.language,
                            "provider": segment_result.provider,
                            "mime_type": segment_result.mime_type,
                            "sample_rate": segment_result.sample_rate,
                            "duration_ms": segment_result.duration_ms,
                            "audio_b64": segment_result.audio_b64,
                        },
                    )
                )

            await ws.send_json(
                enrich_stream_event(
                    stream_state,
                    {
                        "type": "final",
                        "status": "ok",
                        "text": result.text,
                        "language": result.language,
                        "provider": result.provider,
                        "mime_type": result.mime_type,
                        "sample_rate": result.sample_rate,
                        "segment_count": len(result.segments),
                        "audio_b64": result.audio_b64,
                    },
                )
            )
            latency_ms = _elapsed_ms(started_at)
            store.record_latency(
                session_id,
                "ws.tts",
                latency_ms,
                status="ok",
                details={
                    "provider": result.provider,
                    "language": result.language,
                    "segment_count": len(result.segments),
                },
            )
            await ws.send_json(
                build_stream_complete_event(
                    stream_state,
                    "ok",
                    latency_ms,
                    {
                        "provider": result.provider,
                        "language": result.language,
                        "segment_count": len(result.segments),
                    },
                )
            )
    except WebSocketDisconnect:
        log.info(f"TTS WebSocket disconnected: session={session_id}")
    except Exception as exc:
        log.error(f"TTS WebSocket error [{session_id}]: {exc}")
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "error", "error": str(exc)})
                await ws.close(code=1011, reason=str(exc))
        except Exception:
            pass
