# NudiScribe Ubuntu Handoff

Date: 2026-04-03

This file is the continuation brief for the most recent Ubuntu Codex session that ran the project inside the real Ubuntu venv with the required speech/runtime libraries installed.

## 1. Current Repository State

The repository has been statically reviewed against `nudiscribe_build_plan.txt`.

Current conclusion:

- backend Phases 1 to 5 are implemented in code
- Phase 5 was runtime-validated on Ubuntu with a real speech provider
- Phase 6 now has a working SQLite-backed persistence foundation
- Phase 7 is not started
- the build plan includes a frontend, but this repository is backend-only

Important constraint:

- AI4Bharat Hindi/Kannada assets are still not configured in the current Ubuntu env
- the persistence layer is implemented for local development with SQLite, not PostgreSQL

## 2. What Was Completed In The Latest Pass

### Core backend consistency

- normalized several code files that had encoding artifacts
- aligned runtime configuration so the app can read either repo-root `.env` or `backend/.env`
- updated health/status reporting so TTS readiness is visible at runtime

### TTS hardening

- kept AI4Bharat Indic-TTS as the first provider in the routing stack
- preserved Piper and Coqui fallback providers
- kept tone fallback for environments where real TTS is unavailable
- added provider diagnostics for missing assets, binaries, and package issues
- added real-speech readiness tracking so tone fallback alone does not count as full TTS readiness
- normalized merged WAV output before combining per-segment audio

### Validation tooling

- added `backend/app/runtime_validation.py`
- added `backend/app/product_smoke_test.py`
- updated the README and handoff flow to use the smoke test
- added `BUILD_PLAN_ALIGNMENT.md` for a phase-by-phase build-plan snapshot

### Ubuntu validation and Phase 6 follow-up

- executed the full Ubuntu Phase 5 validation flow in the project venv
- wired the existing local Piper runtime into `backend/.env` so a real speech provider was available
- verified REST chat, REST TTS, text WebSocket, TTS WebSocket, upload transcription, and audio WebSocket flows
- identified that `backend/temp_audio_test.wav` is not a valid RIFF/WAV file and used a generated Piper WAV for the optional audio pass
- replaced the in-memory `MemoryStore` with a SQLite-backed persistence store
- started persisting session history, transcripts, selected language, latency, and errors

## 3. Files That Matter Most

Start with these files:

- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/api.py`
- `backend/app/orchestrator.py`
- `backend/app/runtime_validation.py`
- `backend/app/tts_router.py`
- `backend/app/product_smoke_test.py`
- `backend/app/asr/router.py`
- `backend/app/asr/segmenter.py`
- `backend/app/asr/whisper_asr.py`
- `backend/app/asr/indic_asr.py`
- `.env.example`
- `BUILD_PLAN_ALIGNMENT.md`

## 4. Build Plan Mapping

Use `BUILD_PLAN_ALIGNMENT.md` as the authoritative static mapping from code to plan.

Short version:

- Phase 1: backend side implemented
- Phase 2: implemented
- Phase 3: implemented
- Phase 4: implemented
- Phase 5: implemented and runtime-validated on Ubuntu
- Phase 6: started with SQLite-backed persistence
- Phase 7: pending

Out-of-repo scope:

- frontend text UI
- frontend transcript rendering
- frontend audio playback UI
- deployment artifacts

## 5. Expected Runtime Goal On Ubuntu

Ubuntu should verify that the current backend can do all of the following:

1. start successfully in the project venv
2. read the intended `.env`
3. reach Ollama
4. expose healthy REST and WebSocket endpoints
5. run chat end to end
6. run TTS end to end with a real speech provider
7. report degraded status if only fallback or missing runtime pieces are present
8. optionally validate transcription and audio WebSocket flow if a sample WAV is available

## 6. Ubuntu Validation Commands Executed And Results

Exact commands executed:

```bash
venv/bin/python backend/app/product_smoke_test.py --self-check --run-command-probes
venv/bin/python -m py_compile \
  backend/app/config.py \
  backend/app/main.py \
  backend/app/api.py \
  backend/app/orchestrator.py \
  backend/app/runtime_validation.py \
  backend/app/product_smoke_test.py \
  backend/app/tts_router.py \
  backend/app/asr/router.py \
  backend/app/asr/segmenter.py \
  backend/app/asr/whisper_asr.py \
  backend/app/asr/indic_asr.py
