from __future__ import annotations

import re
from typing import Iterable, Optional

from .healthcare_resources import select_healthcare_resources
from .language import detect_scripts, get_dominant_language
from .transcript_cleaner import clean_transcript

VALID_SPEAKER_ROLES = {"patient", "doctor", "assistant", "document"}
VALID_CONSULTATION_MODES = {"consultation", "follow_up"}

REPORT_FIELD_ORDER = (
    "complaint_query",
    "background_history",
    "observations_responses",
    "diagnosis_classification_status",
    "action_plan_treatment_plan",
    "verification_survey_responses",
    "symptoms",
    "past_history",
    "clinical_observations",
    "diagnosis",
    "treatment_advice",
    "immunization_data",
    "pregnancy_data",
    "risk_indicators",
    "injury_mobility",
    "ent_findings",
)

FIELD_KEYWORDS = {
    "complaint_query": ("problem", "issue", "complaint", "pain", "fever", "cough", "help", "query"),
    "background_history": (
        "history",
        "before",
        "earlier",
        "previous",
        "past",
        "since",
        "long time",
    ),
    "observations_responses": (
        "reports",
        "reported",
        "mentions",
        "states",
        "response",
        "observation",
        "observed",
    ),
    "diagnosis_classification_status": (
        "diagnosis",
        "assessment",
        "status",
        "likely",
        "confirmed",
        "improving",
        "worsening",
    ),
    "action_plan_treatment_plan": (
        "plan",
        "treatment",
        "advice",
        "recommend",
        "follow up",
        "medicine",
        "medication",
        "rest",
    ),
    "verification_survey_responses": (
        "confirm",
        "yes",
        "no",
        "verified",
        "survey",
        "consent",
    ),
    "symptoms": (
        "pain",
        "fever",
        "cough",
        "cold",
        "headache",
        "vomit",
        "nausea",
        "dizziness",
        "breath",
        "swelling",
        "itching",
        "rash",
    ),
    "past_history": (
        "diabetes",
        "hypertension",
        "bp",
        "asthma",
        "allergy",
        "surgery",
        "chronic",
        "previous",
        "history",
        "medication",
    ),
    "clinical_observations": (
        "temperature",
        "blood pressure",
        "pulse",
        "spo2",
        "oxygen",
        "exam",
        "observed",
        "vitals",
        "swelling",
    ),
    "diagnosis": (
        "diagnosis",
        "likely",
        "infection",
        "viral",
        "fracture",
        "sprain",
        "migraine",
        "assessment",
    ),
    "treatment_advice": (
        "tablet",
        "medicine",
        "medication",
        "rest",
        "hydrate",
        "steam",
        "follow up",
        "consult",
        "monitor",
        "take",
    ),
    "immunization_data": ("vaccine", "vaccination", "immunization", "booster", "dose"),
    "pregnancy_data": ("pregnant", "pregnancy", "trimester", "antenatal", "fetal", "bleeding"),
    "risk_indicators": (
        "risk",
        "urgent",
        "emergency",
        "severe",
        "warning",
        "red flag",
        "chest pain",
        "breathlessness",
        "bleeding",
    ),
    "injury_mobility": (
        "injury",
        "fall",
        "fracture",
        "sprain",
        "walking",
        "movement",
        "mobility",
        "limp",
        "weight bearing",
    ),
    "ent_findings": ("ear", "nose", "throat", "sinus", "hearing", "swallow", "tonsil"),
}

PATIENT_CUES = (
    "i have",
    "i am having",
    "my",
    "mujhe",
    "mujhko",
    "mere",
    "meri",
    "मुझे",
    "मुझको",
    "मेरे",
    "मेरी",
    "nanage",
    "nange",
    "ನನಗೆ",
    "ನನ್ನ",
    "ನನಗೆ ಇದೆ",
    "ನನಗೆ ಜ್ವರ",
    "pain",
    "fever",
    "cough",
    "since yesterday",
    "since morning",
    "problem",
    "symptom",
)

DOCTOR_CUES = (
    "how long",
    "since when",
    "do you have",
    "are you",
    "please confirm",
    "take this",
    "you should",
    "i recommend",
    "follow up",
    "blood pressure",
    "temperature",
    "allergies",
    "medications",
    "कब से",
    "क्या आपको",
    "दवाई",
    "दवा लें",
    "कृपया बताइए",
    "please tell me",
    "please describe",
    "ಎಷ್ಟು ದಿನದಿಂದ",
    "ನಿಮಗೆ ಇದೆಯೆ",
    "ದಯವಿಟ್ಟು ಹೇಳಿ",
    "ಔಷಧಿ ತೆಗೆದುಕೊಳ್ಳಿ",
    "ಪರಿಶೀಲನೆ",
)

