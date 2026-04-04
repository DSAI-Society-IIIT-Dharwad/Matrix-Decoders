# Current Workflow Checklist

Date: 2026-04-04

This status review is based on:

- `nudiscribe_build_plan.txt`
- `README.md`
- `UBUNTU_HANDOFF_README.md`
- `.env.example`
- `backend/requirements.txt`
- all current source files under `backend/app/`

This pass now includes direct ASR runtime validation plus the current persistence implementation pass.

## Phase Assessment

The backend implementation now has a validated audio-first runtime: audio WebSocket input -> ASR -> LLM -> persistence. The Whisper runtime can load the local fine-tuned checkpoints, but the selected default remains the base Whisper model because the current checkpoint benchmark did not show a quality win. TTS remains enabled in config, but the current workspace only has tone fallback because no real speech provider is presently usable.

Important nuance:

- backend coverage for Phases 1-4 is largely present
- product-level Phase 1 is not fully complete because the build plan expects a frontend text UI/display and this repo has no frontend
- Phase 5 TTS is implemented in code, but the current local runtime only has tone fallback
- Phase 6 is the active foundation: SQLite persistence, transcript/telemetry persistence, and stable DB path resolution
- the ASR runtime-selection path is now a real part of the deployed backend behavior, with base Whisper currently selected by benchmark

## Workflow Phase Summary

- [x] Phase 1 backend text/WebSocket/Ollama pipeline
- [x] Phase 2 Whisper ASR
- [x] Phase 3 IndicConformer routing
- [x] Phase 4 segment-based code-mixed routing
- [x] Phase 5 TTS code path exists, but only tone fallback is currently available in the local runtime
- [x] Phase 6 persistence foundation
- [ ] Phase 7 containerization and deployment

## Current Phase Checklist: Phase 6 - Persistence Foundation

### Completed In This Phase

- [x] the current local runtime self-check now passes with the configured fine-tuned ASR path and tone-fallback TTS
- [x] the audio WebSocket input path is the current ingestion path for later workflows
- [x] the runtime ASR path can load a valid local fine-tuned Whisper checkpoint and falls back safely to `ASR_BASE_MODEL`
- [x] the current benchmark pass keeps base Whisper as the selected default runtime
- [x] the backend now persists session history to SQLite
- [x] the backend now persists transcripts, selected language, latency, and errors
- [x] relative `PERSISTENCE_DB_PATH` values now resolve against the repository root
- [x] `.env.example` now includes `PERSISTENCE_DB_PATH`
- [x] `.env.example` now exposes `ASR_RUNTIME_PREFER_FINETUNED` for controlled runtime comparison

### Remaining In This Phase

- [ ] add automated tests around the persistence boundary
- [ ] add automated tests around the ASR runtime-selection boundary
- [ ] build a stronger multilingual benchmark set before reconsidering fine-tuned checkpoints as the default runtime
- [ ] add structured extraction, review, or reporting surfaces required by the hackathon problem statement
- [ ] decide whether to keep tone fallback for local development or re-enable a real TTS provider later
- [ ] add retrieval/reporting surfaces for persisted transcripts and telemetry if the product needs them
- [ ] connect the audio workflow to a frontend playback or review flow because no frontend exists in this repository

## Not Started Yet: Next Workflow Phase

These items belong to the next build-plan phase after persistence and are still pending:

- [ ] automated tests
- [ ] Docker or deployment setup
- [ ] CI and observability
- [ ] auth or access control
- [ ] editable structured report and dashboard surfaces from the problem statement

## Notes

- the most accurate status document right now is `UBUNTU_HANDOFF_README.md`, which records the completed Ubuntu validation and the current persistence status
- `BUILD_PLAN_ALIGNMENT.md` now captures the broader gap between the technical build plan and the hackathon problem statement
- `README.md` now includes the smoke-test workflow and supports either repo-root `.env` or `backend/.env`
- `ASR_SESSION_WORKFLOW.md` now reflects the completed runtime checkpoint integration and the follow-up validation commands
- `README.md` and several source files still contain encoding/mojibake artifacts and should be cleaned up in a later hardening pass
