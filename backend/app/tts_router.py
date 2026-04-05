from __future__ import annotations

import asyncio
import audioop
import base64
import importlib.util
import io
import math
import os
import shlex
import shutil
import struct
import subprocess
import tempfile
import wave
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .config import settings
from .language import segment_text_by_language
from .logger import get_logger
from .response_policy import choose_response_language

log = get_logger("tts")

SUPPORTED_TTS_LANGUAGES = ("en", "hi", "kn")


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


@dataclass
class TTSProviderDiagnostic:
    name: str
    priority: int
    available: bool
    supported_languages: list[str]
    configured_languages: list[str]
    issues: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)


class BaseTTSProvider:
    name = "base"

    def is_available(self) -> bool:
        return False

    def supported_languages(self) -> list[str]:
        return list(SUPPORTED_TTS_LANGUAGES)

    def configured_languages(self) -> list[str]:
        return []

    def supports_language(self, language: str) -> bool:
        return language in self.configured_languages()

    def diagnostics(self, priority: int) -> TTSProviderDiagnostic:
        return TTSProviderDiagnostic(
            name=self.name,
            priority=priority,
            available=self.is_available(),
            supported_languages=self.supported_languages(),
            configured_languages=self.configured_languages(),
        )

    def synthesize(self, text: str, language: str) -> TTSResult:
        raise NotImplementedError


class IndicTTSProvider(BaseTTSProvider):
    name = "ai4bharat-indic"

    def __init__(self):
        self._command_template = settings.indic_tts_command_template.strip()

    def supported_languages(self) -> list[str]:
        return ["hi", "kn"]

    def configured_languages(self) -> list[str]:
        languages: list[str] = []
        for language in self.supported_languages():
            if self._language_requested(language) and not self._language_issues(language):
                languages.append(language)
        return languages

    def is_available(self) -> bool:
        return bool(self.configured_languages())

    def supports_language(self, language: str) -> bool:
        return language in self.configured_languages()

    def diagnostics(self, priority: int) -> TTSProviderDiagnostic:
        issues: list[str] = []
        for language in self.supported_languages():
            issues.extend(self._language_issues(language))

        return TTSProviderDiagnostic(
            name=self.name,
            priority=priority,
            available=self.is_available(),
            supported_languages=self.supported_languages(),
            configured_languages=self.configured_languages(),
            issues=issues,
            details={
                "python_bin": settings.indic_tts_python_bin or "python",
                "command_template": self._command_template or "<default>",
            },
        )

    def synthesize(self, text: str, language: str) -> TTSResult:
        if not self.supports_language(language):
            raise RuntimeError(
                f"AI4Bharat Indic-TTS assets are not fully configured for language '{language}'."
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
            output_path = output_file.name

        try:
            command = self._build_command(text, language, output_path)
            proc = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    proc.stderr.decode("utf-8", errors="ignore").strip()
                    or "AI4Bharat Indic-TTS synthesis failed."
                )

            with open(output_path, "rb") as handle:
                audio_bytes = handle.read()

            return TTSResult(
                text=text,
                language=language,
                provider=self.name,
                audio_bytes=audio_bytes,
                sample_rate=_wav_sample_rate(audio_bytes) or settings.tts_sample_rate,
            )
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def _build_command(self, text: str, language: str, output_path: str) -> list[str]:
        assets = _indic_tts_assets(language)
        if self._command_template:
            rendered = self._command_template.format(
                language=language,
                model_path=assets["model_path"],
                config_path=assets["config_path"],
                vocoder_path=assets["vocoder_path"],
                vocoder_config_path=assets["vocoder_config_path"],
                output_path=output_path,
            )
            return shlex.split(rendered, posix=False)

        return [
            settings.indic_tts_python_bin or "python",
            "-m",
            "TTS.bin.synthesize",
            "--text",
            text,
            "--model_path",
            assets["model_path"],
            "--config_path",
            assets["config_path"],
            "--vocoder_path",
            assets["vocoder_path"],
            "--vocoder_config_path",
            assets["vocoder_config_path"],
            "--out_path",
            output_path,
        ]

    def _language_issues(self, language: str) -> list[str]:
        asset_map = _indic_tts_asset_map(language)
        if not asset_map or not self._language_requested(language):
            return []

        assets = {asset_key: value for asset_key, (_, value) in asset_map.items()}
        missing_keys = [env_name for _, (env_name, value) in asset_map.items() if not value]
        missing_paths = [
            str(Path(value))
            for value in assets.values()
            if value and not Path(value).expanduser().exists()
        ]

        issues: list[str] = []
        if missing_keys:
            issues.append(
                f"{language}: missing env values for {', '.join(sorted(missing_keys))}"
            )
        if missing_paths:
            issues.append(
                f"{language}: missing asset files at {', '.join(missing_paths)}"
            )
        return issues

    def _language_requested(self, language: str) -> bool:
        asset_map = _indic_tts_asset_map(language)
        return any(value.strip() for _, value in asset_map.values())