cd backend && ../venv/bin/uvicorn app.main:app --reload
venv/bin/python backend/app/product_smoke_test.py --base-url http://127.0.0.1:8000 --timeout 180
venv/bin/python backend/app/product_smoke_test.py --base-url http://127.0.0.1:8000 --audio-file /media/raviteja/Volume/nudiscribe/backend/temp_audio_test.wav --timeout 180
file /media/raviteja/Volume/nudiscribe/backend/temp_audio_test.wav /media/raviteja/Volume/nudiscribe/smoke_test_artifacts/tts_rest_output.wav
venv/bin/python backend/app/product_smoke_test.py --base-url http://127.0.0.1:8000 --audio-file /media/raviteja/Volume/nudiscribe/smoke_test_artifacts/tts_rest_output.wav --timeout 180
venv/bin/python -m py_compile backend/app/config.py backend/app/main.py backend/app/api.py backend/app/memory.py
venv/bin/python -m py_compile backend/app/api.py
venv/bin/python backend/app/product_smoke_test.py --base-url http://127.0.0.1:8000 --audio-file /media/raviteja/Volume/nudiscribe/smoke_test_artifacts/tts_rest_output.wav --timeout 180
```

What passed:

- static self-check passed once Piper was configured in `backend/.env`
- `py_compile` passed for the validated backend files
- `GET /`
- `GET /api/health`
- `POST /api/chat`
- `POST /api/tts` with real Piper WAV output
- `ws://.../ws/{session_id}`
- `ws://.../ws/tts/{session_id}` with `audio_chunk` and `final`
- `POST /api/transcribe` using a valid generated WAV sample
- `ws://.../ws/audio/{session_id}` using a valid generated WAV sample

What failed and was fixed:

- initial self-check failed because no real speech provider was configured
- fixed by binding the existing local Piper runtime in `backend/.env`:
  - `PIPER_BINARY=/tmp/nudiscribe_runtime/piper/piper/piper`
  - `PIPER_VOICE_EN=/tmp/nudiscribe_runtime/piper/voices/en_US-lessac-low.onnx`
- the bundled file `backend/temp_audio_test.wav` failed the optional audio checks because it is not a valid RIFF/WAV file
- fixed by switching the optional audio validation to `/media/raviteja/Volume/nudiscribe/smoke_test_artifacts/tts_rest_output.wav`, which was generated by the successful real-speech TTS pass
- after the Phase 6 persistence changes, the audio WebSocket still emitted noisy disconnect errors in server logs after `final`
- fixed by treating configured audio sessions as commit-driven and by handling disconnect-after-final as a normal client close

## 7. What “Done” Means For Phase 5

Phase 5 has now been validated on Ubuntu. The following checks were satisfied:

- `GET /api/health` returns usable readiness information
- `POST /api/chat` works end to end
- `POST /api/tts` returns synthesized WAV data
- `ws://.../ws/{session_id}` streams text successfully
- `ws://.../ws/tts/{session_id}` emits `audio_chunk` and `final`
- at least one real speech provider is available
- AI4Bharat is used first for Hindi/Kannada when its assets are configured
- merged audio output is valid after multi-segment synthesis

Optional but recommended:

- `POST /api/transcribe`
- `ws://.../ws/audio/{session_id}`

## 8. Likely Runtime Failure Points

Ubuntu should expect the following categories of issues if anything still fails:

- wrong `.env` file loaded
- missing or incorrect AI4Bharat model/config/vocoder paths
- `TTS` import works in one interpreter but not the configured `INDIC_TTS_PYTHON_BIN`
- Ollama reachable but configured model unavailable
- sample-rate or WAV-format mismatches from external TTS tools
- missing Piper binary or missing Piper voice files
- Coqui model names configured but the package or model download path is unavailable

## 9. What Is Still Not Done After Phase 5

These remain Phase 6 or later tasks:

- automated tests around the new SQLite persistence boundary
- decide whether to keep SQLite for local use only or add PostgreSQL/SQLAlchemy next
- automated test suite and CI execution
- Docker and deployment setup
- auth or access control
- observability and metrics
- frontend implementation

## 10. Recommended Next Step After Ubuntu Validation

The immediate next step after the successful Ubuntu validation is to continue Phase 6 with this order:

1. add tests around `backend/app/memory.py` and the API persistence hooks
2. inspect the generated SQLite data model and confirm it matches the desired product reporting needs
3. decide whether PostgreSQL/SQLAlchemy should replace or sit behind the current SQLite layer
4. expose persisted transcript or telemetry retrieval endpoints only if the product actually needs them

## 11. Guidance For The Next Codex Session

- trust `BUILD_PLAN_ALIGNMENT.md` for plan status
- trust `backend/app/product_smoke_test.py` for the current validation path
- trust `backend/app/memory.py` as the current Phase 6 persistence boundary
- do not remove the TTS readiness diagnostics
- do not treat tone fallback as a substitute for real TTS readiness
- keep the current API shapes unless a concrete runtime bug forces a change
