from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading

import torch
import torchaudio
import whisper
from transformers import WhisperForConditionalGeneration, WhisperProcessor

from ..config import settings
from ..logger import get_logger

log = get_logger("asr.whisper")

TARGET_SAMPLE_RATE = 16000
device = "cuda" if torch.cuda.is_available() else "cpu"

_runtime = None
_runtime_lock = threading.Lock()


@dataclass
class _TranscriptionResult:
    text: str
    language: str = "en"


class _HFWhisperRuntime:
    kind = "fine_tuned"

    def __init__(self, model_path: Path):
        self.model_path = model_path
        dtype = torch.float16 if device == "cuda" else torch.float32
        self.processor = WhisperProcessor.from_pretrained(model_path)
        self.model = WhisperForConditionalGeneration.from_pretrained(
            model_path,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
        ).to(device)
        self.model.eval()
        self.model.config.use_cache = True
        if getattr(self.model, "generation_config", None) is not None:
            self.model.generation_config.forced_decoder_ids = None
            self.model.generation_config.suppress_tokens = None
            self.model.generation_config.begin_suppress_tokens = None
        if hasattr(self.model.config, "forced_decoder_ids"):
            self.model.config.forced_decoder_ids = None
        if hasattr(self.model.config, "suppress_tokens"):
            self.model.config.suppress_tokens = None

        self._lang_id_to_code = {
            token_id: token.replace("<|", "").replace("|>", "")
            for token, token_id in (self.model.generation_config.lang_to_id or {}).items()
        }

    def transcribe(self, audio_path: str) -> _TranscriptionResult:
        batch = self._prepare_batch(audio_path)
        input_features = batch["input_features"].to(device=device, dtype=self.model.dtype)
        attention_mask = batch["attention_mask"].to(device=device)

        language = "en"
        with torch.inference_mode():
            try:
                language_ids = self.model.detect_language(input_features=input_features)
                if language_ids.numel() > 0:
                    language = self._lang_id_to_code.get(int(language_ids[0]), "en")
            except Exception as exc:
                log.warning(f"Fine-tuned Whisper language detection failed: {exc}")

            generate_kwargs = {
                "attention_mask": attention_mask,
                "task": "transcribe",
                "return_timestamps": False,
            }
            if language:
                generate_kwargs["language"] = language

            generated_ids = self.model.generate(input_features=input_features, **generate_kwargs)

        text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
        return _TranscriptionResult(text=text, language=language or "en")

    def _prepare_batch(self, audio_path: str) -> dict[str, torch.Tensor]:
        waveform, sample_rate = torchaudio.load(audio_path)
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)
        if waveform.size(0) > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if sample_rate != TARGET_SAMPLE_RATE:
            resampler = torchaudio.transforms.Resample(sample_rate, TARGET_SAMPLE_RATE)
            waveform = resampler(waveform)

        audio = waveform.squeeze(0).cpu().numpy()
        batch = self.processor(
            audio,
            sampling_rate=TARGET_SAMPLE_RATE,
            return_tensors="pt",
            return_attention_mask=True,
        )
        return {
            "input_features": batch.input_features,
            "attention_mask": batch.attention_mask,
        }


class _OpenAIWhisperRuntime:
    kind = "fallback"

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.model = whisper.load_model(model_name).to(device)

    def transcribe(self, audio_path: str) -> _TranscriptionResult:
        result = self.model.transcribe(audio_path)
        return _TranscriptionResult(
            text=result.get("text", "").strip(),
            language=result.get("language", "en") or "en",
        )


def _checkpoint_candidates() -> list[Path]:
    root = Path(settings.asr_checkpoint_dir).expanduser().resolve()
    candidates = [root]
    checkpoint_dirs = sorted(
        (
            path
            for path in root.glob("checkpoint-*")
            if path.is_dir() and path.name.split("-")[-1].isdigit()
        ),
        key=lambda path: int(path.name.split("-")[-1]),
        reverse=True,
    )
    candidates.extend(checkpoint_dirs)
    return candidates


def _is_valid_hf_checkpoint(path: Path) -> bool:
    required_files = ("config.json", "model.safetensors", "processor_config.json", "tokenizer.json")
    return path.is_dir() and all((path / filename).exists() for filename in required_files)


def _normalize_openai_whisper_name(model_name: str) -> str:
    normalized = (model_name or "").strip()
    if normalized.startswith("openai/whisper-"):
        return normalized.removeprefix("openai/whisper-")
    return normalized or "base"


def _build_runtime(force_base: bool = False):
    if not force_base and settings.asr_runtime_prefer_finetuned:
        for checkpoint_dir in _checkpoint_candidates():
            if not _is_valid_hf_checkpoint(checkpoint_dir):
                continue
            log.info(
                f"Loading fine-tuned Whisper checkpoint from {checkpoint_dir} on {device}..."
            )
            try:
                runtime = _HFWhisperRuntime(checkpoint_dir)
                log.info(
                    f"Fine-tuned Whisper checkpoint loaded successfully from {checkpoint_dir}"
                )
                return runtime
            except Exception as exc:
                log.warning(
                    f"Failed to load fine-tuned Whisper checkpoint from {checkpoint_dir}: {exc}"
                )
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
    elif not settings.asr_runtime_prefer_finetuned:
        log.info("Skipping fine-tuned Whisper checkpoint because ASR runtime preference is disabled")

    fallback_name = _normalize_openai_whisper_name(settings.asr_base_model)
    log.info(f"Loading fallback Whisper model '{fallback_name}' on {device}...")
    runtime = _OpenAIWhisperRuntime(fallback_name)
    log.info(f"Fallback Whisper model '{fallback_name}' loaded successfully")
    return runtime


def _load_runtime(force_base: bool = False):
    """Lazy-load the preferred runtime with checkpoint fallback."""
    global _runtime
    with _runtime_lock:
        if _runtime is None or force_base:
            _runtime = _build_runtime(force_base=force_base)
    return _runtime


def _transcribe(audio_path: str) -> _TranscriptionResult:
    runtime = _load_runtime()
    try:
        return runtime.transcribe(audio_path)
    except Exception as exc:
        if getattr(runtime, "kind", "") != "fine_tuned":
            raise

        log.warning(
            f"Fine-tuned Whisper transcription failed for {audio_path}: {exc}. "
            "Retrying with fallback base Whisper."
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        runtime = _load_runtime(force_base=True)
        return runtime.transcribe(audio_path)


def transcribe_english(audio_path: str) -> str:
    """Transcribe audio using the preferred Whisper runtime.

    Returns empty string on failure instead of crashing.
    """
    try:
        result = _transcribe(audio_path)
        log.info(f"Whisper transcription: '{result.text[:80]}...'")
        return result.text
    except Exception as exc:
        log.error(f"Whisper transcription failed for {audio_path}: {exc}")
        return ""


def transcribe_with_language(audio_path: str) -> tuple[str, str]:
    """Transcribe audio using Whisper and return the detected language code."""
    try:
        result = _transcribe(audio_path)
        log.info(f"Whisper transcription [{result.language}]: '{result.text[:80]}...'")
        return result.text, result.language
    except Exception as exc:
        log.error(f"Whisper transcription failed for {audio_path}: {exc}")
        return "", "en"
