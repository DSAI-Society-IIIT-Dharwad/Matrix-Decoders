from typing import Iterable, Optional, Set

from .config import settings
from .language import detect_scripts, get_dominant_language

_SUPPORTED_RESPONSE_LANGUAGES = {"en", "hi", "kn"}


def _normalize_languages(languages: Optional[Iterable[str]]) -> Set[str]:
    normalized = {lang for lang in (languages or []) if lang in _SUPPORTED_RESPONSE_LANGUAGES}
    return normalized


def choose_response_language(
    response_text: str,
    detected_languages: Optional[Iterable[str]] = None,
    preferred_language: Optional[str] = None,
) -> str:
    """Choose the best TTS/output language for a response."""
    if preferred_language in _SUPPORTED_RESPONSE_LANGUAGES:
        return preferred_language

    default_language = settings.default_response_language
    if default_language in _SUPPORTED_RESPONSE_LANGUAGES:
        return default_language

    normalized_languages = _normalize_languages(detected_languages)
    if normalized_languages:
        dominant = get_dominant_language(response_text, normalized_languages.copy())
        if dominant in _SUPPORTED_RESPONSE_LANGUAGES:
            return dominant

    inferred_languages = detect_scripts(response_text)
    inferred_languages.discard("unknown")
    if inferred_languages:
        dominant = get_dominant_language(response_text, inferred_languages.copy())
        if dominant in _SUPPORTED_RESPONSE_LANGUAGES:
            return dominant

    return "en"

