from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import existing_env_files, settings
from .logger import get_logger
from .memory import store
from .runtime_validation import collect_runtime_validation_report
from .tts_router import tts_router

log = get_logger("main")

app = FastAPI(
    title="NuDiscribe - Multilingual Healthcare Consultation Platform",
    description=(
        "Healthcare-focused multilingual speech recognition, live consultation support, "
        "structured report extraction, and voice response for Hindi, English, Kannada, "
        "and code-mixed speech."
    ),
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
async def startup_event():
    log.info("Server started")
    log.info(f"Model: {settings.ollama_model}")
    log.info(f"Ollama URL: {settings.ollama_base_url}")
    log.info(f"Persistence DB: {store.db_path}")
    log.info(f"Indic ASR: {'enabled' if settings.enable_indic_asr else 'disabled'}")
    log.info(f"Max context: {settings.max_context_messages} messages")
    log.info(f"TTS enabled: {'yes' if settings.enable_tts else 'no'}")
    log.info(f"TTS providers: {tts_router.available_providers()}")
    log.info(f"TTS real providers: {tts_router.available_real_speech_providers()}")
    log.info(f"Env files: {[str(path) for path in existing_env_files()]}")

    validation_report = collect_runtime_validation_report(run_command_probes=False)
    for issue in validation_report.issues:
        if issue.level == "error":
            log.error(issue.message)
        else:
            log.warning(issue.message)


@app.on_event("shutdown")
async def shutdown_event():
    store.close()


@app.get("/")
async def root():
    return {
        "service": "NuDiscribe",
        "version": "2.1.0",
        "status": "ok",
        "model": settings.ollama_model,
        "features": [
            "assistant-led-healthcare-consultation",
            "zero-shot-dynamic-json-extraction",
            "multilingual-and-code-mixed-asr",
            "whisper-and-indic-asr-routing",
            "dynamic-follow-up-questioning",
            "structured-healthcare-report-extraction",
            "editable-review-workflow",
            "report-upload-parsing",
            "longitudinal-session-history",
            "realtime-websocket-streaming",
            "websocket-audio-consultation",
            "ai4bharat-first-tts-routing",
            "multi-provider-tts-fallbacks",
            "websocket-tts",
            "runtime-validation",
        ],
    }