class PiperTTSProvider(BaseTTSProvider):
    name = "piper"

    def __init__(self):
        self._configured_binary = settings.piper_binary.strip()

    def configured_languages(self) -> list[str]:
        languages: list[str] = []
        for language in SUPPORTED_TTS_LANGUAGES:
            voice_path = _voice_path_for_language("piper", language)
            if voice_path and Path(voice_path).expanduser().exists():
                languages.append(language)
        return languages

    def is_available(self) -> bool:
        return bool(self._binary_path() and self.configured_languages())

    def supports_language(self, language: str) -> bool:
        return bool(
            self._binary_path()
            and language in self.configured_languages()
            and _voice_path_for_language("piper", language)
        )

    def diagnostics(self, priority: int) -> TTSProviderDiagnostic:
        issues: list[str] = []
        if self._configured_binary and not self._binary_path():
            issues.append(f"Piper binary does not exist at {self._configured_binary}")
        elif self._provider_requested() and not self._binary_path():
            issues.append("Piper binary is not configured and was not found on PATH.")

        for language, voice_path in _explicit_voice_settings("piper").items():
            if voice_path and not Path(voice_path).expanduser().exists():
                issues.append(f"{language}: Piper voice file does not exist at {voice_path}")

        return TTSProviderDiagnostic(
            name=self.name,
            priority=priority,
            available=self.is_available(),
            supported_languages=list(SUPPORTED_TTS_LANGUAGES),
            configured_languages=self.configured_languages(),
            issues=issues,
            details={"binary": self._binary_path() or self._configured_binary or "<missing>"},
        )

    def synthesize(self, text: str, language: str) -> TTSResult:
        binary = self._binary_path()
        if not binary:
            raise RuntimeError("Piper binary not configured.")

        voice_path = _voice_path_for_language("piper", language)
        if not voice_path:
            raise RuntimeError(f"No Piper voice configured for language '{language}'.")
        if not Path(voice_path).expanduser().exists():
            raise RuntimeError(f"Piper voice file does not exist: {voice_path}")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
            output_path = output_file.name

        try:
            proc = subprocess.run(
                [binary, "--model", voice_path, "--output_file", output_path],
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    proc.stderr.decode("utf-8", errors="ignore").strip()
                    or "Piper synthesis failed."
                )

            with open(output_path, "rb") as handle:
                audio_bytes = handle.read()

            return TTSResult(
                text=text,
                language=language,
                provider=self.name,
                audio_bytes=audio_bytes,
                sample_rate=_wav_sample_rate(audio_bytes) or settings.tts_sample_rate,
            )
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def _binary_path(self) -> Optional[str]:
        return _resolve_command_path(self._configured_binary or "piper")

    def _provider_requested(self) -> bool:
        if self._configured_binary:
            return True
        return any(path.strip() for path in _explicit_voice_settings("piper").values())


