# Current Workflow Checklist

Date: 2026-04-04

This status review is based on:

- `nudiscribe_build_plan.txt`
- `README.md`
- `UBUNTU_HANDOFF_README.md`
- `.env.example`
- `backend/requirements.txt`
- all current source files under `backend/app/`

This pass now includes direct ASR runtime validation, the persistence implementation pass,
and the first working frontend integration slice.

## Phase Assessment

The implementation now has a validated audio-first runtime plus a working frontend:
audio WebSocket input -> ASR -> LLM -> persistence -> React operator surface. The
Whisper runtime can load the local fine-tuned checkpoints, but the selected default
remains the base Whisper model because the current checkpoint benchmark did not show
a quality win. TTS remains enabled in config, but the current workspace only has
tone fallback because no real speech provider is presently usable.

Important nuance:

- backend coverage for Phases 1-4 is largely present
- product-level Phase 1 now has a working frontend text UI/display over the current backend
- Phase 5 TTS is implemented in code, but the current local runtime only has tone fallback
- Phase 6 now includes SQLite persistence, transcript/telemetry persistence, stable DB path resolution, and retrieval surfaces for session summaries/details
- the ASR runtime-selection path is now a real part of the deployed backend behavior, with base Whisper currently selected by benchmark

## Workflow Phase Summary

- [x] Phase 1 text/WebSocket/Ollama pipeline with frontend text UI
- [x] Phase 2 Whisper ASR
- [x] Phase 3 IndicConformer routing
- [x] Phase 4 segment-based code-mixed routing
- [x] Phase 5 TTS code path exists, but only tone fallback is currently available in the local runtime
- [x] Phase 6 persistence foundation and retrieval surface
- [ ] Phase 7 containerization and deployment

## Current Phase Checklist: Phase 6 - Persistence Foundation

### Completed In This Phase

- [x] the current local runtime self-check now passes with the configured fine-tuned ASR path and tone-fallback TTS
- [x] the audio WebSocket input path is the current ingestion path for later workflows
- [x] the runtime ASR path can load a valid local fine-tuned Whisper checkpoint and falls back safely to `ASR_BASE_MODEL`
- [x] the current benchmark pass keeps base Whisper as the selected default runtime
- [x] the backend now persists session history to SQLite
- [x] the backend now persists transcripts, selected language, latency, and errors
- [x] the backend now exposes session summary and session-detail retrieval for the frontend
- [x] `POST /api/transcribe` now accepts an optional `session_id` so upload transcripts join the current session
- [x] relative `PERSISTENCE_DB_PATH` values now resolve against the repository root
- [x] `.env.example` now includes `PERSISTENCE_DB_PATH`
- [x] `.env.example` now exposes `ASR_RUNTIME_PREFER_FINETUNED` for controlled runtime comparison
- [x] a React + TypeScript + Vite frontend now exists under `frontend/`
- [x] the frontend is wired to `/`, `/api/health`, `/api/chat`, `/api/transcribe`, `/api/tts`, `/api/sessions`, `DELETE /api/session/{session_id}`, `GET /api/session/{session_id}`, `WS /ws/{session_id}`, `WS /ws/audio/{session_id}`, and `WS /ws/tts/{session_id}`
- [x] the frontend microphone flow follows `audio_test_client.py`: raw `pcm_s16le`, mono, negotiated config, binary chunks, and explicit `commit`
- [x] the frontend now includes command-center, live conversation, playback, editable review, and session-history/dashboard surfaces
- [x] frontend and backend validation now includes `py_compile`, runtime self-check, TypeScript build, Vite production build, and in-process REST/WebSocket validation

### Remaining In This Phase

- [ ] add automated tests around the persistence boundary
- [ ] add automated tests around the ASR runtime-selection boundary
- [ ] build a stronger multilingual benchmark set before reconsidering fine-tuned checkpoints as the default runtime
- [ ] replace the client-side structured review heuristic with a backend/domain-aware structured extractor
- [ ] decide whether to keep tone fallback for local development or re-enable a real TTS provider later
- [ ] deepen the dashboard/search/reporting layer beyond the current session summary/detail surfaces
- [ ] add automated browser-level frontend tests around the live audio/TTS workflow

## Not Started Yet: Next Workflow Phase

These items belong to the next build-plan phase after persistence and are still pending:

- [ ] automated tests
- [ ] Docker or deployment setup
- [ ] CI and observability
- [ ] auth or access control
- [ ] backend-owned domain workflows, outbound flows, and compliance/security hardening from the problem statement

## Notes

- the most accurate status document right now is `UBUNTU_HANDOFF_README.md`, which records the completed Ubuntu validation and the current persistence status
- `BUILD_PLAN_ALIGNMENT.md` now captures the broader gap between the technical build plan and the hackathon problem statement
- `README.md` now includes the smoke-test workflow and supports either repo-root `.env` or `backend/.env`
- `ASR_SESSION_WORKFLOW.md` now reflects the completed runtime checkpoint integration and the follow-up validation commands
- `README.md` and several source files still contain encoding/mojibake artifacts and should be cleaned up in a later hardening pass
