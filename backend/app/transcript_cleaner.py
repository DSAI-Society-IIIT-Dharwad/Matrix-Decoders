import re

from .language import detect_scripts, get_dominant_language, is_code_mixed

_WHITESPACE_RE = re.compile(r"\s+")
_REPEATED_PUNCT_RE = re.compile(r"([!?.,])\1+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([!?.,])")
_SEGMENT_SPLIT_RE = re.compile(r"(?<=[.!?,;:\u0964])\s+")


def clean_transcript(text: str) -> str:
    """Normalize raw ASR output into cleaner conversational text."""
    if not text:
        return ""

    cleaned = text.strip()
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    cleaned = _REPEATED_PUNCT_RE.sub(r"\1", cleaned)
    cleaned = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)

    # Collapse repeated filler artifacts that ASR models often emit.
    cleaned = re.sub(r"\b(uh|um|ah|er)\b(?:\s+\1\b)+", r"\1", cleaned, flags=re.IGNORECASE)

    return cleaned.strip(" ,")


def split_transcript_segments(text: str) -> list[str]:
    """Split a transcript into readable routing segments."""
    cleaned = clean_transcript(text)
    if not cleaned:
        return []

    parts = [part.strip() for part in _SEGMENT_SPLIT_RE.split(cleaned) if part.strip()]
    if parts:
        return parts

    return [cleaned]


def build_segment_metadata(text: str) -> list[dict]:
    """Create language-tagged transcript segments for downstream routing."""
    segments = []

    for index, segment in enumerate(split_transcript_segments(text), start=1):
        languages = detect_scripts(segment)
        languages.discard("unknown")
        if not languages:
            languages = {"en"}

        segments.append(
            {
                "index": index,
                "text": segment,
                "languages": sorted(languages),
                "dominant_language": get_dominant_language(segment, languages.copy()),
                "is_code_mixed": is_code_mixed(segment),
            }
        )

    return segments