class CoquiTTSProvider(BaseTTSProvider):
    name = "coqui"

    def __init__(self):
        self._tts_models: dict[str, object] = {}

    def configured_languages(self) -> list[str]:
        languages: list[str] = []
        for language in SUPPORTED_TTS_LANGUAGES:
            if _voice_path_for_language("coqui", language):
                languages.append(language)
        return languages

    def is_available(self) -> bool:
        return _coqui_package_available() and bool(self.configured_languages())

    def supports_language(self, language: str) -> bool:
        return _coqui_package_available() and language in self.configured_languages()

    def diagnostics(self, priority: int) -> TTSProviderDiagnostic:
        issues: list[str] = []
        if self.configured_languages() and not _coqui_package_available():
            issues.append(
                "Coqui model names are configured, but TTS.api could not be imported: "
                f"{_coqui_import_error()}"
            )

        return TTSProviderDiagnostic(
            name=self.name,
            priority=priority,
            available=self.is_available(),
            supported_languages=list(SUPPORTED_TTS_LANGUAGES),
            configured_languages=self.configured_languages(),
            issues=issues,
        )

    def _load(self, language: str):
        model_name = _voice_path_for_language("coqui", language)
        if not model_name:
            raise RuntimeError(f"No Coqui model configured for language '{language}'.")

        if model_name in self._tts_models:
            return self._tts_models[model_name]

        try:
            from TTS.api import TTS  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"Coqui TTS is not installed: {exc}") from exc

        self._tts_models[model_name] = TTS(model_name=model_name)
        return self._tts_models[model_name]

    def synthesize(self, text: str, language: str) -> TTSResult:
        tts = self._load(language)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
            output_path = output_file.name

        try:
            kwargs = {}
            speaker = settings.coqui_speaker
            if speaker:
                kwargs["speaker"] = speaker

            tts.tts_to_file(text=text, file_path=output_path, **kwargs)
            with open(output_path, "rb") as handle:
                audio_bytes = handle.read()

            return TTSResult(
                text=text,
                language=language,
                provider=self.name,
                audio_bytes=audio_bytes,
                sample_rate=_wav_sample_rate(audio_bytes) or settings.tts_sample_rate,
            )
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)


class ToneFallbackProvider(BaseTTSProvider):
    name = "tone-fallback"

    def configured_languages(self) -> list[str]:
        if settings.enable_tts_fallback_tone:
            return list(SUPPORTED_TTS_LANGUAGES)
        return []

    def is_available(self) -> bool:
        return settings.enable_tts_fallback_tone

    def supports_language(self, language: str) -> bool:
        return self.is_available() and language in SUPPORTED_TTS_LANGUAGES

    def diagnostics(self, priority: int) -> TTSProviderDiagnostic:
        issues = []
        if not settings.enable_tts_fallback_tone:
            issues.append("Tone fallback is disabled.")

        return TTSProviderDiagnostic(
            name=self.name,
            priority=priority,
            available=self.is_available(),
            supported_languages=list(SUPPORTED_TTS_LANGUAGES),
            configured_languages=self.configured_languages(),
            issues=issues,
        )

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
            for index in range(total_samples):
                sample = amplitude * math.sin(2.0 * math.pi * tone_hz * (index / sample_rate))
                frames.extend(struct.pack("<h", int(sample * 32767)))
            wav_file.writeframes(bytes(frames))

        return TTSResult(
            text=text,
            language=language,
            provider=self.name,
            audio_bytes=buffer.getvalue(),
            sample_rate=sample_rate,
        )


def _coqui_package_available() -> bool:
    return _coqui_import_error() is None


@lru_cache(maxsize=1)
def _coqui_import_error() -> Optional[str]:
    if importlib.util.find_spec("TTS") is None:
        return "TTS is not installed."

    try:
        from TTS.api import TTS  # type: ignore  # noqa: F401
    except Exception as exc:
        return str(exc)

    return None


def _indic_tts_assets(language: str) -> dict[str, str]:
    asset_map = _indic_tts_asset_map(language)
    return {asset_key: value for asset_key, (_, value) in asset_map.items()}


