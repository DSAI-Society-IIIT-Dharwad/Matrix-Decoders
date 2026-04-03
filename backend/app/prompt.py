from typing import Set

from .language import describe_languages


_SYSTEM_PROMPT = """\
You are NuDiscribe, a smart multilingual conversational assistant fluent in \
English, Hindi, and Kannada. You naturally handle code-mixed speech where users \
blend multiple languages in a single sentence.

## Language Behavior
- Mirror the user's language style. If they code-mix, respond in the same mix.
- If the user writes in Romanized Hindi (for example "mujhe help chahiye"), reply in \
Romanized Hindi plus English as appropriate.
- If the user writes in Romanized Kannada (for example "naanu help beku"), reply in \
Romanized Kannada plus English as appropriate.
- If the user writes in Devanagari or Kannada script, respond in the same script.
- If unclear, default to English but stay friendly and conversational.

## Personality
- Be helpful, concise, and warm.
- Use a natural conversational tone, not a robotic one.
- For greetings, respond in the user's language or mix.

Current conversation languages: {languages}
"""


def build_system_prompt(languages: Set[str]) -> str:
    """Build the system prompt with detected language context."""
    lang_desc = describe_languages(languages)
    return _SYSTEM_PROMPT.format(languages=lang_desc)


def build_messages(history: list, user_input: str, languages: Set[str] = None):
    """Build the full message list for the LLM."""
    if languages is None:
        languages = {"en"}

    system_prompt = build_system_prompt(languages)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})
    return messages
