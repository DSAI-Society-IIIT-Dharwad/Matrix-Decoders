import re
from typing import Iterable, Optional, Set

from .logger import get_logger

log = get_logger("language")

SUPPORTED_LANGUAGE_CODES = frozenset({"en", "hi", "kn"})

# Unicode ranges for script detection
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")   # Hindi
_KANNADA = re.compile(r"[\u0C80-\u0CFF]")      # Kannada
_LATIN = re.compile(r"[A-Za-z]")               # English / Roman

# Common transliterated Hindi words (Roman script Hindi)
_HINDI_ROMAN = re.compile(
    r"\b(?:kya|kaise|mujhe|chahiye|hai|hain|nahi|nahin|acha|theek|"
    r"karo|karta|karti|bolo|batao|bol|samajh|samjho|yaar|bhai|"
    r"didi|accha|aur|lekin|kyunki|matlab|sab|kuch|bahut|zyada|"
    r"thoda|abhi|woh|yeh|mera|tera|hum|tum|aap|unko|inko|"
    r"kahan|kidhar|idhar|udhar|kaisa|kaisi|kitna|kitni|"
    r"ruko|chalo|jao|aao|dekho|suno|padho|likho|khao|piyo|"
    r"namaste|dhanyavaad|shukriya|alvida|"
    r"paani|khana|ghar|dost|kaam|din|raat|subah|shaam)\b",
    re.IGNORECASE,
)

# Common transliterated Kannada words (Roman script Kannada)
_KANNADA_ROMAN = re.compile(
    r"\b(?:naanu|nanna|ninage|hegidiyaa|hegiddira|channagide|"
    r"hege|yenu|yaake|yelli|yavaga|illi|alli|baa|banni|"
    r"hogi|baro|maadu|maadi|nodu|kodu|helu|kelu|oodu|bareyiri|"
    r"guru|maga|hennu|mane|oota|neeru|kelsa|haalu|"
    r"chennagide|olledu|ketta|hosa|halai|dodda|chikka|"
    r"namaskara|dhanyavaada|shubha|"
    r"gottu|gottilla|beku|beda|aaguttade|aaytu|"
    r"swalpa|thumba|yella|ondhu|eradu|mooru)\b",
    re.IGNORECASE,
)

_TOKEN_PATTERN = re.compile(
    r"\s+|[A-Za-z]+(?:['-][A-Za-z]+)*|[\u0900-\u097F]+|[\u0C80-\u0CFF]+|\d+|[^\w\s]+",
    re.UNICODE,
)


def detect_scripts(text: str) -> Set[str]:
    """Detect all scripts present in the text.

    Returns a set of language codes: 'hi', 'kn', 'en'.
    Also detects transliterated Hindi/Kannada written in Roman script.
    """
    found: Set[str] = set()

    if _DEVANAGARI.search(text):
        found.add("hi")
    if _KANNADA.search(text):
        found.add("kn")
    if _LATIN.search(text):
        found.add("en")

    # Detect transliterated Indic in Roman script
    if "en" in found or not found:
        hindi_matches = _HINDI_ROMAN.findall(text)
        kannada_matches = _KANNADA_ROMAN.findall(text)

        if len(hindi_matches) >= 2:
            found.add("hi")
        if len(kannada_matches) >= 2:
            found.add("kn")

    return found if found else {"unknown"}


def detect_language(text: str) -> str:
    """Backward-compatible single language detection.

    Returns the dominant language code.
    """
    scripts = detect_scripts(text)
    return get_dominant_language(text, scripts)


def normalize_supported_language(language: str, fallback: str = "en") -> str:
    """Clamp a language code to the supported ASR/TTS set."""
    if language in SUPPORTED_LANGUAGE_CODES:
        return language
    if fallback in SUPPORTED_LANGUAGE_CODES:
        return fallback
    return "en"


def filter_supported_languages(languages: Optional[Iterable[str]]) -> Set[str]:
    """Keep only supported language codes from an arbitrary iterable."""
    return {lang for lang in (languages or []) if lang in SUPPORTED_LANGUAGE_CODES}


