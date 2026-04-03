from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import existing_env_files, settings
from .logger import get_logger
from .runtime_validation import collect_runtime_validation_report
from .tts_router import tts_router

log = get_logger("main")

app = FastAPI(
    title="NuDiscribe - Multilingual Speech Orchestrator",
    description=(
        "Code-mixed speech recognition and conversational AI "
        "for Hindi, English, and Kannada."
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


@app.get("/")
async def root():
    return {
        "service": "NuDiscribe",
        "version": "2.1.0",
        "status": "ok",
        "model": settings.ollama_model,
        "features": [
            "code-mixed-speech",
            "hindi-english",
            "kannada-english",
            "streaming-llm",
            "websocket-audio",
            "tts-routing",
            "websocket-tts",
            "runtime-validation",
        ],
    }
