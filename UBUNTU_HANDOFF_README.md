# NudiScribe Ubuntu Handoff

Date: 2026-04-03

This file is the continuation brief for the Ubuntu Codex session that will run the project inside the real Ubuntu venv with the required speech/runtime libraries installed.

## 1. Current Repository State

The repository has been statically reviewed against `nudiscribe_build_plan.txt`.

Current conclusion:

- backend Phases 1 to 5 are implemented in code
- Phase 5 is code-complete in-repo, but still needs real runtime verification on Ubuntu
- Phase 6 and Phase 7 are not started
- the build plan includes a frontend, but this repository is backend-only

Important constraint:

- this pass did not execute the backend, tests, or model runtimes
- Ubuntu must perform the actual runtime verification

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
- Phase 5: implemented in code, runtime verification pending
- Phase 6: pending
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

## 6. Required Ubuntu Actions

Do these in order.

### Step 1: Activate the real environment

- activate the Ubuntu venv used for this project
- work from the repository root unless a command explicitly says `backend/`

### Step 2: Check runtime configuration

- confirm whether you are using repo-root `.env` or `backend/.env`
- confirm `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_TIMEOUT`
- confirm all Hindi and Kannada AI4Bharat asset paths if real Indic-TTS is expected
- confirm Piper or Coqui fallback values if they are intentionally used

### Step 3: Run static validation inside Ubuntu

From repo root:

```bash
python backend/app/product_smoke_test.py --self-check --run-command-probes
```

This should confirm:

- visible env file paths
- required Python packages
- optional packages
- TTS provider diagnostics
- whether a real speech provider is actually available

### Step 4: Compile the backend files

From repo root:

```bash
python -m py_compile \
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
```

### Step 5: Start the backend

From `backend/`:

```bash
uvicorn app.main:app --reload
```

### Step 6: Run the live smoke test

From repo root:

```bash
python backend/app/product_smoke_test.py --base-url http://127.0.0.1:8000
```

This command intentionally treats tone fallback as a failure because full Phase 5 validation requires a real speech provider.

Optional audio/transcription check:

```bash
python backend/app/product_smoke_test.py \
  --base-url http://127.0.0.1:8000 \
  --audio-file /absolute/path/to/sample.wav
```

### Step 7: Inspect failures and patch only what is necessary

If the smoke test fails:

- inspect the exact failing endpoint or provider
- fix the smallest runtime issue first
- rerun self-check and live smoke test
- do not redesign APIs unless a concrete bug requires it
- only use `--allow-tone-fallback` for temporary debugging, not for the final Phase 5 sign-off

## 7. What “Done” Means For Phase 5

Phase 5 should be treated as fully validated only when Ubuntu confirms all of the following:

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

- persistent storage for sessions, transcripts, latency, and errors
- automated test suite and CI execution
- Docker and deployment setup
- auth or access control
- observability and metrics
- frontend implementation

## 10. Recommended Next Step After Ubuntu Validation

If Ubuntu verifies Phase 5 successfully, begin Phase 6 with this order:

1. choose persistence approach and schema
2. replace `MemoryStore` with a persistence-backed implementation
3. store session history and transcripts
4. store latency and error metadata
5. add tests around the persistence boundary

## 11. Guidance For The Next Codex Session

- trust `BUILD_PLAN_ALIGNMENT.md` for plan status
- trust `backend/app/product_smoke_test.py` for the current validation path
- do not remove the TTS readiness diagnostics
- do not treat tone fallback as a substitute for real TTS readiness
- keep the current API shapes unless a concrete runtime bug forces a change
