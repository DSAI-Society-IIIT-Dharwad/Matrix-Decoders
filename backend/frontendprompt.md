Build the first frontend for NudiScribe as a thin frontend over the existing backend. Use React + TypeScript +
  Vite for the JavaScript frontend layer. Do not create a second backend, do not redesign the API, and do not
  invent endpoints that do not exist.

  Context:
  - Existing backend stack: Python, FastAPI, WebSockets, Ollama, Whisper, Indic ASR routing, TTS routing, SQLite
  session persistence.
  - Existing backend already supports:
    - GET /api/health
    - POST /api/chat
    - POST /api/transcribe
    - POST /api/tts
    - GET /api/sessions
    - DELETE /api/session/{session_id}
    - WS /ws/{session_id}
    - WS /ws/audio/{session_id}
    - WS /ws/tts/{session_id}
  - Product goals from the problem statement: live and remote voice capture, multilingual/code-mixed
  conversations, dynamic two-way conversation, structured extraction, editable review, longitudinal history/
  dashboard, and domain-specific healthcare / financial-survey workflows.

  Critical implementation rules:
  - This must be a frontend-only build against the current FastAPI backend.
  - Use native fetch + native WebSocket.
  - For live microphone streaming, do not use MediaRecorder for the websocket audio path. The backend expects raw
  16-bit PCM binary frames (`pcm_s16le`), so use Web Audio API with an AudioWorklet or equivalent PCM pipeline.
  - Prefer 16 kHz, mono, 16-bit PCM, with chunks about every 250 ms, matching the existing audio test client
  behavior.
  - Preserve a stable session_id across text, audio, and TTS flows.
  - Handle degraded backend states cleanly, especially when TTS is disabled or only partially ready.
  - Do not fake unsupported backend features as if they are complete; isolate them behind mock adapters or clearly
  labeled placeholder modules.

  Design direction:
  - Create an intentional, voice-first interface for multilingual Indian-language operations.
  - Avoid generic purple SaaS styling.
  - Use a warm, operational visual system with strong hierarchy, clear recording state, transcript readability,
  and mobile support.
  - Show recording consent and capture state clearly.

  Build these product surfaces:
  1. Command Center
  - Show backend health from GET /api/health.
  - Show current model, uptime, active sessions, TTS readiness, warnings, and errors.
  - Include domain switcher: Healthcare, Financial/Survey.
  - Include session picker from GET /api/sessions, create-new-session action, and clear-session action via
  DELETE /api/session/{session_id}.

  2. Live Conversation Workspace
  - Text chat input and send action.
  - Live microphone capture panel.
  - Audio file upload panel for transcription.
  - Streaming transcript panel with language badges, code-mixed indicator, segment metadata, and timestamps when
  available.
  - Streaming assistant response panel.
  - TTS playback/download controls for synthesized output.
  - Explicit states: idle, recording, buffering, transcribing, generating, speaking, error.

  3. Editable Structured Review
  - Build a review panel that converts current transcript + assistant output into editable structured fields.
  - Because structured extraction endpoints do not exist yet, implement this as a typed client-side adapter with
  mock extraction logic and a clean boundary for future backend integration.
  - Generic fields:
    - complaint/query
    - background history
    - observations/responses
    - diagnosis/classification/status
    - action plan/treatment plan
    - verification/survey responses
  - Healthcare fields:
    - symptoms
    - past history
    - clinical observations
    - diagnosis
    - treatment advice
    - immunization data
    - pregnancy data
    - risk indicators
    - injury and mobility details
    - ENT findings
  - Financial/survey fields:
    - identity verification
    - account/loan confirmation
    - payment status
    - payer identity
    - payment date
    - payment mode
    - executive interaction details
    - reason for payment
    - amount paid

  4. Longitudinal History / Dashboard
  - Show searchable session list and summary cards.
  - Use real session IDs from GET /api/sessions.
  - Since the backend does not yet expose transcript/history retrieval endpoints, build the dashboard with a data
  adapter that can use local/mock detail records for now without pretending the backend already supports full
  analytics.
  - Keep the layout ready for analytics-ready records and future search/reporting APIs.

  5. Outbound Workflow Placeholder
  - Add a clearly labeled future-facing page/shell for outbound voice workflows and configurable scripts.
  - Do not invent telephony integrations; keep it as a placeholder UX module.

  Exact backend contract to support:
  - POST /api/chat with { session_id, text }.
  - POST /api/transcribe with audio file upload.
  - POST /api/tts with { text, language?, languages? } and decode/play returned audio_b64 WAV.
  - WS /ws/{session_id}: send { "type": "input", "text": "..." } and handle language_info, delta, final, error.
  - WS /ws/audio/{session_id}: first send { "type": "start", "sample_rate": 16000, "channels": 1, "sample_width":
  2, "encoding": "pcm_s16le" }, then stream binary PCM frames, then send "commit". Handle audio_config,
  transcription, language_info, delta, final, audio_skipped, error, pong, audio_reset.
  - WS /ws/tts/{session_id}: send { "type": "synthesize", "text": "...", "language": "...", "languages":
  ["en","hi","kn"], "segments": [...] } and handle tts_info, audio_chunk, final, error.

  Engineering expectations:
  - Deliver real code, not pseudocode.
  - Organize with typed API clients, websocket services, reusable hooks, domain schemas, and clean component
  boundaries.
  - Include robust error handling, reconnection behavior, and empty/degraded states.
  - Make the app responsive on desktop and mobile.
  - Output the full frontend scaffold and the key implementation files.

  If you want, I can turn this into a repo-specific implementation plan or scaffold the frontend directly in this
  workspace.