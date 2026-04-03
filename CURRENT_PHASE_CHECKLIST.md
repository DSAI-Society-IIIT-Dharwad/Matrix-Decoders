# Current Workflow Checklist

Date: 2026-04-03

This status review is based on:

- `nudiscribe_build_plan.txt`
- `README.md`
- `UBUNTU_HANDOFF_README.md`
- `.env.example`
- `backend/requirements.txt`
- all current source files under `backend/app/`

This pass was validated statically in the current workspace without running the backend or test commands.

## Phase Assessment

The backend implementation has moved past the ASR and code-mixed-routing stages and now has a completed in-repo `Phase 5 - Add TTS` implementation, including readiness diagnostics and a smoke-test entrypoint.

Important nuance:

- backend coverage for Phases 1-4 is largely present
- product-level Phase 1 is not fully complete because the build plan expects a frontend text UI/display and this repo has no frontend
- Phase 6 is not started in the build-plan sense because session memory is still in-process only and there is no database or persistence layer

## Workflow Phase Summary

- [x] Phase 1 backend text/WebSocket/Ollama pipeline
- [x] Phase 2 Whisper ASR
- [x] Phase 3 IndicConformer routing
- [x] Phase 4 segment-based code-mixed routing
- [x] Phase 5 TTS fully complete in repository code
- [ ] Phase 6 persistence
- [ ] Phase 7 containerization and deployment

## Current Phase Checklist: Phase 5 - TTS Integration And Verification

### Completed In This Phase

- [x] `POST /api/tts` is implemented
- [x] `ws://.../ws/tts/{session_id}` is implemented
- [x] the orchestrator emits a sentence-level `tts_plan`
- [x] the orchestrator emits structured `tts_segments` metadata for downstream synthesis
- [x] the TTS router uses a provider stack of AI4Bharat Indic -> Piper -> Coqui -> tone fallback
- [x] segment-wise synthesis returns per-segment audio metadata
- [x] final merged WAV output is produced from segment audio
- [x] `.env.example` contains AI4Bharat model/config/vocoder variables for Hindi and Kannada
- [x] `backend/requirements.txt` includes the `TTS` dependency
- [x] a manual TTS WebSocket test client exists
- [x] a product smoke-test entrypoint exists for static checks and live backend checks
- [x] startup/runtime validation reports TTS provider readiness and warnings
- [x] merged WAV output is normalized to a single output format before batching
- [x] config loading supports both `backend/.env` and repo-root `.env`

### Remaining In This Phase

- [ ] execute the smoke test on the Ubuntu runtime with the real venv and model assets
- [ ] bind real Hindi AI4Bharat asset paths in `.env` if they are not already present on Ubuntu
- [ ] bind real Kannada AI4Bharat asset paths in `.env` if they are not already present on Ubuntu
- [ ] run end-to-end verification for `POST /api/tts` with real speech output
- [ ] run end-to-end verification for `ws://.../ws/tts/{session_id}` and inspect both `audio_chunk` and `final` events
- [ ] connect synthesized audio to a frontend playback flow because no frontend exists in this repository

## Not Started Yet: Next Workflow Phase

These items belong to the next build-plan phase after TTS verification and are still pending:

- [ ] persistent storage for session history, transcripts, latency, and errors
- [ ] automated tests
- [ ] Docker or deployment setup
- [ ] CI and observability
- [ ] auth or access control

## Notes

- the most accurate status document right now is `UBUNTU_HANDOFF_README.md`, which correctly describes AI4Bharat TTS as partially implemented
- `README.md` now includes the smoke-test workflow and supports either repo-root `.env` or `backend/.env`
- `README.md` and several source files still contain encoding/mojibake artifacts and should be cleaned up in a later hardening pass
