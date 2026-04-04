import json
import os
import time
import wave

from fastapi import APIRouter, File, UploadFile, WebSocket
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect, WebSocketState

from .asr.router import ASRRouter
from .audio_utils import AudioFormatConfig, trim_pcm16_silence
from .logger import get_logger
from .memory import store
from .ollama_client import OllamaClient
from .orchestrator import Orchestrator
from .runtime_validation import collect_runtime_validation_report
from .schemas import ChatRequest, ChatResponse, HealthResponse, TTSRequest, TTSResponse
from .training.archive import archive_training_audio
from .transcript_cleaner import clean_transcript
from .tts_router import TTSSegmentInput, tts_router

log = get_logger("api")

router = APIRouter()
orch = Orchestrator()
asr_router = ASRRouter()
ollama_client = OllamaClient()

_start_time = time.time()
_ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


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


@router.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check with model status and uptime."""
    ollama_ok = await ollama_client.is_available()
    validation_report = collect_runtime_validation_report(run_command_probes=False)
    available_tts_providers = tts_router.available_providers()
    available_real_tts_providers = tts_router.available_real_speech_providers()
    tts_ready = bool(available_tts_providers)
    tts_real_ready = bool(available_real_tts_providers)
    health_status = "ok"
    if not ollama_ok or (
        bool(validation_report.settings_summary["enable_tts"]) and not tts_ready
    ):
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


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Text chat endpoint with language-aware validation."""
    started_at = time.perf_counter()
    cleaned_text = clean_transcript(request.text)
    if not cleaned_text:
        message = "Text input cannot be empty."
        store.record_error(request.session_id, "api.chat", message)
        store.record_latency(request.session_id, "api.chat", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=400, content={"error": "Text input cannot be empty."})

    log.info(f"Chat request [{request.session_id}]: '{cleaned_text[:60]}...'")

    response_text = ""
    language = "en"
    languages = []
    is_code_mixed = False

    async for event in orch.process(request.session_id, cleaned_text):
        if event["type"] == "delta":
            response_text += event["text"]
        elif event["type"] == "final":
            language = event.get("language", "en")
            languages = event.get("languages", [])
            is_code_mixed = event.get("is_code_mixed", False)
        elif event["type"] == "error":
            store.record_error(request.session_id, "api.chat", event["error"])
            store.record_latency(
                request.session_id,
                "api.chat",
                _elapsed_ms(started_at),
                status="error",
                details={"input_length": len(cleaned_text)},
            )
            return JSONResponse(status_code=500, content={"error": event["error"]})

    if languages:
        store.track_languages(request.session_id, set(languages))
    if language:
        store.set_selected_language(request.session_id, language)
    store.record_latency(
        request.session_id,
        "api.chat",
        _elapsed_ms(started_at),
        status="ok",
        details={"response_language": language, "is_code_mixed": is_code_mixed},
    )

    return ChatResponse(
        text=response_text,
        language=language,
        languages=languages,
        is_code_mixed=is_code_mixed,
        session_id=request.session_id,
    )


