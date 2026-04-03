# Build Plan Alignment

Date: 2026-04-03

This document maps the current repository state to `nudiscribe_build_plan.txt`.

Validation mode for this pass:

- static code and documentation review
- Ubuntu runtime validation executed in the project venv
- backend startup verified in the current local workspace
- the active local `.env` is configured for audio-only validation, so real-speech TTS is not exercised in this run

## Overall Status

The repository now covers the backend side of build-plan Phases 1 through 6 in code, but the current workspace is configured for audio-only validation and does not exercise TTS at startup.

Important scope limits:

- the build plan includes a frontend, but this repository is backend-only
- the hackathon problem statement adds structured extraction, editable review, dashboards, and domain workflows that are not yet implemented here
- Phase 5 TTS code exists, but the active local runtime keeps TTS disabled
- Phase 6 now has a working SQLite-backed persistence foundation; PostgreSQL/SQLAlchemy are still future work
- Phase 7 is still pending

## Problem Statement Alignment

`IDRP_PS.pdf` describes a broader conversational intelligence system than the technical build plan alone. Current coverage is:

- covered: multilingual ASR for Kannada, Hindi, English, and code-mixed speech; Ollama-driven conversational backend; persisted interaction history
- partial: live voice intake via WebSocket audio/file upload and conversational response streaming, but only as a backend pipeline
- missing: secure in-person recording, automated outbound call handling, structured data extraction, editable review interface, searchable dashboard/history, domain-specific workflow configuration, and compliance/security hardening

## Phase 1 - Core Text Pipeline

Build-plan intent:

- frontend text input
- WebSocket backend
- Ollama streaming
- text response display

Repository status:

- [x] REST text chat endpoint exists
- [x] WebSocket text chat endpoint exists
- [x] Ollama streaming client exists
- [x] language-aware prompt building exists
- [ ] frontend text UI is not part of this repository
- [ ] frontend text response display is not part of this repository

Primary files:

- `backend/app/api.py`
- `backend/app/orchestrator.py`
- `backend/app/ollama_client.py`
- `backend/app/prompt.py`

## Phase 2 - Whisper For English Speech

Build-plan intent:

- microphone capture
- Whisper transcription
- transcript display

Repository status:

- [x] Whisper ASR adapter exists
- [x] audio upload transcription endpoint exists
- [x] audio WebSocket endpoint exists
- [x] manual audio test client exists
- [ ] frontend transcript display is not part of this repository

Primary files:

- `backend/app/asr/whisper_asr.py`
- `backend/app/api.py`
- `backend/app/audio_test_client.py`

## Phase 3 - IndicConformer For Kannada And Hindi

Build-plan intent:

- language detector
- Kannada/Hindi routing
- transcript merging

Repository status:

- [x] Indic ASR adapter exists
- [x] language/script heuristics exist
- [x] merged ASR router exists
- [x] transcript cleanup and segment metadata exist

Primary files:

- `backend/app/asr/indic_asr.py`
- `backend/app/asr/router.py`
- `backend/app/language.py`
- `backend/app/transcript_cleaner.py`

## Phase 4 - Code-Mixed Routing

Build-plan intent:

- break speech into segments
- detect language per segment
- route each segment separately
- merge transcripts

Repository status:

- [x] energy-based segmenter exists
- [x] per-segment ASR routing exists
- [x] merged transcript metadata exists
- [x] orchestrator preserves language mix metadata
- [ ] true VAD is still pending

Primary files:

- `backend/app/asr/segmenter.py`
- `backend/app/asr/router.py`
- `backend/app/orchestrator.py`

## Phase 5 - TTS

Build-plan intent:

- Kannada/Hindi TTS with Indic-TTS
- English fallback TTS with Coqui
- stitch audio chunks
- stream audio to frontend

Repository status:

- [x] REST TTS endpoint exists
- [x] TTS WebSocket endpoint exists
- [x] AI4Bharat-first routing exists
- [x] Piper fallback exists
- [x] Coqui fallback exists
- [x] tone fallback exists for non-runtime environments
- [x] sentence-level TTS planning exists
- [x] per-segment synthesis exists
- [x] merged WAV generation exists
- [x] merged WAV normalization exists
- [x] runtime validation exists
- [x] smoke-test entrypoint exists for self-check and live backend testing
- [ ] the current local runtime is audio-only, so real-speech TTS is not exercised by default
- [ ] AI4Bharat Hindi/Kannada assets are still not configured in the current workspace
- [ ] frontend playback layer is not part of this repository

Primary files:

- `backend/app/tts_router.py`
- `backend/app/api.py`
- `backend/app/orchestrator.py`
- `backend/app/runtime_validation.py`
- `backend/app/product_smoke_test.py`

## Phase 6 - Conversation Memory And Persistence

Build-plan intent:

- store session history
- store transcripts
- store selected language
- store latency and errors

Repository status:

- [x] persistence-backed session storage exists
- [x] session language and selected-language persistence exists
- [x] transcript persistence exists
- [x] latency/error persistence exists
- [x] relative SQLite persistence paths now resolve against the repository root
- [ ] PostgreSQL/SQLAlchemy are not implemented; the current persistence layer uses local SQLite

Primary files:

- `backend/app/memory.py`

## Phase 7 - Containerize And Deploy

Build-plan intent:

- Docker
- Compose or service topology
- deployment path

Repository status:

- [ ] not implemented

## Runtime And Persistence Updates Applied In This Pass

- config loading now supports both repo-root `.env` and `backend/.env`
- relative SQLite paths now resolve against the repository root, so the database stays stable regardless of launch directory
- health output now reflects the currently available TTS providers without making audio-only validation fatal
- runtime validation now skips unused TTS provider diagnostics when TTS is disabled
- product smoke-test file now exists for self-check and live backend testing
- TTS merging now normalizes WAV format before combining segments
- the active local runtime is configured for audio-only validation
- the backend now persists session history, transcripts, selected language, latencies, and errors to SQLite
- several encoding-affected files were normalized to plain text
- local-client dependency alignment was improved by listing `sounddevice` in `backend/requirements.txt`

## What Still Must Happen Next

1. Add automated tests around the new persistence boundary.
2. Add the structured extractor, editable review surface, and searchable dashboard implied by the hackathon problem statement.
3. Decide whether to keep the workspace audio-only or re-enable a real TTS provider for speech output validation.
4. Decide whether to keep SQLite for local-only use and add PostgreSQL/SQLAlchemy for fuller Phase 6 alignment.
5. Continue with Phase 7 containerization and deployment work.