RED_FLAG_RULES = {
    "severe_breathing_difficulty": ("cannot breathe", "can't breathe", "breathlessness", "shortness of breath"),
    "cardiac_or_chest_pain": ("chest pain", "chest pressure", "fainting", "collapse"),
    "pregnancy_emergency": ("pregnant bleeding", "pregnancy bleeding", "no fetal movement"),
    "major_injury": ("cannot walk", "unable to walk", "bone visible", "severe swelling"),
    "neurological_alarm": ("unconscious", "seizure", "confused", "slurred speech"),
}

QUESTION_BANK = {
    "complaint_query": "What is the main health problem or symptom right now?",
    "symptoms": "What symptoms are present, and when did they start?",
    "past_history": "Does the patient have past illnesses, allergies, or regular medicines?",
    "clinical_observations": "Do you have any vitals or observations such as temperature, BP, or oxygen level?",
    "diagnosis": "What is the working diagnosis or likely clinical assessment?",
    "treatment_advice": "What treatment, medication, or follow-up advice has been given?",
    "immunization_data": "Are there any vaccine or immunization details that should be recorded?",
    "pregnancy_data": "Is there any pregnancy-related history or risk that should be documented?",
    "risk_indicators": "Are there urgent warning signs or escalation risks present?",
    "injury_mobility": "If injury is involved, what is the mechanism and current mobility status?",
    "ent_findings": "Are there ear, nose, or throat findings that should be added?",
}

GUIDANCE_CUES = {
    "en": ("rest", "hydrate", "monitor", "continue", "seek clinical review", "consult"),
    "hi": ("आराम", "पानी", "निगरानी रखें", "डॉक्टर से संपर्क", "परामर्श"),
    "kn": ("ವಿಶ್ರಾಂತಿ", "ನೀರು", "ಗಮನಿಸಿ", "ವೈದ್ಯರನ್ನು ಸಂಪರ್ಕಿಸಿ", "ಸಲಹೆ"),
}


def normalize_speaker_role(role: Optional[str], fallback: str = "patient") -> str:
    normalized = clean_transcript(str(role or "")).lower().replace(" ", "_")
    if normalized == "user":
        return "patient"
    if normalized in VALID_SPEAKER_ROLES:
        return normalized
    if fallback in VALID_SPEAKER_ROLES:
        return fallback
    return ""


def normalize_consultation_mode(mode: Optional[str]) -> str:
    normalized = clean_transcript(str(mode or "")).lower().replace(" ", "_")
    if normalized in VALID_CONSULTATION_MODES:
        return normalized
    return "consultation"


def infer_speaker_role(
    text: str,
    history_messages: Optional[Iterable[dict]] = None,
    speaker_role_hint: Optional[str] = None,
) -> str:
    if speaker_role_hint in {"patient", "doctor"}:
        return str(speaker_role_hint)

    cleaned = clean_transcript(text).lower()
    if not cleaned:
        return "patient"

    patient_score = sum(2 for cue in PATIENT_CUES if cue in cleaned)
    doctor_score = sum(2 for cue in DOCTOR_CUES if cue in cleaned)

    if cleaned.endswith("?"):
        doctor_score += 1
    if re.search(r"\b(i|my|me|mujhe|nanage|nange)\b", cleaned):
        patient_score += 1
    if re.search(r"\b(take|monitor|rest|hydrate|consult|follow up)\b", cleaned):
        doctor_score += 1

    if doctor_score > patient_score:
        return "doctor"
    if patient_score > doctor_score:
        return "patient"

    last_role = ""
    for message in reversed(list(history_messages or [])):
        role = normalize_speaker_role(message.get("role"), fallback="")
        if role in {"doctor", "patient"}:
            last_role = role
            break

    if last_role == "patient":
        return "doctor"
    return "patient"


def blank_structured_report() -> dict[str, object]:
    report = {field: "" for field in REPORT_FIELD_ORDER}
    report.update(
        {
            "risk_level": "routine",
            "red_flags": [],
            "pending_questions": [],
            "care_summary": "",
        }
    )
    return report