def _indic_tts_asset_map(language: str) -> dict[str, tuple[str, str]]:
    if language == "hi":
        return {
            "model_path": ("INDIC_TTS_MODEL_HI", settings.indic_tts_model_hi),
            "config_path": ("INDIC_TTS_CONFIG_HI", settings.indic_tts_config_hi),
            "vocoder_path": ("INDIC_TTS_VOCODER_HI", settings.indic_tts_vocoder_hi),
            "vocoder_config_path": (
                "INDIC_TTS_VOCODER_CONFIG_HI",
                settings.indic_tts_vocoder_config_hi,
            ),
        }
    if language == "kn":
        return {
            "model_path": ("INDIC_TTS_MODEL_KN", settings.indic_tts_model_kn),
            "config_path": ("INDIC_TTS_CONFIG_KN", settings.indic_tts_config_kn),
            "vocoder_path": ("INDIC_TTS_VOCODER_KN", settings.indic_tts_vocoder_kn),
            "vocoder_config_path": (
                "INDIC_TTS_VOCODER_CONFIG_KN",
                settings.indic_tts_vocoder_config_kn,
            ),
        }
    return {}


def _voice_path_for_language(provider: str, language: str) -> Optional[str]:
    mapping = _explicit_voice_settings(provider)

    value = mapping.get(language)
    return value or None


def _explicit_voice_settings(provider: str) -> dict[str, str]:
    if provider == "piper":
        return {
            "en": settings.piper_voice_en.strip(),
            "hi": settings.piper_voice_hi.strip(),
            "kn": settings.piper_voice_kn.strip(),
        }

    return {
        "en": settings.coqui_model_en.strip(),
        "hi": settings.coqui_model_hi.strip(),
        "kn": settings.coqui_model_kn.strip(),
    }


def _resolve_command_path(command: str) -> Optional[str]:
    if not command:
        return None

    resolved = shutil.which(command)
    if resolved:
        return resolved

    path = Path(command).expanduser()
    if path.exists():
        return str(path)

    return None


class TTSRouter:
    """Route text to the best available TTS provider."""

    def __init__(self):
        self.providers = [
            IndicTTSProvider(),
            PiperTTSProvider(),
            CoquiTTSProvider(),
            ToneFallbackProvider(),
        ]

    def available_providers(self) -> list[str]:
        return [provider.name for provider in self.providers if provider.is_available()]

    def available_real_speech_providers(self) -> list[str]:
        return [
            provider.name
            for provider in self.providers
            if provider.is_available() and provider.name != "tone-fallback"
        ]

    def provider_diagnostics(self) -> list[dict]:
        diagnostics = []
        for priority, provider in enumerate(self.providers, start=1):
            diagnostics.append(asdict(provider.diagnostics(priority)))
        return diagnostics

    def readiness_warnings(self) -> list[str]:
        warnings: list[str] = []

        if settings.enable_tts and not self.available_providers():
            warnings.append("TTS is enabled, but no provider is currently available.")

        for diagnostic in self.provider_diagnostics():
            for issue in diagnostic["issues"]:
                warnings.append(f"{diagnostic['name']}: {issue}")

        return warnings

    def choose_language(
        self,
        text: str,
        languages: Optional[list[str]] = None,
        preferred_language: Optional[str] = None,
    ) -> str:
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
            if not provider.supports_language(language):
                continue

            try:
                result = await loop.run_in_executor(None, provider.synthesize, cleaned_text, language)
                log.info(f"TTS synthesized with {provider.name} for language={language}")
                return result
            except Exception as exc:
                last_error = exc
                log.warning(f"TTS provider {provider.name} failed: {exc}")

        raise RuntimeError(f"No TTS provider available for language '{language}': {last_error}")

    def _expand_segment_inputs(
        self,
        segments: list[TTSSegmentInput],
        languages: Optional[list[str]] = None,
        preferred_language: Optional[str] = None,
    ) -> list[TTSSegmentInput]:
        expanded: list[TTSSegmentInput] = []

        for segment in segments:
            cleaned_text = segment.text.strip()
            if not cleaned_text:
                continue

            chunked_segments = segment_text_by_language(
                cleaned_text,
                languages=segment.languages or languages,
                preferred_language=segment.language or preferred_language,
            )

            if len(chunked_segments) > 1:
                log.info(
                    "Split code-mixed TTS text into %s chunks: %s",
                    len(chunked_segments),
                    [language for _, language in chunked_segments],
                )

            for chunk_text, chunk_language in chunked_segments:
                expanded.append(
                    TTSSegmentInput(
                        text=chunk_text,
                        language=chunk_language,
                        languages=[chunk_language],
                    )
                )

        return expanded

    async def synthesize_segments(
        self,
        segments: list[TTSSegmentInput],
        languages: Optional[list[str]] = None,
        preferred_language: Optional[str] = None,
    ) -> TTSBatchResult:
        cleaned_segments = self._expand_segment_inputs(
            [segment for segment in segments if segment.text.strip()],
            languages=languages,
            preferred_language=preferred_language,
        )
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
            results.append(
                TTSSegmentResult(
                    index=index,
                    text=result.text,
                    language=result.language,
                    provider=result.provider,
                    audio_bytes=result.audio_bytes,
                    mime_type=result.mime_type,
                    sample_rate=result.sample_rate,
                    duration_ms=_wav_duration_ms(result.audio_bytes),
                )
            )
            merged_provider_names.append(result.provider)

        merged_audio = _merge_wav_segments(
            [result.audio_bytes for result in results],
            target_sample_rate=settings.tts_sample_rate,
        )
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
            sample_rate=settings.tts_sample_rate,
        )


