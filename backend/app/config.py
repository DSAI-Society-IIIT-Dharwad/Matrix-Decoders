from pathlib import Path

from pydantic import field_validator
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
    persistence_db_path: str = str(BACKEND_ROOT / "data" / "nudiscribe.db")

    # ASR settings
    whisper_model_size: str = "base"
    enable_indic_asr: bool = True
    asr_archive_audio_for_training: bool = False
    asr_corpus_dir: str = str(BACKEND_ROOT / "data" / "asr_corpus")
    asr_archive_dir: str = str(BACKEND_ROOT / "data" / "asr_corpus" / "local_archive")
    asr_checkpoint_dir: str = str(BACKEND_ROOT / "data" / "asr_checkpoints")
    asr_base_model: str = "openai/whisper-small"
    asr_runtime_prefer_finetuned: bool = True
    asr_hf_token: str = ""
    asr_target_hours_per_bucket: float = 40.0
    asr_target_code_mixed_hours: float = 20.0
    asr_local_archive_hours_per_bucket: float = 5.0
    asr_eval_ratio: float = 0.1
    asr_max_clip_seconds: float = 30.0
    asr_train_epochs: float = 3.0
    asr_train_learning_rate: float = 1e-5
    asr_train_batch_size: int = 4
    asr_eval_batch_size: int = 4
    asr_gradient_accumulation_steps: int = 4
    asr_logging_steps: int = 25
    asr_save_steps: int = 500
    asr_eval_steps: int = 500
    asr_warmup_steps: int = 250

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

    @field_validator(
        "persistence_db_path",
        "asr_corpus_dir",
        "asr_archive_dir",
        "asr_checkpoint_dir",
        mode="before",
    )
    @classmethod
    def _resolve_persistence_db_path(cls, value):
        """Resolve relative database paths against the repository root."""
        if value in {None, ""}:
            return value

        path = Path(str(value)).expanduser()
        if path.is_absolute():
            return str(path)

        return str((REPO_ROOT / path).resolve())


settings = Settings()
