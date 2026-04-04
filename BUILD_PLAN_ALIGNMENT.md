# Build Plan Alignment

Date: 2026-04-04

This document maps the current repository state to `nudiscribe_build_plan.txt`.

Validation mode for this pass:

- static code and documentation review
- direct ASR runtime validation executed in the project venv against the local fine-tuned checkpoint
- runtime self-check executed in the current local workspace
- the active local `.env` keeps TTS enabled, but only tone fallback is currently available because real provider assets are not configured

## Overall Status

The repository now covers build-plan Phases 1 through 6 with a working backend plus
the first frontend integration slice under `frontend/`. The Whisper runtime can load
local fine-tuned checkpoints, but the current selected default stays on base Whisper
because the available checkpoint benchmark does not yet beat the base model on quality.
The current workspace still lacks a configured real-speech TTS provider.

Important scope limits:

- a thin frontend now exists, but the stack is still not production-ready
- the hackathon problem statement adds structured extraction, editable review, dashboards, and domain workflows that are not yet implemented here
- Phase 5 TTS code exists, but the active local runtime currently falls back to tone output because real provider assets are not configured
- Phase 6 now has a working SQLite-backed persistence foundation; PostgreSQL/SQLAlchemy are still future work
- the current fine-tuned Whisper checkpoints are benchmarkable but are not yet the selected default runtime
- Phase 7 is still pending

## Problem Statement Alignment

`IDRP_PS.pdf` describes a broader conversational intelligence system than the technical
build plan alone. Current coverage is:

- covered: multilingual ASR for Kannada, Hindi, English, and code-mixed speech; Ollama-driven conversational backend; persisted interaction history; a frontend for text, audio upload, microphone streaming, TTS playback, editable review draft, and session history
- partial: live voice intake, structured review, and dashboard/history now exist, but the structured extraction is still client-side heuristic logic and the current local TTS runtime is still tone fallback only
- missing: secure in-person recording/compliance controls, automated outbound call handling, backend-owned structured extraction, domain-specific workflow configuration, and production security hardening

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
- [x] frontend text UI exists under `frontend/`
- [x] frontend text response display exists under `frontend/`

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
- [x] runtime Whisper path can load a local fine-tuned checkpoint from `ASR_CHECKPOINT_DIR`
- [x] runtime Whisper path can fall back to `ASR_BASE_MODEL` when checkpoint loading fails or is disabled
- [x] base Whisper remains the selected default runtime after the current checkpoint benchmark pass
- [x] audio upload transcription endpoint exists
- [x] audio WebSocket endpoint exists
- [x] manual audio test client exists
- [x] frontend transcript display exists under `frontend/`

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
- [ ] the current local runtime has TTS enabled, but no real-speech provider is currently usable
- [ ] AI4Bharat Hindi/Kannada assets are still not configured in the current workspace
- [x] frontend playback layer exists under `frontend/`

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
- [x] session summary/detail retrieval endpoints now exist for the frontend dashboard
- [x] the frontend now surfaces session history and detail records
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
- Whisper runtime now supports valid local fine-tuned checkpoints while keeping base-model fallback behavior
- `.env.example` now exposes `ASR_RUNTIME_PREFER_FINETUNED`, with base Whisper kept as the current default selection
- health output now reflects the currently available TTS providers without making degraded local validation fatal
- runtime validation now skips unused TTS provider diagnostics when TTS is disabled
- product smoke-test file now exists for self-check and live backend testing
- `GET /api/session/{session_id}` now exists for persisted frontend detail retrieval
- `POST /api/transcribe` now accepts an optional `session_id`
- a React + TypeScript + Vite frontend now exists under `frontend/`
- the frontend connects the current REST and WebSocket endpoints without changing the backend workflow
- the frontend build now passes `tsc -b` and `vite build`
- in-process validation now covers root, health, session list/detail/clear, REST TTS, WebSocket TTS, WebSocket audio negotiation + commit, REST chat, and text WebSocket streaming
- TTS merging now normalizes WAV format before combining segments
- runtime self-check now shows fine-tuned ASR checkpoint candidates in the settings summary
- a local benchmark pass showed the current fine-tuned checkpoints are not yet better than base Whisper on the known-text sample
- the backend now persists session history, transcripts, selected language, latencies, and errors to SQLite
- several encoding-affected files were normalized to plain text
- local-client dependency alignment was improved by listing `sounddevice` in `backend/requirements.txt`

## What Still Must Happen Next

1. Add automated tests around the ASR runtime-selection path, the persistence boundary, and the frontend-facing session endpoints.
2. Replace the current client-side structured review heuristic with backend/domain-aware structured extraction.
3. Reconfigure a real TTS provider if speech-output validation beyond tone fallback is required.
4. Decide whether to keep SQLite for local-only use and add PostgreSQL/SQLAlchemy for fuller Phase 6 alignment.
5. Build a stronger multilingual benchmark set before reconsidering fine-tuned Whisper as the default runtime.
6. Continue with Phase 7 containerization and deployment work.
