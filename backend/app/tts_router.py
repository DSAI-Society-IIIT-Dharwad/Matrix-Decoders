import asyncio
import base64
import io
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from typing import Optional

from .config import settings
from .logger import get_logger
from .response_policy import choose_response_language

log = get_logger("tts")


@dataclass
class TTSResult:
    text: str
    language: str
    provider: str
    audio_bytes: bytes
    mime_type: str = "audio/wav"
    sample_rate: int = 22050

    @property
    def audio_b64(self) -> str:
        return base64.b64encode(self.audio_bytes).decode("ascii")


@dataclass
class TTSSegmentResult:
    index: int
    text: str
    language: str
    provider: str
    audio_bytes: bytes
    mime_type: str = "audio/wav"
    sample_rate: int = 22050
    duration_ms: Optional[int] = None

    @property
    def audio_b64(self) -> str:
        return base64.b64encode(self.audio_bytes).decode("ascii")


@dataclass
class TTSBatchResult:
    text: str
    language: str
    provider: str
    audio_bytes: bytes
    segments: list[TTSSegmentResult]
    mime_type: str = "audio/wav"
    sample_rate: int = 22050

    @property
    def audio_b64(self) -> str:
        return base64.b64encode(self.audio_bytes).decode("ascii")


@dataclass
class TTSSegmentInput:
    text: str
    language: Optional[str] = None
    languages: Optional[list[str]] = None


class BaseTTSProvider:
    name = "base"

    def is_available(self) -> bool:
        return False

    def synthesize(self, text: str, language: str) -> TTSResult:
        raise NotImplementedError


class PiperTTSProvider(BaseTTSProvider):
    name = "piper"

    def __init__(self):
        self._binary = settings.piper_binary or shutil.which("piper")

    def is_available(self) -> bool:
        return bool(self._binary and _voice_path_for_language("piper", "en"))

    def synthesize(self, text: str, language: str) -> TTSResult:
        if not self._binary:
            raise RuntimeError("Piper binary not configured.")

        voice_path = _voice_path_for_language("piper", language)
        if not voice_path:
            raise RuntimeError(f"No Piper voice configured for language '{language}'.")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
            output_path = output_file.name

        try:
            proc = subprocess.run(
                [self._binary, "--model", voice_path, "--output_file", output_path],
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore").strip() or "Piper synthesis failed.")

            with open(output_path, "rb") as f:
                audio_bytes = f.read()

            return TTSResult(
                text=text,
                language=language,
                provider=self.name,
                audio_bytes=audio_bytes,
                sample_rate=settings.tts_sample_rate,
            )
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)


class CoquiTTSProvider(BaseTTSProvider):
    name = "coqui"

    def __init__(self):
        self._tts = None

    def _load(self):
        if self._tts is not None:
            return self._tts

        try:
            from TTS.api import TTS  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(f"Coqui TTS is not installed: {exc}") from exc

        model_name = _voice_path_for_language("coqui", "en")
        if not model_name:
            raise RuntimeError("Coqui model name not configured.")

        self._tts = TTS(model_name=model_name)
        return self._tts

    def is_available(self) -> bool:
        try:
            self._load()
            return True
        except Exception:
            return False

    def synthesize(self, text: str, language: str) -> TTSResult:
        tts = self._load()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
            output_path = output_file.name

        try:
            kwargs = {}
            speaker = settings.coqui_speaker
            if speaker:
                kwargs["speaker"] = speaker

            tts.tts_to_file(text=text, file_path=output_path, **kwargs)
            with open(output_path, "rb") as f:
                audio_bytes = f.read()

            return TTSResult(
                text=text,
                language=language,
                provider=self.name,
                audio_bytes=audio_bytes,
                sample_rate=settings.tts_sample_rate,
            )
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)


class ToneFallbackProvider(BaseTTSProvider):
    name = "tone-fallback"

    def is_available(self) -> bool:
        return settings.enable_tts_fallback_tone

    def synthesize(self, text: str, language: str) -> TTSResult:
        duration_seconds = max(0.35, min(2.5, 0.055 * max(len(text.split()), 1)))
        sample_rate = settings.tts_sample_rate
        tone_hz = {"en": 440.0, "hi": 493.88, "kn": 523.25}.get(language, 440.0)
        amplitude = 0.15

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)

            total_samples = int(duration_seconds * sample_rate)
            frames = bytearray()
            for i in range(total_samples):
                sample = amplitude * math.sin(2.0 * math.pi * tone_hz * (i / sample_rate))
                frames.extend(struct.pack("<h", int(sample * 32767)))
            wav_file.writeframes(bytes(frames))

        return TTSResult(
            text=text,
            language=language,
            provider=self.name,
            audio_bytes=buffer.getvalue(),
            sample_rate=sample_rate,
        )


