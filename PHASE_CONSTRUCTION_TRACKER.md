# Phase Construction Tracker

Date: 2026-04-03

This file is the working construction log for the current repository. It has three jobs:

- define the recommended build order from here
- map the end-to-end workflow to the actual code files
- record what changed in this cleanup pass and what still remains

## Recommended Build Order

Short answer:

- do not postpone every product feature until after the frontend and then try to build them all in one batch
- do not mix all advanced product features into the core backend while the main speech workflow is still being stabilized

Recommended order:

1. finish and harden the key backend workflow first
2. build a thin frontend that exercises the existing backend end to end
3. add the remaining product features one vertical slice at a time

Why this order is the right tradeoff:

- the backend workflow is already the foundation for everything else
- a thin frontend exposes protocol and UX gaps early without forcing a large rewrite
- structured extraction, review, dashboards, and domain workflows should be layered in after the base speech loop is visible and testable

## End-To-End Workflow

The intended runtime flow is:

1. input arrives as text, uploaded audio, or streamed PCM audio
2. audio is normalized, buffered, and segmented
3. ASR routing sends English-heavy speech toward Whisper and Hindi/Kannada-heavy speech toward Indic ASR
4. transcript cleanup normalizes text and attaches language metadata
5. orchestration builds a language-aware prompt and streams the request to Ollama
6. the assistant response is split into TTS-ready segments
7. TTS routing picks the best available provider and merges audio segments
8. text, transcript metadata, and audio are returned to the client
9. session history, transcripts, selected language, latency, and errors are persisted

## Workflow To Code Map

### Core runtime files

- [backend/app/main.py](/media/raviteja/Volume/nudiscribe/backend/app/main.py)
  service startup, runtime logging, validation summary
- [backend/app/api.py](/media/raviteja/Volume/nudiscribe/backend/app/api.py)
  REST and WebSocket entrypoints for chat, transcription, audio, TTS, health, and session operations
- [backend/app/orchestrator.py](/media/raviteja/Volume/nudiscribe/backend/app/orchestrator.py)
  core pipeline coordination for text and audio flows
- [backend/app/memory.py](/media/raviteja/Volume/nudiscribe/backend/app/memory.py)
  SQLite-backed session, transcript, and telemetry persistence
- [backend/app/config.py](/media/raviteja/Volume/nudiscribe/backend/app/config.py)
  configuration loading and env-file resolution
- [backend/app/schemas.py](/media/raviteja/Volume/nudiscribe/backend/app/schemas.py)
  API schema contract

### ASR and transcript pipeline

- [backend/app/audio_utils.py](/media/raviteja/Volume/nudiscribe/backend/app/audio_utils.py)
  PCM handling and silence trimming
- [backend/app/asr/segmenter.py](/media/raviteja/Volume/nudiscribe/backend/app/asr/segmenter.py)
  segment-based audio splitting
- [backend/app/asr/router.py](/media/raviteja/Volume/nudiscribe/backend/app/asr/router.py)
  ASR routing and merge strategy
- [backend/app/asr/whisper_asr.py](/media/raviteja/Volume/nudiscribe/backend/app/asr/whisper_asr.py)
  Whisper adapter
- [backend/app/asr/indic_asr.py](/media/raviteja/Volume/nudiscribe/backend/app/asr/indic_asr.py)
  IndicConformer adapter
- [backend/app/transcript_cleaner.py](/media/raviteja/Volume/nudiscribe/backend/app/transcript_cleaner.py)
  transcript normalization and segment metadata generation
- [backend/app/language.py](/media/raviteja/Volume/nudiscribe/backend/app/language.py)
  script detection, language dominance, code-mix heuristics

### LLM and response policy

- [backend/app/ollama_client.py](/media/raviteja/Volume/nudiscribe/backend/app/ollama_client.py)
  streaming Ollama client
- [backend/app/prompt.py](/media/raviteja/Volume/nudiscribe/backend/app/prompt.py)
  system prompt and message assembly
- [backend/app/response_policy.py](/media/raviteja/Volume/nudiscribe/backend/app/response_policy.py)
  output-language selection policy

### TTS and runtime validation

- [backend/app/tts_router.py](/media/raviteja/Volume/nudiscribe/backend/app/tts_router.py)
  provider routing, segment synthesis, WAV merge/normalization