@router.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Upload an audio file and return cleaned transcript metadata."""
    log.info(f"Transcribe request: {file.filename}")
    started_at = time.perf_counter()
    filename = file.filename or ""

    suffix = os.path.splitext(filename)[1].lower()
    if suffix and suffix not in _ALLOWED_AUDIO_EXTENSIONS:
        message = (
            f"Unsupported audio format '{suffix}'. Expected one of {sorted(_ALLOWED_AUDIO_EXTENSIONS)}."
        )
        store.record_error(None, "api.transcribe", message, details={"filename": filename})
        store.record_latency(None, "api.transcribe", _elapsed_ms(started_at), status="error")
        return JSONResponse(
            status_code=400,
            content={
                "error": message
            },
        )

    os.makedirs("temp_audio", exist_ok=True)
    temp_suffix = suffix or ".wav"
    temp_path = f"temp_audio/upload_{int(time.time())}{temp_suffix}"

    try:
        contents = await file.read()
        if not contents:
            message = "Uploaded audio file is empty."
            store.record_error(None, "api.transcribe", message, details={"filename": filename})
            store.record_latency(None, "api.transcribe", _elapsed_ms(started_at), status="error")
            return JSONResponse(status_code=400, content={"error": "Uploaded audio file is empty."})

        with open(temp_path, "wb") as f:
            f.write(contents)

        result = await asr_router.transcribe_full(temp_path)
        store.record_transcript(
            session_id=None,
            source="api.transcribe",
            text=result.text,
            dominant_language=result.dominant_language,
            languages=result.languages,
            is_code_mixed=result.is_code_mixed,
            segments=result.segments,
            details={"filename": filename, "content_type": file.content_type or ""},
        )
        store.record_latency(
            None,
            "api.transcribe",
            _elapsed_ms(started_at),
            status="ok",
            details={"filename": filename, "language": result.dominant_language},
        )
        archive_training_audio(
            audio_path=temp_path,
            text=result.text,
            dominant_language=result.dominant_language,
            languages=result.languages,
            is_code_mixed=result.is_code_mixed,
            source="api.transcribe",
            details={"filename": filename, "content_type": file.content_type or ""},
        )

        return {
            "text": result.text,
            "language": result.dominant_language,
            "languages": list(result.languages),
            "is_code_mixed": result.is_code_mixed,
            "segments": result.segments,
        }

    except Exception as e:
        log.error(f"Transcription failed: {e}")
        store.record_error(None, "api.transcribe", str(e), details={"filename": filename})
        store.record_latency(None, "api.transcribe", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=500, content={"error": str(e)})

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/api/tts", response_model=TTSResponse)
async def synthesize_speech(request: TTSRequest):
    """Synthesize speech for the provided text."""
    started_at = time.perf_counter()
    cleaned_text = clean_transcript(request.text)
    if not cleaned_text:
        message = "TTS input cannot be empty."
        store.record_error(None, "api.tts", message)
        store.record_latency(None, "api.tts", _elapsed_ms(started_at), status="error")
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
    except ValueError as e:
        store.record_error(None, "api.tts", str(e))
        store.record_latency(None, "api.tts", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=400, content={"error": str(e)})
    except RuntimeError as e:
        store.record_error(None, "api.tts", str(e))
        store.record_latency(None, "api.tts", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        log.error(f"TTS synthesis failed: {e}")
        store.record_error(None, "api.tts", str(e))
        store.record_latency(None, "api.tts", _elapsed_ms(started_at), status="error")
        return JSONResponse(status_code=500, content={"error": str(e)})

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
    """Clear conversation history for a session."""
    store.clear(session_id)
    return {"status": "cleared", "session_id": session_id}


@router.get("/api/sessions")
async def list_sessions():
    """List all active sessions."""
    return {"sessions": store.list_sessions(), "count": store.session_count()}


@router.websocket("/ws/{session_id}")
async def text_ws(ws: WebSocket, session_id: str):
    """WebSocket endpoint for streaming text chat."""
    await ws.accept()
    log.info(f"WebSocket connected: session={session_id}")

    try:
        while True:
            raw = await ws.receive_text()
            started_at = time.perf_counter()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                store.record_error(session_id, "ws.text", "Invalid JSON")
                store.record_latency(session_id, "ws.text", _elapsed_ms(started_at), status="error")
                await ws.send_json({"type": "error", "error": "Invalid JSON"})
                continue

            cleaned_text = clean_transcript(msg.get("text", ""))
            if msg.get("type") != "input" or not cleaned_text:
                message = "Expected {type: 'input', text: '...'}"
                store.record_error(session_id, "ws.text", message)
                store.record_latency(session_id, "ws.text", _elapsed_ms(started_at), status="error")
                await ws.send_json(
                    {"type": "error", "error": message}
                )
                continue

            final_event = None
            pipeline_error = None
            async for event in orch.process(session_id, cleaned_text):
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(event)
                if event["type"] == "final":
                    final_event = event
                elif event["type"] == "error":
                    pipeline_error = event.get("error", "Unknown text WebSocket error")

            latency_ms = _elapsed_ms(started_at)
            if pipeline_error:
                store.record_error(session_id, "ws.text", pipeline_error)
                store.record_latency(session_id, "ws.text", latency_ms, status="error")
                continue

            if final_event:
                final_languages = final_event.get("languages") or []
                if final_languages:
                    store.track_languages(session_id, set(final_languages))
                if final_event.get("language"):
                    store.set_selected_language(session_id, final_event["language"])
                store.record_latency(
                    session_id,
                    "ws.text",
                    latency_ms,
                    status="ok",
                    details={
                        "response_language": final_event.get("language", ""),
                        "is_code_mixed": bool(final_event.get("is_code_mixed", False)),
                    },
                )

    except WebSocketDisconnect:
        log.info(f"WebSocket disconnected: session={session_id}")
    except Exception as e:
        log.error(f"WebSocket error [{session_id}]: {e}")
        store.record_error(session_id, "ws.text", str(e))
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "error", "error": str(e)})
                await ws.close(code=1011, reason=str(e))
        except Exception:
            pass


@router.websocket("/ws/audio/{session_id}")
async def audio_ws(ws: WebSocket, session_id: str):
    """WebSocket endpoint for streaming 16-bit PCM audio."""
    await ws.accept()
    log.info(f"Audio WebSocket connected: session={session_id}")

    audio_buffer = bytearray()
    audio_config = AudioFormatConfig()
    last_audio_time = time.time()
    commit_driven_mode = False

    silence_timeout = 1.2

    async def flush_audio_buffer():
        nonlocal audio_buffer

        if not audio_buffer:
            return

        pcm_audio = trim_pcm16_silence(bytes(audio_buffer), channels=audio_config.channels)
        audio_buffer.clear()

        if not pcm_audio:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "audio_skipped", "reason": "silence"})
            return

        log.info(
            "Processing audio "
            f"({len(pcm_audio)} bytes, {audio_config.sample_rate}Hz, {audio_config.channels}ch)..."
        )
        started_at = time.perf_counter()

        os.makedirs("temp_audio", exist_ok=True)
        temp_path = f"temp_audio/{session_id}_{int(time.time())}.wav"

        try:
            with wave.open(temp_path, "wb") as wf:
                wf.setnchannels(audio_config.channels)
                wf.setsampwidth(audio_config.sample_width)
                wf.setframerate(audio_config.sample_rate)
                wf.writeframes(pcm_audio)

            transcription_event = None
            final_event = None
            pipeline_error = None

            async for event in orch.process_audio(session_id, temp_path):
                if event["type"] == "transcription":
                    transcription_event = event
                elif event["type"] == "final":
                    final_event = event
                elif event["type"] == "error":
                    pipeline_error = event.get("error", "Unknown audio pipeline error")

                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(event)

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
                    },
                )
                archive_training_audio(
                    audio_path=temp_path,
                    text=str(transcription_event.get("text", "")),
                    dominant_language=transcription_event.get("language"),
                    languages=transcription_event.get("languages") or [],
                    is_code_mixed=bool(transcription_event.get("is_code_mixed", False)),
                    source="ws.audio",
                    session_id=session_id,
                    details={
                        "sample_rate": audio_config.sample_rate,
                        "channels": audio_config.channels,
                    },
                )

            latency_ms = _elapsed_ms(started_at)
            if pipeline_error:
                store.record_error(
                    session_id,
                    "ws.audio",
                    pipeline_error,
                    details={
                        "sample_rate": audio_config.sample_rate,
                        "channels": audio_config.channels,
                    },
                )
                store.record_latency(
                    session_id,
                    "ws.audio",
                    latency_ms,
                    status="error",
                    details={
                        "sample_rate": audio_config.sample_rate,
                        "channels": audio_config.channels,
                    },
                )
            elif final_event:
                final_languages = final_event.get("languages") or []
                if final_languages:
                    store.track_languages(session_id, set(final_languages))
                if final_event.get("language"):
                    store.set_selected_language(session_id, final_event["language"])
                store.record_latency(
                    session_id,
                    "ws.audio",
                    latency_ms,
                    status="ok",
                    details={
                        "sample_rate": audio_config.sample_rate,
                        "channels": audio_config.channels,
                        "transcript_language": (
                            transcription_event.get("language", "") if transcription_event else ""
                        ),
                    },
                )

        except Exception as e:
            log.error(f"Audio processing error: {e}")
            store.record_error(
                session_id,
                "ws.audio",
                str(e),
                details={"sample_rate": audio_config.sample_rate, "channels": audio_config.channels},
            )
            store.record_latency(
                session_id,
                "ws.audio",
                _elapsed_ms(started_at),
                status="error",
                details={"sample_rate": audio_config.sample_rate, "channels": audio_config.channels},
            )
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "error", "error": str(e)})

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    try:
        while True:
            try:
                data = await ws.receive()
            except WebSocketDisconnect:
                log.info(f"Audio client disconnected: session={session_id}")
                break
            except RuntimeError as e:
                if "disconnect message has been received" in str(e).lower():
                    log.info(f"Audio client disconnected: session={session_id}")
                    break
                raise

            if "bytes" in data and data["bytes"] is not None:
                chunk = data["bytes"]
                max_chunk_bytes = audio_config.max_chunk_bytes()

                if len(chunk) > max_chunk_bytes:
                    await ws.send_json(
                        {
                            "type": "error",
                            "error": f"Audio chunk too large ({len(chunk)} bytes). Max allowed is {max_chunk_bytes} for the negotiated audio format.",
                        }
                    )
                    continue

                if len(chunk) % audio_config.frame_size != 0:
                    await ws.send_json(
                        {
                            "type": "error",
                            "error": "Invalid PCM frame received. Expected complete 16-bit PCM frames for the negotiated channel count.",
                        }
                    )
                    continue

                audio_buffer.extend(chunk)
                last_audio_time = time.time()
                log.debug(f"Buffer: {len(audio_buffer)} bytes")

            elif "text" in data and data["text"] is not None:
                raw_text = data["text"].strip()
                command = raw_text.lower()

                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError:
                    payload = None

                if isinstance(payload, dict):
                    message_type = str(payload.get("type", "")).lower()

                    if message_type in {"start", "config"}:
                        try:
                            audio_config = AudioFormatConfig.from_message(payload)
                        except ValueError as e:
                            await ws.send_json({"type": "error", "error": str(e)})
                            continue
                        commit_driven_mode = True

                        await ws.send_json(
                            {
                                "type": "audio_config",
                                "sample_rate": audio_config.sample_rate,
                                "channels": audio_config.channels,
                                "sample_width": audio_config.sample_width,
                                "encoding": audio_config.encoding,
                                "max_chunk_bytes": audio_config.max_chunk_bytes(),
                            }
                        )
                        continue

                    if message_type == "commit":
                        await flush_audio_buffer()
                        continue
                    if message_type == "reset":
                        audio_buffer.clear()
                        await ws.send_json({"type": "audio_reset"})
                        continue
                    if message_type == "ping":
                        await ws.send_json({"type": "pong"})
                        continue

                if command == "commit":
                    await flush_audio_buffer()
                    continue
                if command == "reset":
                    audio_buffer.clear()
                    await ws.send_json({"type": "audio_reset"})
                    continue
                if command == "ping":
                    await ws.send_json({"type": "pong"})
                    continue

                await ws.send_json(
                    {
                        "type": "error",
                        "error": "Unsupported audio control message. Use 'commit', 'reset', or 'ping'.",
                    }
                )
                continue

            current_time = time.time()
            max_buffer_size = audio_config.max_buffer_bytes()
            should_flush = current_time - last_audio_time > silence_timeout
            if not commit_driven_mode:
                should_flush = should_flush or len(audio_buffer) >= max_buffer_size

            if audio_buffer and should_flush:
                await flush_audio_buffer()

    except WebSocketDisconnect:
        log.info(f"Audio WebSocket disconnected: session={session_id}")
    except Exception as e:
        log.error(f"Audio WebSocket error [{session_id}]: {e}")
        store.record_error(session_id, "ws.audio", str(e))
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.close(code=1011, reason=str(e))
        except Exception:
            pass


@router.websocket("/ws/tts/{session_id}")
async def tts_ws(ws: WebSocket, session_id: str):
    """WebSocket endpoint for TTS synthesis."""
    await ws.accept()
    log.info(f"TTS WebSocket connected: session={session_id}")

    try:
        while True:
            raw = await ws.receive_text()
            started_at = time.perf_counter()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                store.record_error(session_id, "ws.tts", "Invalid JSON")
                store.record_latency(session_id, "ws.tts", _elapsed_ms(started_at), status="error")
                await ws.send_json({"type": "error", "error": "Invalid JSON"})
                continue

            if msg.get("type") != "synthesize":
                message = "Expected {type: 'synthesize', text: '...'}"
                store.record_error(session_id, "ws.tts", message)
                store.record_latency(session_id, "ws.tts", _elapsed_ms(started_at), status="error")
                await ws.send_json(
                    {
                        "type": "error",
                        "error": message,
                    }
                )
                continue

            cleaned_text = clean_transcript(msg.get("text", ""))
            if not cleaned_text:
                message = "TTS input cannot be empty."
                store.record_error(session_id, "ws.tts", message)
                store.record_latency(session_id, "ws.tts", _elapsed_ms(started_at), status="error")
                await ws.send_json({"type": "error", "error": "TTS input cannot be empty."})
                continue

            segments = _build_tts_segment_inputs(
                msg.get("segments"),
                cleaned_text,
                fallback_languages=msg.get("languages"),
                fallback_language=msg.get("language"),
            )

            await ws.send_json(
                {
                    "type": "tts_info",
                    "session_id": session_id,
                    "segment_count": len(segments),
                    "available_providers": tts_router.available_providers(),
                }
            )

            try:
                result = await tts_router.synthesize_segments(
                    segments,
                    languages=msg.get("languages"),
                    preferred_language=msg.get("language"),
                )
            except Exception as e:
                store.record_error(session_id, "ws.tts", str(e))
                store.record_latency(session_id, "ws.tts", _elapsed_ms(started_at), status="error")
                await ws.send_json({"type": "error", "error": str(e)})
                continue

            for segment_result in result.segments:
                await ws.send_json(
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
                    }
                )

            await ws.send_json(
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
                }
            )
            message_languages = msg.get("languages") or []
            if message_languages:
                store.track_languages(session_id, set(message_languages))
            if result.language:
                store.set_selected_language(session_id, result.language)
            store.record_latency(
                session_id,
                "ws.tts",
                _elapsed_ms(started_at),
                status="ok",
                details={
                    "provider": result.provider,
                    "language": result.language,
                    "segment_count": len(result.segments),
                },
            )

    except WebSocketDisconnect:
        log.info(f"TTS WebSocket disconnected: session={session_id}")
    except Exception as e:
        log.error(f"TTS WebSocket error [{session_id}]: {e}")
        store.record_error(session_id, "ws.tts", str(e))
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json({"type": "error", "error": str(e)})
                await ws.close(code=1011, reason=str(e))
        except Exception:
            pass
