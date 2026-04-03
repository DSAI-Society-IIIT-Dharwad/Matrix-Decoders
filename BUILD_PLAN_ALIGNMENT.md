# Build Plan Alignment

Date: 2026-04-03

This document maps the current repository state to `nudiscribe_build_plan.txt`.

Validation mode for this pass:

- static code and documentation review only
- no backend startup
- no test execution
- no network or model-runtime verification

## Overall Status

The repository now covers the backend side of build-plan Phases 1 through 5 in code.

Important scope limits:

- the build plan includes a frontend, but this repository is backend-only
- Phase 5 is code-complete in-repo, but real runtime verification must be executed on Ubuntu with the project venv and model assets
- Phases 6 and 7 are still pending

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
- [x] smoke-test entrypoint exists and rejects tone fallback by default during live Phase 5 validation
- [ ] real runtime verification on Ubuntu still needs to be executed
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

- [x] in-memory session storage exists
- [ ] persistent database storage is not implemented
- [ ] transcript persistence is not implemented
- [ ] latency/error persistence is not implemented

Primary files:

- `backend/app/memory.py`

## Phase 7 - Containerize And Deploy

Build-plan intent:

- Docker
- Compose or service topology
- deployment path

Repository status:

- [ ] not implemented

## Static Consistency Fixes Applied In This Pass

- config loading now supports both repo-root `.env` and `backend/.env`
- health output now distinguishes general TTS readiness from real-speech provider readiness
- runtime validation now reports missing packages and provider issues
- product smoke-test file now exists for self-check and live backend testing
- TTS merging now normalizes WAV format before combining segments
- several encoding-affected files were normalized to plain text
- local-client dependency alignment was improved by listing `sounddevice` in `backend/requirements.txt`

## What Still Must Happen On Ubuntu

1. Activate the project venv.
2. Confirm `.env` values for Ollama and TTS assets.
3. Run `python backend/app/product_smoke_test.py --self-check --run-command-probes`.
4. Run `python -m py_compile` over the backend files.
5. Start FastAPI from `backend/`.
6. Run the live smoke test.
7. If any provider or endpoint fails, patch only the failing runtime issue and rerun the smoke test.
8. When all Phase 5 runtime checks pass, start Phase 6 work.