- [backend/app/runtime_validation.py](/media/raviteja/Volume/nudiscribe/backend/app/runtime_validation.py)
  provider diagnostics and self-check reporting
- [backend/app/product_smoke_test.py](/media/raviteja/Volume/nudiscribe/backend/app/product_smoke_test.py)
  workflow-level validation entrypoint

### Support and manual client files

- [backend/app/test_client_example.py](/media/raviteja/Volume/nudiscribe/backend/app/test_client_example.py)
  manual text WebSocket test client
- [backend/app/audio_test_client.py](/media/raviteja/Volume/nudiscribe/backend/app/audio_test_client.py)
  manual audio WebSocket test client
- [backend/app/tts_test_client.py](/media/raviteja/Volume/nudiscribe/backend/app/tts_test_client.py)
  manual TTS WebSocket test client

These support files are not part of the backend runtime path, but they are still useful for validation and should be kept.

## Cleanup And Efficiency Changes In This Pass

Changes made:

- reused a module-level ASR router in [backend/app/api.py](/media/raviteja/Volume/nudiscribe/backend/app/api.py) instead of constructing it inside every `/api/transcribe` request
- reused a module-level Ollama client in [backend/app/api.py](/media/raviteja/Volume/nudiscribe/backend/app/api.py) for health checks
- avoided repeated TTS provider list computation in the health endpoint
- added [backend/backend/](/media/raviteja/Volume/nudiscribe/backend/backend/) to `.gitignore` because it is a stale duplicate persistence path from an older relative-path bug
- updated [README.md](/media/raviteja/Volume/nudiscribe/README.md) so the roadmap reflects the current implementation instead of older prototype assumptions

Safe cleanup already identified:

- `backend/app/__pycache__/` is generated and can be removed any time
- `backend/temp_audio_test.wav` is not a valid RIFF/WAV file and should not be used as a workflow test asset

Cleanup intentionally not automated:

- `backend/backend/data/nudiscribe.db` looks like stale data from an older persistence path, but it may contain historical local records, so it should only be deleted when that data is confirmed disposable

## Phase Status

### Phase 1 - Core text pipeline

Completed:

- REST chat endpoint
- text WebSocket endpoint
- Ollama streaming
- language-aware prompt building

Remaining:

- actual frontend text UI
- frontend response display

### Phase 2 - Speech input with Whisper

Completed:

- upload transcription endpoint
- audio WebSocket endpoint
- Whisper adapter
- manual audio test path

Remaining:

- browser/client capture UI
- more robust live-audio protocol testing

### Phase 3 - Indic ASR routing

Completed:

- Indic ASR adapter
- script/language heuristics
- segment metadata generation

Remaining:

- model-quality evaluation against real multilingual samples

### Phase 4 - Code-mixed routing

Completed:

- segment-based routing
- transcript merging
- code-mix awareness in orchestration

Remaining:

- stronger routing confidence logic
- true VAD instead of only energy-style segmentation

### Phase 5 - TTS

Completed:

- REST TTS endpoint
- TTS WebSocket endpoint
- segment planning and merged WAV output
- provider diagnostics and smoke-test validation path
- fallback-capable local runtime

Remaining:

- configure real AI4Bharat Hindi/Kannada assets in the active workspace
- restore or validate a real speech provider in the current runtime if production-like speech output is required
- build frontend playback controls

### Phase 6 - Persistence

Completed:

- SQLite-backed session history
- transcript persistence
- selected-language persistence
- latency and error persistence

Remaining:

- automated tests around persistence
- decide whether to keep SQLite as local-dev storage only
- add retrieval/reporting surfaces only where the product actually needs them

### Phase 7 - Frontend integration

Recommended next execution target:

- build a thin frontend against the current backend
- support text chat, transcript display, audio upload or microphone capture, and TTS playback
- do not add structured extraction or dashboard complexity until this loop is working end to end

### Phase 8 - Product-specific features from the problem statement

Add after the thin frontend exists, one slice at a time:

- structured extractor
- editable review interface
- searchable history and dashboard views
- domain-specific workflow configuration
- auth, compliance, CI, observability, and deployment

## Remaining High-Priority Work

1. keep the backend stable around the current workflow contract
2. build the thin frontend on top of the existing REST and WebSocket endpoints
3. add tests for `memory.py`, ASR routing, transcript cleanup, and the TTS router
4. turn the hackathon-only feature set into explicit vertical slices instead of a single large catch-up phase
