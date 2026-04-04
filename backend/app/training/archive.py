from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Iterable, Optional

import torchaudio

from ..config import settings
from ..language import detect_scripts, get_dominant_language
from ..logger import get_logger
from ..transcript_cleaner import clean_transcript

log = get_logger("training.archive")

_BUCKET_BY_LANGUAGE = {
    "en": "english",
    "hi": "hindi",
    "kn": "kannada",
}


def _bucket_from_metadata(
    text: str,
    dominant_language: Optional[str],
    languages: Optional[Iterable[str]],
    is_code_mixed: bool,
) -> tuple[str, list[str], str]:
    detected_languages = sorted(
        {
            language
            for language in (languages or detect_scripts(text))
            if language and language != "unknown"
        }
    )
    chosen_language = dominant_language or get_dominant_language(text, set(detected_languages))
    if is_code_mixed or len(detected_languages) > 1:
        return "code_mixed", detected_languages or ["en"], chosen_language or "en"
    return _BUCKET_BY_LANGUAGE.get(chosen_language or "", "english"), detected_languages or ["en"], (
        chosen_language or "en"
    )


def _audio_duration_seconds(audio_path: Path) -> float | None:
    try:
        metadata = torchaudio.info(str(audio_path))
    except Exception:
        return None

    if not metadata.sample_rate:
        return None
    return round(float(metadata.num_frames) / float(metadata.sample_rate), 3)


def archive_training_audio(
    audio_path: str,
    text: str,
    dominant_language: Optional[str] = None,
    languages: Optional[Iterable[str]] = None,
    is_code_mixed: bool = False,
    source: str = "runtime",
    session_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> Path | None:
    """Persist audio + transcript pairs for later continual training.

    Stored examples are intentionally marked as weak supervision because the
    transcript currently comes from the running ASR system, not a human review
    workflow. The offline trainer can choose whether to include them.
    """
    if not settings.asr_archive_audio_for_training:
        return None

    try:
        source_path = Path(audio_path).expanduser()
        cleaned_text = clean_transcript(text)
        if not cleaned_text or not source_path.exists():
            return None

        bucket, normalized_languages, chosen_language = _bucket_from_metadata(
            cleaned_text,
            dominant_language=dominant_language,
            languages=languages,
            is_code_mixed=is_code_mixed,
        )

        archive_root = Path(settings.asr_archive_dir).expanduser()
        audio_root = archive_root / "audio" / bucket
        audio_root.mkdir(parents=True, exist_ok=True)

        extension = source_path.suffix or ".wav"
        sample_id = f"runtime_{int(time.time() * 1000)}_{uuid.uuid4().hex[:12]}"
        archived_audio_path = audio_root / f"{sample_id}{extension}"
        shutil.copy2(source_path, archived_audio_path)

        record = {
            "sample_id": sample_id,
            "audio_path": str(archived_audio_path.resolve()),
            "text": cleaned_text,
            "bucket": bucket,
            "languages": normalized_languages,
            "dominant_language": chosen_language,
            "is_code_mixed": bucket == "code_mixed",
            "duration_seconds": _audio_duration_seconds(archived_audio_path),
            "source": source,
            "source_repo": "local_archive",
            "source_config": "",
            "source_split": "runtime",
            "supervision": "weak",
            "session_id": session_id or "",
            "captured_at_epoch_ms": int(time.time() * 1000),
            "metadata": details or {},
        }

        manifest_path = archive_root / "weak_supervision.jsonl"
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        log.info(f"Archived runtime ASR sample for continual training: {archived_audio_path}")
        return archived_audio_path
    except Exception as exc:
        log.warning(f"Skipping training-archive write for {audio_path}: {exc}")
        return None