def classify_token_language(token: str) -> str | None:
    """Classify a single token for code-mixed routing."""
    if not token or token.isspace():
        return None

    if _DEVANAGARI.search(token):
        return "hi"
    if _KANNADA.search(token):
        return "kn"
    if _HINDI_ROMAN.fullmatch(token):
        return "hi"
    if _KANNADA_ROMAN.fullmatch(token):
        return "kn"
    if _LATIN.search(token):
        return "en"

    return None


def segment_text_by_language(
    text: str,
    languages: Optional[Iterable[str]] = None,
    preferred_language: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Split code-mixed text into contiguous language-specific chunks."""
    allowed_languages = filter_supported_languages(languages)
    normalized_preferred = (
        preferred_language if preferred_language in SUPPORTED_LANGUAGE_CODES else None
    )
    groups: list[list[object]] = []
    pending_prefix = ""

    for token in _TOKEN_PATTERN.findall(text):
        token_language = classify_token_language(token)
        if token_language is None:
            if groups:
                parts = groups[-1][1]
                assert isinstance(parts, list)
                parts.append(token)
            else:
                pending_prefix += token
            continue

        if groups and groups[-1][0] == token_language:
            parts = groups[-1][1]
            assert isinstance(parts, list)
            parts.append(token)
            continue

        groups.append([token_language, [pending_prefix, token]])
        pending_prefix = ""

    if pending_prefix and groups:
        parts = groups[-1][1]
        assert isinstance(parts, list)
        parts.append(pending_prefix)

    if not groups:
        cleaned = text.strip()
        if not cleaned:
            return []
        fallback_languages = allowed_languages or detect_scripts(cleaned)
        fallback = normalize_supported_language(
            normalized_preferred or get_dominant_language(cleaned, fallback_languages)
        )
        return [(cleaned, fallback)]

    segmented: list[tuple[str, str]] = []
    for language, parts in groups:
        chunk_text = "".join(parts).strip()
        if chunk_text:
            segmented.append((chunk_text, str(language)))
    return segmented


def is_code_mixed(text: str) -> bool:
    """Check if text contains multiple languages."""
    scripts = detect_scripts(text)
    scripts.discard("unknown")
    return len(scripts) > 1


def get_dominant_language(text: str, scripts: Optional[Set[str]] = None) -> str:
    """Determine the dominant language in the text by character count."""
    if scripts is None:
        scripts = detect_scripts(text)

    scripts = filter_supported_languages(scripts)

    if not scripts:
        return "unknown"
    if len(scripts) == 1:
        return scripts.pop()

    # Count characters per script
    counts = {"hi": 0, "kn": 0, "en": 0}

    for ch in text:
        if _DEVANAGARI.match(ch):
            counts["hi"] += 1
        elif _KANNADA.match(ch):
            counts["kn"] += 1
        elif _LATIN.match(ch):
            counts["en"] += 1

    # Also count transliterated words
    counts["hi"] += len(_HINDI_ROMAN.findall(text)) * 3
    counts["kn"] += len(_KANNADA_ROMAN.findall(text)) * 3

    # Return language with highest count
    dominant = max(
        ((lang, count) for lang, count in counts.items() if lang in scripts),
        key=lambda x: x[1],
        default=("en", 0),
    )
    return dominant[0]


def describe_languages(scripts: Set[str]) -> str:
    """Return human-readable description of language mix."""
    names = {"hi": "Hindi", "kn": "Kannada", "en": "English", "unknown": "Unknown"}
    lang_names = [
        names.get(s, s)
        for s in sorted(filter_supported_languages(scripts))
    ]

    if not lang_names:
        return "Unknown"
    if len(lang_names) == 1:
        return lang_names[0]

    return " + ".join(lang_names)


def split_sentences(text: str):
    """Split text into sentences, handling Indic and English punctuation."""
    # Split on standard punctuation and Devanagari danda (।)
    parts = re.split(r"(?<=[.!?।]) +", text)
    return [p.strip() for p in parts if p.strip()]