tts_router = TTSRouter()


def _wav_sample_rate(audio_bytes: bytes) -> Optional[int]:
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            return wav_file.getframerate()
    except Exception:
        return None


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


def _normalize_wav_frames(
    audio_bytes: bytes,
    target_sample_rate: int,
    target_channels: int = 1,
    target_sample_width: int = 2,
) -> tuple[bytes, int, int, int]:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frames = wav_file.readframes(wav_file.getnframes())

    if channels not in {1, 2}:
        raise ValueError(f"Unsupported WAV channel count: {channels}")

    if sample_width != target_sample_width:
        frames = audioop.lin2lin(frames, sample_width, target_sample_width)
        sample_width = target_sample_width

    if channels != target_channels:
        if channels == 2 and target_channels == 1:
            frames = audioop.tomono(frames, sample_width, 0.5, 0.5)
        elif channels == 1 and target_channels == 2:
            frames = audioop.tostereo(frames, sample_width, 1.0, 1.0)
        else:
            raise ValueError(
                f"Unsupported channel conversion from {channels} to {target_channels}"
            )
        channels = target_channels

    if sample_rate != target_sample_rate:
        frames, _ = audioop.ratecv(
            frames,
            sample_width,
            channels,
            sample_rate,
            target_sample_rate,
            None,
        )
        sample_rate = target_sample_rate

    return frames, sample_rate, channels, sample_width


def _merge_wav_segments(segments: list[bytes], target_sample_rate: Optional[int] = None) -> bytes:
    if not segments:
        raise ValueError("No audio segments to merge.")

    output_sample_rate = target_sample_rate or settings.tts_sample_rate
    merged_frames = bytearray()
    channels = 1
    sample_width = 2

    for audio_bytes in segments:
        frames, _, normalized_channels, normalized_sample_width = _normalize_wav_frames(
            audio_bytes,
            target_sample_rate=output_sample_rate,
            target_channels=channels,
            target_sample_width=sample_width,
        )
        channels = normalized_channels
        sample_width = normalized_sample_width
        merged_frames.extend(frames)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(output_sample_rate)
        wav_file.writeframes(bytes(merged_frames))

    return buffer.getvalue()
