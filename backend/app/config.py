from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
ENV_FILE_CANDIDATES = (
    BACKEND_ROOT / ".env",
    REPO_ROOT / ".env",
)


def existing_env_files() -> list[Path]:
    """Return the configured env files that currently exist on disk."""
    return [path for path in ENV_FILE_CANDIDATES if path.exists()]


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"
    ollama_timeout: int = 120
    max_context_messages: int = 10
    default_response_language: str = "auto"

    # ASR settings
    whisper_model_size: str = "base"
    enable_indic_asr: bool = True

    # TTS settings
    enable_tts: bool = True
    enable_tts_fallback_tone: bool = True
    tts_sample_rate: int = 22050
    indic_tts_python_bin: str = "python"
    indic_tts_command_template: str = ""
    indic_tts_model_hi: str = ""
    indic_tts_config_hi: str = ""
    indic_tts_vocoder_hi: str = ""
    indic_tts_vocoder_config_hi: str = ""
    indic_tts_model_kn: str = ""
    indic_tts_config_kn: str = ""
    indic_tts_vocoder_kn: str = ""
    indic_tts_vocoder_config_kn: str = ""
    piper_binary: str = ""
    piper_voice_en: str = ""
    piper_voice_hi: str = ""
    piper_voice_kn: str = ""
    coqui_model_en: str = ""
    coqui_model_hi: str = ""
    coqui_model_kn: str = ""
    coqui_speaker: str = ""

    model_config = SettingsConfigDict(
        env_file=tuple(str(path) for path in ENV_FILE_CANDIDATES),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