def build_structured_report_schema() -> dict[str, object]:
    properties: dict[str, object] = {field: {"type": "string"} for field in REPORT_FIELD_ORDER}
    properties.update(
        {
            "risk_level": {"type": "string", "enum": ["routine", "watch", "urgent"]},
            "red_flags": {"type": "array", "items": {"type": "string"}},
            "pending_questions": {"type": "array", "items": {"type": "string"}},
            "care_summary": {"type": "string"},
        }
    )
    return {
        "type": "object",
        "properties": properties,
        "required": list(REPORT_FIELD_ORDER),
        "additionalProperties": False,
    }


def merge_structured_report_overrides(
    base_report: Optional[dict[str, object]],
    overrides: Optional[dict[str, object]],
) -> dict[str, object]:
    merged = blank_structured_report()
    if isinstance(base_report, dict):
        merged.update(base_report)
    if not isinstance(overrides, dict):
        return merged

    for field in REPORT_FIELD_ORDER:
        cleaned = clean_transcript(str(overrides.get(field, "")))
        if cleaned:
            merged[field] = cleaned

    risk_level = clean_transcript(str(overrides.get("risk_level", ""))).lower()
    if risk_level in {"routine", "watch", "urgent"}:
        merged["risk_level"] = risk_level

    for field in ("red_flags", "pending_questions"):
        value = overrides.get(field)
        if isinstance(value, list):
            items = [clean_transcript(str(item)) for item in value if clean_transcript(str(item))]
            if items:
                merged[field] = items

    care_summary = clean_transcript(str(overrides.get("care_summary", "")))
    if care_summary:
        merged["care_summary"] = care_summary

    return merged


def _split_sentences(text: str) -> list[str]:
    cleaned = clean_transcript(text)
    if not cleaned:
        return []
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?।])\s+|\n+", cleaned)
        if part.strip()
    ]