def _voice_path_for_language(provider: str, language: str) -> Optional[str]:
    if provider == "piper":
        mapping = {
            "en": settings.piper_voice_en,
            "hi": settings.piper_voice_hi,
            "kn": settings.piper_voice_kn,
        }
    else:
        mapping = {
            "en": settings.coqui_model_en,
            "hi": settings.coqui_model_hi,
            "kn": settings.coqui_model_kn,
        }

    value = mapping.get(language) or mapping.get("en")
    return value or None


class TTSRouter:
    """Route text to the best available TTS provider."""

    def __init__(self):
        self.providers = [
            PiperTTSProvider(),
            CoquiTTSProvider(),
            ToneFallbackProvider(),
        ]

    def available_providers(self) -> list[str]:
        return [provider.name for provider in self.providers if provider.is_available()]

    def choose_language(self, text: str, languages: Optional[list[str]] = None, preferred_language: Optional[str] = None) -> str:
        return choose_response_language(text, languages, preferred_language)

    async def synthesize(
        self,
        text: str,
        languages: Optional[list[str]] = None,
        preferred_language: Optional[str] = None,
    ) -> TTSResult:
        if not settings.enable_tts:
            raise RuntimeError("TTS is disabled by configuration.")

        cleaned_text = text.strip()
        if not cleaned_text:
            raise ValueError("TTS input text is empty.")

        language = self.choose_language(cleaned_text, languages, preferred_language)
        loop = asyncio.get_running_loop()

        last_error = None
        for provider in self.providers:
            if not provider.is_available():
                continue

            try:
                result = await loop.run_in_executor(None, provider.synthesize, cleaned_text, language)
                log.info(f"TTS synthesized with {provider.name} for language={language}")
                return result
            except Exception as exc:
                last_error = exc
                log.warning(f"TTS provider {provider.name} failed: {exc}")

        raise RuntimeError(f"No TTS provider available for language '{language}': {last_error}")

    async def synthesize_segments(
        self,
        segments: list[TTSSegmentInput],
        languages: Optional[list[str]] = None,
        preferred_language: Optional[str] = None,
    ) -> TTSBatchResult:
        cleaned_segments = [segment for segment in segments if segment.text.strip()]
        if not cleaned_segments:
            raise ValueError("TTS segment list is empty.")

        results: list[TTSSegmentResult] = []
        merged_provider_names: list[str] = []

        for index, segment in enumerate(cleaned_segments, start=1):
            result = await self.synthesize(
                segment.text.strip(),
                languages=segment.languages or languages,
                preferred_language=segment.language or preferred_language,
            )
            duration_ms = _wav_duration_ms(result.audio_bytes)
            results.append(
                TTSSegmentResult(
                    index=index,
                    text=result.text,
                    language=result.language,
                    provider=result.provider,
                    audio_bytes=result.audio_bytes,
                    mime_type=result.mime_type,
                    sample_rate=result.sample_rate,
                    duration_ms=duration_ms,
                )
            )
            merged_provider_names.append(result.provider)

        merged_audio = _merge_wav_segments([result.audio_bytes for result in results])
        language = self.choose_language(
            " ".join(segment.text.strip() for segment in cleaned_segments),
            languages,
            preferred_language,
        )
        provider = "+".join(dict.fromkeys(merged_provider_names))

        return TTSBatchResult(
            text=" ".join(segment.text.strip() for segment in cleaned_segments),
            language=language,
            provider=provider,
            audio_bytes=merged_audio,
            segments=results,
            sample_rate=results[0].sample_rate if results else settings.tts_sample_rate,
        )


tts_router = TTSRouter()


def _wav_duration_ms(audio_bytes: bytes) -> Optional[int]:
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            if frame_rate <= 0:
                return None
            return int((frame_count / frame_rate) * 1000)
    except Exception:
        return None


def _merge_wav_segments(segments: list[bytes]) -> bytes:
    if not segments:
        raise ValueError("No audio segments to merge.")

    merged_frames = bytearray()
    sample_rate = None
    channels = None
    sample_width = None

    for audio_bytes in segments:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            current_sample_rate = wav_file.getframerate()
            current_channels = wav_file.getnchannels()
            current_sample_width = wav_file.getsampwidth()

            if sample_rate is None:
                sample_rate = current_sample_rate
                channels = current_channels
                sample_width = current_sample_width
            elif (
                current_sample_rate != sample_rate
                or current_channels != channels
                or current_sample_width != sample_width
            ):
                raise ValueError("Cannot merge WAV segments with mismatched audio formats.")

            merged_frames.extend(wav_file.readframes(wav_file.getnframes()))

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels or 1)
        wav_file.setsampwidth(sample_width or 2)
        wav_file.setframerate(sample_rate or settings.tts_sample_rate)
        wav_file.writeframes(bytes(merged_frames))

    return buffer.getvalue()

