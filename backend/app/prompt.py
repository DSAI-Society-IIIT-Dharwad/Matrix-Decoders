from __future__ import annotations

import json
from typing import Iterable, Optional

from .consultation import normalize_consultation_mode, normalize_speaker_role
from .language import describe_languages

_LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "kn": "Kannada",
}


def _language_label(language: str) -> str:
    return _LANGUAGE_NAMES.get(language, language.upper() if language else "English")


def _find_last_question(history: list[dict[str, str]]) -> str:
    for message in reversed(history or []):
        role = normalize_speaker_role(message.get("role"), fallback="")
        if role not in {"assistant", "doctor"}:
            continue
        content = str(message.get("content", "")).strip()
        if "?" not in content:
            continue
        return content
    return ""


def _speaker_prefix(speaker_role: str) -> str:
    normalized = normalize_speaker_role(speaker_role, fallback="patient")
    if normalized == "document":
        return "DOCUMENT"
    if normalized == "assistant":
        return "ASSISTANT TURN"
    return f"{normalized.upper()} TURN"


def _is_brief_follow_up_answer(user_input: str) -> bool:
    cleaned = str(user_input or "").strip()
    if not cleaned or "?" in cleaned:
        return False
    return len(cleaned.split()) <= 16


def _format_history_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    formatted: list[dict[str, str]] = []
    for message in history or []:
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        speaker_role = normalize_speaker_role(message.get("role"), fallback="patient")
        if speaker_role == "assistant":
            formatted.append({"role": "assistant", "content": content})
            continue
        formatted.append(
            {
                "role": "user",
                "content": f"{_speaker_prefix(speaker_role)}: {content}",
            }
        )
    return formatted


_HEALTHCARE_SYSTEM_PROMPT = """\
You are NuDiscribe, a multilingual healthcare conversation assistant for clinical intake,
follow-up calls, and structured documentation.

MANDATORY LANGUAGE RULES (highest priority):
- You MUST respond in the selected output language: {response_language}.
- If the selected output language is Hindi, respond fully in Hindi.
- If the selected output language is Kannada, respond fully in Kannada.
- If the selected output language is English, respond in English.
- Do not prepend role labels like DOCTOR TURN or PATIENT TURN.
- If the user reply is short or fragmentary, treat it as the answer to the most recent question.
- The detected input language for this turn is: {input_languages}.

Operational rules:
- Focus on healthcare documentation, triage-safe follow-up, and structured capture.
- Do not invent symptoms, vitals, diagnoses, or medications that were not stated.
- If urgent risk indicators appear, advise immediate clinical or emergency escalation.
- Keep responses concise and action-oriented.
- The assistant consultant's only job is to give a brief probable solution or next-step advice for the reported symptoms.
- Default to 1 or 2 short sentences. Never exceed 2 short sentences.
- Do not ask follow-up questions in the final answer.
- When the speaker is a doctor, prioritize documentation support and confirmation prompts.
- When the speaker is a patient, prioritize symptom clarification, history capture, and safe follow-up questions.
- After learning about symptoms, recommend solutions based on the public healthcare resources provided below.
- When the patient gives a follow-up update, provide only a brief consultation impression or next-step advice.
- Do not keep repeating the intake interview once the patient has already answered.
- Avoid bullet points unless you are warning about urgent escalation.
- Return only plain spoken text.
- Never output JSON, Markdown code fences, field names, or report objects.
- Never mention structured reports, pending questions, knowledge hits, or internal processing.
- Most recent question asked:
{last_question}

Conversation mode: {consultation_mode}
Detected languages: {input_languages}
Selected output language: {response_language}
Current speaker role: {speaker_role}

Current structured report:
{structured_report_json}

Relevant public healthcare resources (use these to recommend solutions):
{knowledge_hits_json}

Suggested follow-up questions:
{suggested_questions_json}
"""


def build_healthcare_messages(
    history: list[dict[str, str]],
    user_input: str,
    languages: Optional[Iterable[str]] = None,
    speaker_role: str = "patient",
    consultation_mode: str = "consultation",
    response_language: str = "en",
    structured_report: Optional[dict[str, object]] = None,
    knowledge_hits: Optional[list[dict[str, object]]] = None,
    suggested_questions: Optional[list[str]] = None,
) -> list[dict[str, str]]:
    normalized_languages = set(languages or {"en"})
    normalized_speaker_role = normalize_speaker_role(speaker_role)
    normalized_mode = normalize_consultation_mode(consultation_mode)
    normalized_response_language = response_language if response_language in {"en", "hi", "kn"} else "en"
    last_question = _find_last_question(history)
    system_prompt = _HEALTHCARE_SYSTEM_PROMPT.format(
        consultation_mode=normalized_mode,
        input_languages=describe_languages(normalized_languages),
        speaker_role=normalized_speaker_role,
        response_language=_language_label(normalized_response_language),
        last_question=last_question or "None",
        structured_report_json=json.dumps(structured_report or {}, ensure_ascii=False, indent=2),
        knowledge_hits_json=json.dumps(knowledge_hits or [], ensure_ascii=False, indent=2),
        suggested_questions_json=json.dumps(suggested_questions or [], ensure_ascii=False, indent=2),
    )

    speaker_prefix = _speaker_prefix(normalized_speaker_role)
    user_content = f"{speaker_prefix}: {user_input}"
    if last_question and _is_brief_follow_up_answer(user_input):
        user_content = (
            f"{user_content}\n"
            f"This short reply answers the most recent question: {last_question}"
        )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(_format_history_messages(history))
    messages.append({"role": "user", "content": user_content})
    return messages
