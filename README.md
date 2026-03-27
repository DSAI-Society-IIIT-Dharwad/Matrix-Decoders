# NuDiscribe

NuDiscribe is a multilingual conversational backend for speech-first interactions across English, Hindi, and Kannada. It is designed to handle both typed input and spoken input, including code-mixed usage where users switch between languages within the same utterance.

The current repository contains the backend service layer that performs:

- audio transcription
- language and script detection
- code-mixed input handling
- session-aware conversational orchestration
- streaming LLM responses through Ollama

## Project Goal

The long-term goal of NuDiscribe is to provide a robust multilingual speech orchestration platform for Indian language usage patterns, especially mixed-language conversations that are poorly handled by conventional monolingual assistants.

The system is intended to support:

- English-only conversations
- Hindi-English code-mixed conversations
- Kannada-English code-mixed conversations
- script-based and Romanized input
- speech-to-text to LLM conversational flows
- future text-to-speech and more production-grade deployment patterns

## Current Scope

This repository currently contains a FastAPI backend prototype. It exposes REST and WebSocket APIs for text chat, transcription, and speech-driven conversational workflows.

Core modules in the current implementation:

- `backend/app/main.py`: FastAPI application setup and service metadata
- `backend/app/api.py`: REST and WebSocket endpoints
- `backend/app/orchestrator.py`: end-to-end request orchestration
- `backend/app/asr/`: ASR routing and model adapters
- `backend/app/language.py`: script and language heuristics
- `backend/app/ollama_client.py`: Ollama streaming client
- `backend/app/memory.py`: in-memory session tracking
- `backend/app/prompt.py`: language-aware prompting strategy

## Implemented Features

- FastAPI backend service with CORS enabled
- `GET /api/health` for service health and model availability
- `POST /api/chat` for text-based multilingual chat
- `POST /api/transcribe` for uploaded audio transcription
- `DELETE /api/session/{session_id}` to clear session memory
- `GET /api/sessions` to inspect active in-memory sessions
- `WebSocket /ws/{session_id}` for streaming text chat
- `WebSocket /ws/audio/{session_id}` for streaming audio input
- Whisper-based transcription path for English and general fallback
- Indic ASR integration for Hindi and Kannada
- heuristic merging of Whisper and Indic ASR outputs
- detection of Devanagari, Kannada, English, and some Romanized Hindi/Kannada patterns
- language-aware prompting so the assistant mirrors the user’s language style
- in-memory conversation history with bounded context window
- example client scripts for manual text and audio testing

## Current Status

NuDiscribe is currently at an early backend MVP or prototype stage.

What is already in place:

- the backend architecture is implemented end-to-end
- the main API surface is usable
- the multilingual and code-mixed handling logic is present
- the service is structured clearly enough for further iteration
- the source code has been organized into focused modules

What is not yet complete:

- no frontend application is included
- no persistent database or durable session storage is implemented
- no authentication or access control exists
- no automated test suite is present
- no containerization or deployment configuration is included
- no production observability stack exists
- text-to-speech is not yet implemented, only a sentence-level `tts_plan`
- multilingual quality is heuristic-driven and still needs evaluation against real usage data

In practical terms, this repository should be viewed as a functional backend prototype, not a production-ready application.

## Architecture Overview

### 1. Input Layer

The backend accepts either:

- direct text input through REST or WebSocket
- audio input through file upload or audio WebSocket streaming

### 2. ASR Layer

The ASR pipeline currently uses:

- OpenAI Whisper for broad transcription coverage
- Indic ASR for Hindi and Kannada-specific transcription support

The router compares and merges outputs to improve performance on code-mixed speech.

### 3. Language Analysis Layer

The backend detects:

- Devanagari script
- Kannada script
- Latin script
- selected Romanized Hindi and Kannada patterns

This allows the system to infer likely language combinations and dominant language for response shaping.

### 4. Orchestration Layer

The orchestrator:

- tracks conversation state by session
- builds language-aware prompts
- sends the conversation to Ollama
- streams the LLM output back to the client
- prepares sentence chunks for future TTS integration

### 5. LLM Layer

The current implementation expects a locally available Ollama instance and uses the configured model for response generation.

## Technology Stack

- Python
- FastAPI
- Uvicorn
- Pydantic
- HTTPX
- WebSockets
- OpenAI Whisper
- PyTorch
- Torchaudio
- Hugging Face Transformers
- Ollama

## Local Development

### Requirements

- Python 3.12 recommended
- Ollama running locally
- a supported Ollama model available locally
- sufficient system resources for Whisper and Indic ASR models

### Environment

The backend uses environment variables for configuration. Typical values include:

- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `OLLAMA_TIMEOUT`

Example values currently used during development:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral
OLLAMA_TIMEOUT=120
```

### Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### Run the Server

```bash
uvicorn app.main:app --reload
```

The default local server endpoint is typically:

```text
http://127.0.0.1:8000
```

## API Summary

### REST Endpoints

- `GET /`
- `GET /api/health`
- `POST /api/chat`
- `POST /api/transcribe`
- `GET /api/sessions`
- `DELETE /api/session/{session_id}`

### WebSocket Endpoints

- `ws://localhost:8000/ws/{session_id}`
- `ws://localhost:8000/ws/audio/{session_id}`

## Known Limitations

- session memory is stored only in process memory
- multilingual detection is heuristic-based, not model-evaluated
- no benchmark data is included for transcription quality
- audio pipeline behavior is still prototype-grade and needs protocol hardening
- failure handling is present, but recovery behavior is still basic
- no formal versioning or release process has been established
- repository documentation is still being built out

## Planned Future Work

The next phase of development should focus on moving from prototype to reliable product foundation.

### Near-Term Priorities

- add a proper `.env.example`
- add a test suite for API, orchestration, and language detection logic
- add a `README` setup verification flow
- clean up encoding issues in source strings and comments
- add structured logging and stronger error reporting
- refine the audio WebSocket protocol and client examples

### Product and Platform Work

- build a frontend interface for chat and voice interaction
- add persistent session storage
- add user authentication and authorization
- introduce configuration profiles for local, staging, and production
- containerize the backend with Docker
- add deployment automation and CI
- add metrics, health probes, and observability

### ML and Speech Roadmap

- improve code-mixed transcription quality evaluation
- support additional Indian languages
- add better language confidence scoring
- support real text-to-speech output
- explore streaming ASR improvements and lower-latency audio handling
- tune prompts and model behavior for multilingual conversational consistency

## Repository Status Summary

This repository currently represents:

- a meaningful backend implementation
- a clear proof of concept for multilingual and code-mixed speech handling
- a strong foundation for productization
- a non-production prototype that still needs testing, documentation depth, deployment setup, and quality hardening

## License

No license has been added yet. If this project is intended for collaboration or public reuse, a license should be added explicitly.
