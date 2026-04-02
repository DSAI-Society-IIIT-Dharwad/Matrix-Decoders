from pydantic_settings import BaseSettings


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
    indic_tts_command_template: str = ""
    indic_tts_voice_hi: str = ""
    indic_tts_voice_kn: str = ""
    piper_binary: str = ""
    piper_voice_en: str = ""
    piper_voice_hi: str = ""
    piper_voice_kn: str = ""
    coqui_model_en: str = ""
    coqui_model_hi: str = ""
    coqui_model_kn: str = ""
    coqui_speaker: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