def _unique_sentences(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = clean_transcript(value)
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        output.append(normalized)
    return output


def _limit_response_sentences(
    text: str,
    max_sentences: int = 3,
    max_questions: int = 1,
) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return clean_transcript(text)

    limited: list[str] = []
    question_count = 0
    for sentence in sentences:
        is_question = "?" in sentence or sentence.strip().endswith(("?", "？"))
        if is_question and question_count >= max_questions:
            continue
        if is_question:
            question_count += 1
        limited.append(sentence)
        if len(limited) >= max_sentences:
            break

    return clean_transcript(" ".join(limited))


def _extract_by_keywords(sentences: Iterable[str], keywords: Iterable[str]) -> str:
    keyword_list = [keyword.lower() for keyword in keywords]
    matches = [
        sentence
        for sentence in sentences
        if any(keyword in sentence.lower() for keyword in keyword_list)
    ]
    return " ".join(_unique_sentences(matches))


def _find_red_flags(texts: Iterable[str]) -> list[str]:
    corpus = " ".join(clean_transcript(text).lower() for text in texts)
    found: list[str] = []
    for label, patterns in RED_FLAG_RULES.items():
        if any(pattern in corpus for pattern in patterns):
            found.append(label)
    return found


def _derive_risk_level(red_flags: list[str], report: dict[str, object]) -> str:
    if red_flags:
        return "urgent"
    risk_text = str(report.get("risk_indicators", "")).lower()
    if any(keyword in risk_text for keyword in ("severe", "urgent", "emergency")):
        return "urgent"
    if any(keyword in risk_text for keyword in ("monitor", "review", "observe")):
        return "watch"
    return "routine"


def build_structured_report(
    messages: Iterable[dict],
    transcript_records: Optional[Iterable[dict]] = None,
    document_texts: Optional[Iterable[str]] = None,
) -> dict[str, object]:
    report = blank_structured_report()

    patient_messages = [
        clean_transcript(str(message.get("content", "")))
        for message in messages
        if normalize_speaker_role(message.get("role")) == "patient"
    ]
    doctor_messages = [
        clean_transcript(str(message.get("content", "")))
        for message in messages
        if normalize_speaker_role(message.get("role")) == "doctor"
    ]
    assistant_messages = [
        clean_transcript(str(message.get("content", "")))
        for message in messages
        if normalize_speaker_role(message.get("role")) == "assistant"
    ]
    transcript_texts = [
        clean_transcript(str(record.get("text", "")))
        for record in (transcript_records or [])
    ]
    document_payloads = [clean_transcript(text) for text in (document_texts or []) if clean_transcript(text)]

    patient_sentences = _split_sentences(" ".join(patient_messages + transcript_texts))
    doctor_sentences = _split_sentences(" ".join(doctor_messages))
    assistant_sentences = _split_sentences(" ".join(assistant_messages))
    document_sentences = _split_sentences(" ".join(document_payloads))
    all_sentences = _unique_sentences(
        patient_sentences + doctor_sentences + assistant_sentences + document_sentences
    )

    report["complaint_query"] = (
        patient_sentences[0]
        if patient_sentences
        else document_sentences[0] if document_sentences else ""
    )
    report["background_history"] = _extract_by_keywords(all_sentences, FIELD_KEYWORDS["background_history"])
    report["observations_responses"] = _extract_by_keywords(
        patient_sentences + document_sentences,
        FIELD_KEYWORDS["observations_responses"],
    )
    report["diagnosis_classification_status"] = _extract_by_keywords(
        doctor_sentences + assistant_sentences + document_sentences,
        FIELD_KEYWORDS["diagnosis_classification_status"],
    )
    report["action_plan_treatment_plan"] = _extract_by_keywords(
        doctor_sentences + assistant_sentences + document_sentences,
        FIELD_KEYWORDS["action_plan_treatment_plan"],
    )
    report["verification_survey_responses"] = _extract_by_keywords(
        patient_sentences + doctor_sentences + document_sentences,
        FIELD_KEYWORDS["verification_survey_responses"],
    )

    for field in (
        "symptoms",
        "past_history",
        "clinical_observations",
        "diagnosis",
        "treatment_advice",
        "immunization_data",
        "pregnancy_data",
        "risk_indicators",
        "injury_mobility",
        "ent_findings",
    ):
        if field in {"diagnosis", "treatment_advice", "clinical_observations"}:
            sentences = doctor_sentences + assistant_sentences + document_sentences + patient_sentences
        else:
            sentences = patient_sentences + doctor_sentences + document_sentences + assistant_sentences
        report[field] = _extract_by_keywords(sentences, FIELD_KEYWORDS[field])

    red_flags = _find_red_flags(all_sentences)
    report["red_flags"] = red_flags
    report["risk_level"] = _derive_risk_level(red_flags, report)

    pending_questions = [
        question
        for field, question in QUESTION_BANK.items()
        if not clean_transcript(str(report.get(field, "")))
    ]
    report["pending_questions"] = pending_questions[:4]

    summary_bits = [
        report["complaint_query"],
        report["diagnosis"],
        report["treatment_advice"],
    ]
    report["care_summary"] = " ".join(
        clean_transcript(str(value)) for value in summary_bits if clean_transcript(str(value))
    ).strip()
    return report


def build_consultation_turns(session_snapshot: Optional[dict]) -> list[dict[str, object]]:
    if not session_snapshot:
        return []

    turns: list[dict[str, object]] = []
    for message in session_snapshot.get("messages", []):
        role = normalize_speaker_role(message.get("role"), fallback="assistant")
        if role not in VALID_SPEAKER_ROLES:
            continue
        content = clean_transcript(str(message.get("content", "")))
        if not content:
            continue
        languages = list(detect_scripts(content) - {"unknown"}) or ["en"]
        turns.append(
            {
                "id": int(message.get("id", 0)),
                "speaker_role": role,
                "text": content,
                "created_at": message.get("created_at", ""),
                "language": get_dominant_language(content, set(languages)),
                "languages": languages,
            }
        )
    return turns


def build_follow_up_questions(
    report: dict[str, object],
    speaker_role: str,
    consultation_mode: str,
) -> list[str]:
    questions = list(report.get("pending_questions", []))
    if consultation_mode == "follow_up":
        questions = [
            "Has the patient improved since the previous visit?",
            "Is the patient taking the prescribed medicines as advised?",
            "Any new side effects, fever, breathing issues, or worsening symptoms?",
        ] + questions
    elif speaker_role == "doctor":
        questions = [
            "Please confirm the working diagnosis and treatment advice for documentation."
        ] + questions
    return _unique_sentences(questions)[:4]


def build_deterministic_response(
    speaker_role: str,
    consultation_mode: str,
    report: dict[str, object],
    knowledge_hits: list[dict[str, object]],
    response_language: str = "en",
) -> str:
    target_language = response_language if response_language in {"en", "hi", "kn"} else "en"
    red_flags = list(report.get("red_flags", []))
    pending_questions = _localize_follow_up_questions(
        build_follow_up_questions(report, speaker_role, consultation_mode),
        target_language,
    )
    consultation_guidance = build_consultation_guidance(
        report,
        knowledge_hits,
        response_language=target_language,
        consultation_mode=consultation_mode,
    )

    if red_flags:
        if target_language == "hi":
            return (
                "इस बातचीत में गंभीर जोखिम संकेत मिले हैं। "
                "कृपया तुरंत क्लिनिकल समीक्षा या इमरजेंसी सहायता की व्यवस्था करें और मुख्य चेतावनी लक्षणों की पुष्टि करें।"
            )
        if target_language == "kn":
            return (
                "ಈ ಸಂಭಾಷಣದಲ್ಲಿ ತುರ್ತು ಅಪಾಯ ಸೂಚನೆಗಳು ಕಂಡುಬಂದಿವೆ. "
                "ದಯವಿಟ್ಟು ತಕ್ಷಣ ವೈದ್ಯಕೀಯ ಪರಿಶೀಲನೆ ಅಥವಾ ತುರ್ತು ಸಹಾಯವನ್ನು ವ್ಯವಸ್ಥೆ ಮಾಡಿ ಮತ್ತು ಮುಖ್ಯ ಅಪಾಯ ಲಕ್ಷಣಗಳನ್ನು ದೃಢಪಡಿಸಿ."
            )
        return (
            "I have flagged urgent risk indicators in this conversation. "
            "Please arrange immediate clinical review or emergency escalation, and confirm the key red-flag symptoms."
        )

    complaint = clean_transcript(str(report.get("complaint_query", "")))
    symptoms = clean_transcript(str(report.get("symptoms", "")))

    if consultation_mode == "follow_up":
        if target_language == "hi":
            return _limit_response_sentences(
                " ".join(
                    part for part in [
                        "यह स्वास्थ्य फॉलो-अप जाँच है।",
                        consultation_guidance,
                        pending_questions[0] if pending_questions else "",
                    ] if part
                )
            )
        if target_language == "kn":
            return _limit_response_sentences(
                " ".join(
                    part for part in [
                        "ಇದು ಆರೋಗ್ಯ ಫಾಲೋ-ಅಪ್ ಪರಿಶೀಲನೆ.",
                        consultation_guidance,
                        pending_questions[0] if pending_questions else "",
                    ] if part
                )
            )
        return _limit_response_sentences(
            " ".join(
                part for part in [
                    "This is a healthcare follow-up check.",
                    consultation_guidance,
                    pending_questions[0] if pending_questions else "",
                ] if part
            )
        )

    if speaker_role == "doctor":
        if target_language == "hi":
            return _limit_response_sentences(
                "डॉक्टर का इनपुट दर्ज हो गया है। "
                "मैं परामर्श रिपोर्ट अपडेट कर रहा हूँ। "
                + " ".join(pending_questions[:1])
            )
        if target_language == "kn":
            return _limit_response_sentences(
                "ವೈದ್ಯರ ಇನ್‌ಪುಟ್ ದಾಖಲಾಗಿದೆ. "
                "ನಾನು ಸಮಾಲೋಚನೆ ವರದಿಯನ್ನು ನವೀಕರಿಸುತ್ತಿದ್ದೇನೆ. "
                + " ".join(pending_questions[:1])
            )
        return _limit_response_sentences(
            "Doctor input captured. "
            "I will update the consultation report. "
            + " ".join(pending_questions[:1])
        )

    if target_language == "hi":
        intro = "मरीज की जानकारी दर्ज कर ली गई है।"
    elif target_language == "kn":
        intro = "ರೋಗಿಯ ಮಾಹಿತಿಯನ್ನು ದಾಖಲಿಸಲಾಗಿದೆ."
    else:
        intro = "I have captured the patient's update."
    if complaint:
        if target_language == "hi":
            intro = f"मुख्य शिकायत दर्ज की गई है: {complaint}."
        elif target_language == "kn":
            intro = f"ಮುಖ್ಯ ತೊಂದರೆಯನ್ನು ದಾಖಲಿಸಲಾಗಿದೆ: {complaint}."
        else:
            intro = f"I captured the main complaint: {complaint}."
    elif symptoms:
        if target_language == "hi":
            intro = f"बताए गए लक्षण दर्ज किए गए हैं: {symptoms}."
        elif target_language == "kn":
            intro = f"ಹೇಳಿದ ಲಕ್ಷಣಗಳನ್ನು ದಾಖಲಿಸಲಾಗಿದೆ: {symptoms}."
        else:
            intro = f"I captured the reported symptoms: {symptoms}."

    knowledge_line = ""
    if knowledge_hits and target_language == "en":
        knowledge_line = (
            f" Relevant public healthcare context: {knowledge_hits[0]['summary']}"
        )

    if target_language == "hi":
        fallback_tail = " कृपया अगला महत्वपूर्ण चिकित्सीय विवरण बताइए।"
    elif target_language == "kn":
        fallback_tail = " ದಯವಿಟ್ಟು ಮುಂದಿನ ಮುಖ್ಯ ವೈದ್ಯಕೀಯ ವಿವರವನ್ನು ತಿಳಿಸಿ."
    else:
        fallback_tail = " Please continue with the next clinical detail."

    response = (
        intro
        + knowledge_line
        + (" " + consultation_guidance if consultation_guidance else "")
        + (" " + pending_questions[:1][0] if pending_questions else fallback_tail)
    ).strip()
    return _limit_response_sentences(response)


def build_consultation_guidance(
    report: dict[str, object],
    knowledge_hits: list[dict[str, object]],
    response_language: str = "en",
    consultation_mode: str = "consultation",
) -> str:
    target_language = response_language if response_language in {"en", "hi", "kn"} else "en"
    advice = clean_transcript(str(report.get("treatment_advice", "")))
    recommendation = clean_transcript(str((knowledge_hits[0] or {}).get("recommendation", ""))) if knowledge_hits else ""
    symptom_text = clean_transcript(
        str(report.get("symptoms", "") or report.get("complaint_query", ""))
    )

    if advice:
        if target_language == "hi":
            return f"अभी के लिए सलाह: {advice}"
        if target_language == "kn":
            return f"ಈಗಕ್ಕೆ ಸಲಹೆ: {advice}"
        return f"For now: {advice}"

    if recommendation and target_language == "en":
        return recommendation

    if consultation_mode == "follow_up":
        if target_language == "hi":
            if symptom_text:
                return f"{symptom_text} पर निगरानी रखें, दवाइयाँ नियमित लें, और लक्षण बढ़ें तो डॉक्टर से तुरंत संपर्क करें।"
            return "दवाइयाँ नियमित लें, आराम करें, और लक्षण बढ़ें तो डॉक्टर से तुरंत संपर्क करें।"
        if target_language == "kn":
            if symptom_text:
                return f"{symptom_text} ಅನ್ನು ಗಮನಿಸಿ, ಔಷಧಿಗಳನ್ನು ನಿಯಮಿತವಾಗಿ ತೆಗೆದುಕೊಳ್ಳಿ, ಮತ್ತು ಲಕ್ಷಣಗಳು ಹೆಚ್ಚಾದರೆ ತಕ್ಷಣ ವೈದ್ಯರನ್ನು ಸಂಪರ್ಕಿಸಿ."
            return "ಔಷಧಿಗಳನ್ನು ನಿಯಮಿತವಾಗಿ ತೆಗೆದುಕೊಳ್ಳಿ, ವಿಶ್ರಾಂತಿ ಮಾಡಿ, ಮತ್ತು ಲಕ್ಷಣಗಳು ಹೆಚ್ಚಾದರೆ ತಕ್ಷಣ ವೈದ್ಯರನ್ನು ಸಂಪರ್ಕಿಸಿ."
        if symptom_text:
            return f"Monitor {symptom_text}, continue the advised medicines, and seek clinical review if symptoms worsen."
        return "Continue the advised medicines and seek clinical review if symptoms worsen."

    if target_language == "hi":
        return "आराम करें, पानी पीते रहें, और लक्षण बढ़ें तो डॉक्टर से संपर्क करें।"
    if target_language == "kn":
        return "ವಿಶ್ರಾಂತಿ ಮಾಡಿ, ಸಾಕಷ್ಟು ನೀರು ಕುಡಿಯಿರಿ, ಮತ್ತು ಲಕ್ಷಣಗಳು ಹೆಚ್ಚಾದರೆ ವೈದ್ಯರನ್ನು ಸಂಪರ್ಕಿಸಿ."
    return "Rest, stay hydrated, and seek clinical review if symptoms worsen."


def response_contains_guidance(text: str, language: str = "en") -> bool:
    cleaned = clean_transcript(text).lower()
    cues = GUIDANCE_CUES.get(language, GUIDANCE_CUES["en"])
    return any(cue.lower() in cleaned for cue in cues)


def shape_assistant_response(
    text: str,
    speaker_role: str,
    consultation_mode: str,
    report: dict[str, object],
    knowledge_hits: list[dict[str, object]],
    response_language: str = "en",
) -> str:
    target_language = response_language if response_language in {"en", "hi", "kn"} else "en"
    cleaned = clean_transcript(text)
    if not cleaned:
        return build_deterministic_response(
            speaker_role=speaker_role,
            consultation_mode=consultation_mode,
            report=report,
            knowledge_hits=knowledge_hits,
            response_language=target_language,
        )

    if consultation_mode == "follow_up" and speaker_role == "patient":
        guidance = build_consultation_guidance(
            report,
            knowledge_hits,
            response_language=target_language,
            consultation_mode=consultation_mode,
        )
        if guidance and not response_contains_guidance(cleaned, target_language):
            cleaned = f"{guidance} {cleaned}"

    return _limit_response_sentences(cleaned)


def _localize_follow_up_questions(questions: list[str], language: str) -> list[str]:
    if language not in {"hi", "kn"}:
        return questions

    translations = {
        "Has the patient improved since the previous visit?": {
            "hi": "क्या पिछली मुलाकात के बाद मरीज में सुधार हुआ है?",
            "kn": "ಹಿಂದಿನ ಭೇಟಿಯ ನಂತರ ರೋಗಿಯಲ್ಲಿ ಸುಧಾರಣೆ ಆಗಿದೆಯೆ?",
        },
        "Is the patient taking the prescribed medicines as advised?": {
            "hi": "क्या मरीज बताई गई दवाइयाँ नियमित रूप से ले रहा है?",
            "kn": "ರೋಗಿ ಸೂಚಿಸಿದ ಔಷಧಿಗಳನ್ನು ನಿಯಮಿತವಾಗಿ ತೆಗೆದುಕೊಳ್ಳುತ್ತಿದ್ದಾನೆಯೆ?",
        },
        "Any new side effects, fever, breathing issues, or worsening symptoms?": {
            "hi": "क्या कोई नए दुष्प्रभाव, बुखार, सांस की तकलीफ, या बढ़ते हुए लक्षण हैं?",
            "kn": "ಹೊಸ ಅಡ್ಡ ಪರಿಣಾಮಗಳು, ಜ್ವರ, ಉಸಿರಾಟದ ತೊಂದರೆ, ಅಥವಾ ಹೆಚ್ಚಾದ ಲಕ್ಷಣಗಳಿವೆಯೆ?",
        },
        "Please confirm the working diagnosis and treatment advice for documentation.": {
            "hi": "कृपया दस्तावेज़ीकरण के लिए कार्यशील निदान और उपचार सलाह की पुष्टि करें।",
            "kn": "ದಾಖಲೆಗಾಗಿ ಕಾರ್ಯನಿರ್ವಹಣಾ ನಿರ್ಧಾರ ಮತ್ತು ಚಿಕಿತ್ಸಾ ಸಲಹೆಯನ್ನು ದೃಢಪಡಿಸಿ.",
        },
        "What is the main health problem or symptom right now?": {
            "hi": "अभी मुख्य स्वास्थ्य समस्या या लक्षण क्या है?",
            "kn": "ಈಗಿರುವ ಮುಖ್ಯ ಆರೋಗ್ಯ ತೊಂದರೆ ಅಥವಾ ಲಕ್ಷಣ ಯಾವುದು?",
        },
        "What symptoms are present, and when did they start?": {
            "hi": "कौन-कौन से लक्षण हैं, और वे कब से शुरू हुए?",
            "kn": "ಯಾವ ಲಕ್ಷಣಗಳಿವೆ, ಮತ್ತು ಅವು ಯಾವಾಗಿನಿಂದ ಆರಂಭವಾದವು?",
        },
        "Does the patient have past illnesses, allergies, or regular medicines?": {
            "hi": "क्या मरीज को पहले की बीमारियाँ, एलर्जी, या नियमित दवाइयाँ हैं?",
            "kn": "ರೋಗಿಗೆ ಹಿಂದಿನ ಕಾಯಿಲೆಗಳು, ಅಲರ್ಜಿ, ಅಥವಾ ನಿಯಮಿತ ಔಷಧಿಗಳಿವೆಯೆ?",
        },
        "Do you have any vitals or observations such as temperature, BP, or oxygen level?": {
            "hi": "क्या तापमान, बीपी, या ऑक्सीजन स्तर जैसे कोई वाइटल्स या ऑब्जर्वेशन हैं?",
            "kn": "ತಾಪಮಾನ, ಬಿಪಿ, ಅಥವಾ ಆಮ್ಲಜನಕ ಮಟ್ಟದಂತಹ ವೈಟಲ್ಸ್ ಅಥವಾ ಗಮನಿಸುವಿಕೆಗಳಿವೆಯೆ?",
        },
        "What is the working diagnosis or likely clinical assessment?": {
            "hi": "कार्यशील निदान या संभावित क्लिनिकल आकलन क्या है?",
            "kn": "ಕಾರ್ಯನಿರ್ವಹಣಾ ನಿರ್ಧಾರ ಅಥವಾ ಸಾಧ್ಯವಾದ ಕ್ಲಿನಿಕಲ್ ಮೌಲ್ಯಮಾಪನ ಯಾವುದು?",
        },
        "What treatment, medication, or follow-up advice has been given?": {
            "hi": "क्या उपचार, दवा, या फॉलो-अप सलाह दी गई है?",
            "kn": "ಯಾವ ಚಿಕಿತ್ಸೆ, ಔಷಧಿ, ಅಥವಾ ಫಾಲೋ-ಅಪ್ ಸಲಹೆ ನೀಡಲಾಗಿದೆ?",
        },
        "Are there any vaccine or immunization details that should be recorded?": {
            "hi": "क्या कोई टीकाकरण या इम्यूनाइजेशन विवरण दर्ज करना है?",
            "kn": "ದಾಖಲಿಸಬೇಕಾದ ಯಾವುದೇ ಲಸಿಕೆ ವಿವರಗಳಿವೆಯೆ?",
        },
        "Is there any pregnancy-related history or risk that should be documented?": {
            "hi": "क्या गर्भावस्था से जुड़ा कोई इतिहास या जोखिम दर्ज करना है?",
            "kn": "ದಾಖಲಿಸಬೇಕಾದ ಗರ್ಭಧಾರಣೆಗೆ ಸಂಬಂಧಿಸಿದ ಇತಿಹಾಸ ಅಥವಾ ಅಪಾಯವಿದೆಯೆ?",
        },
        "Are there urgent warning signs or escalation risks present?": {
            "hi": "क्या कोई तात्कालिक चेतावनी संकेत या बढ़ते जोखिम मौजूद हैं?",
            "kn": "ತುರ್ತು ಎಚ್ಚರಿಕೆ ಸೂಚನೆಗಳು ಅಥವಾ ಹೆಚ್ಚುವರಿ ಅಪಾಯಗಳಿವೆಯೆ?",
        },
        "If injury is involved, what is the mechanism and current mobility status?": {
            "hi": "यदि चोट लगी है, तो चोट कैसे लगी और अभी चलने-फिरने की स्थिति क्या है?",
            "kn": "ಗಾಯವಿದ್ದರೆ ಅದು ಹೇಗೆ ಸಂಭವಿಸಿತು ಮತ್ತು ಈಗಿನ ಚಲನೆಯ ಸ್ಥಿತಿ ಏನು?",
        },
        "Are there ear, nose, or throat findings that should be added?": {
            "hi": "क्या कान, नाक, या गले से जुड़ी कोई जानकारी जोड़नी है?",
            "kn": "ಕಿವಿ, ಮೂಗು, ಅಥವಾ ಗಂಟಲು ಸಂಬಂಧಿತ ಯಾವುದಾದರೂ ವಿವರಗಳನ್ನು ಸೇರಿಸಬೇಕೆ?",
        },
    }
    return [translations.get(question, {}).get(language, question) for question in questions]


def build_opening_assistant_prompt(consultation_mode: str) -> str:
    if consultation_mode == "follow_up":
        return (
            "This is a follow-up check. Is the patient better, the same, or worse since the last consultation, and are the medicines being taken as advised?"
        )
    return (
        "Please tell me the main problem, when it started, and any regular medicines or past medical history."
    )


def derive_consultation_snapshot(session_snapshot: Optional[dict]) -> dict[str, object]:
    turns = build_consultation_turns(session_snapshot)
    transcript_records = list((session_snapshot or {}).get("transcripts", []))
    document_texts = [
        str(record.get("text", ""))
        for record in transcript_records
        if str(record.get("source", "")).startswith("report.")
    ]
    report = build_structured_report(turns, transcript_records=transcript_records, document_texts=document_texts)
    knowledge_hits = select_healthcare_resources(
        [turn.get("text", "") for turn in turns] + document_texts
    )
    return {
        "consultation_turns": turns,
        "structured_report": report,
        "knowledge_hits": knowledge_hits,
        "suggested_questions": build_follow_up_questions(report, "patient", "consultation"),
    }
