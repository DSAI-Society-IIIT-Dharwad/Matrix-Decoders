from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from typing import Iterable, List

from .logger import get_logger

log = get_logger("healthcare_resources")


@dataclass(frozen=True)
class HealthcareResourceCard:
    topic: str
    summary: str
    source_name: str
    source_url: str
    keywords: tuple[str, ...]
    recommendation: str = ""

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


PUBLIC_HEALTHCARE_RESOURCES: tuple[HealthcareResourceCard, ...] = (
    HealthcareResourceCard(
        topic="acute_respiratory_symptoms",
        summary=(
            "Respiratory complaints should capture fever, cough duration, breathing difficulty, "
            "oxygen risk, and escalation signs such as chest pain or worsening shortness of breath."
        ),
        source_name="MedQuAD",
        source_url="https://github.com/abachaa/MedQuAD",
        keywords=("cough", "fever", "breath", "breathing", "cold", "flu", "respiratory"),
        recommendation="Monitor temperature, stay hydrated, and seek emergency care if breathing becomes difficult.",
    ),
    HealthcareResourceCard(
        topic="chest_pain_red_flags",
        summary=(
            "Chest pain, fainting, severe breathlessness, and sudden worsening symptoms should be "
            "treated as urgent escalation indicators during intake or follow-up."
        ),
        source_name="MedQuAD",
        source_url="https://github.com/abachaa/MedQuAD",
        keywords=("chest pain", "breath", "shortness", "faint", "collapse", "pressure"),
        recommendation="Seek immediate emergency medical attention for chest pain with shortness of breath.",
    ),
    HealthcareResourceCard(
        topic="injury_and_mobility",
        summary=(
            "Injury documentation should capture mechanism of injury, pain location, swelling, "
            "weight-bearing ability, numbness, and mobility limitation."
        ),
        source_name="Synthea synthetic encounter patterns",
        source_url="https://github.com/synthetichealth/synthea",
        keywords=("injury", "fall", "fracture", "mobility", "walking", "swelling", "pain"),
        recommendation="Apply RICE (Rest, Ice, Compression, Elevation) and consult a doctor if symptoms persist.",
    ),
    HealthcareResourceCard(
        topic="maternal_and_pregnancy",
        summary=(
            "Pregnancy-related conversations should record gestational timing, bleeding, pain, "
            "fetal movement concerns, antenatal follow-up, and urgent risk indicators."
        ),
        source_name="MedQuAD",
        source_url="https://github.com/abachaa/MedQuAD",
        keywords=("pregnant", "pregnancy", "trimester", "antenatal", "bleeding", "fetal"),
        recommendation="Maintain regular antenatal visits and report any bleeding or unusual pain immediately.",
    ),
    HealthcareResourceCard(
        topic="immunization_tracking",
        summary=(
            "Vaccination workflows should capture due vaccines, completed doses, last dose date, "
            "adverse events, and missed-booster follow-up."
        ),
        source_name="Synthea immunization records",
        source_url="https://github.com/synthetichealth/synthea",
        keywords=("vaccine", "vaccination", "immunization", "booster", "dose"),
        recommendation="Follow the recommended immunization schedule and report any adverse reactions promptly.",
    ),
    HealthcareResourceCard(
        topic="ent_findings",
        summary=(
            "ENT documentation should capture ear pain or discharge, sinus congestion, sore throat, "
            "swallowing pain, hearing change, and fever or breathing complications."
        ),
        source_name="MedQuAD",
        source_url="https://github.com/abachaa/MedQuAD",
        keywords=("ear", "nose", "throat", "sinus", "hearing", "swallow", "tonsil"),
        recommendation="Gargle with warm salt water for throat issues; see an ENT specialist if symptoms persist beyond a week.",
    ),
    HealthcareResourceCard(
        topic="clinical_dialog_documentation",
        summary=(
            "Doctor-patient conversations should preserve complaint, history, assessment, and treatment "
            "advice as structured note sections that remain editable after extraction."
        ),
        source_name="MTS-Dialog",
        source_url="https://github.com/abachaa/MTS-Dialog",
        keywords=("doctor", "patient", "history", "assessment", "treatment", "consultation"),
        recommendation="Document all consultation findings in structured format for continuity of care.",
    ),
    HealthcareResourceCard(
        topic="chronic_follow_up",
        summary=(
            "Follow-up conversations should document symptom progression, medication adherence, "
            "side effects, missed doses, and whether the patient is improving or worsening."
        ),
        source_name="Synthea longitudinal records",
        source_url="https://github.com/synthetichealth/synthea",
        keywords=("follow up", "medicine", "medication", "improving", "worsening", "dose"),
        recommendation="Take medications as prescribed and maintain a symptom diary for follow-up visits.",
    ),
    HealthcareResourceCard(
        topic="diabetes_management",
        summary=(
            "Diabetes management should track blood sugar levels, medication adherence, diet, "
            "exercise, and complications like neuropathy or retinopathy."
        ),
        source_name="MedlinePlus",
        source_url="https://medlineplus.gov/diabetes.html",
        keywords=("diabetes", "sugar", "insulin", "glucose", "blood sugar", "diabetic"),
        recommendation="Monitor blood sugar regularly, follow prescribed diet, and never skip insulin doses.",
    ),
    HealthcareResourceCard(
        topic="hypertension_management",
        summary=(
            "Hypertension management covers blood pressure monitoring, salt intake reduction, "
            "medication adherence, and risk of stroke or heart disease."
        ),
        source_name="MedlinePlus",
        source_url="https://medlineplus.gov/highbloodpressure.html",
        keywords=("blood pressure", "hypertension", "bp", "high pressure", "headache", "dizziness"),
        recommendation="Reduce salt intake, exercise regularly, take medications on time, and monitor BP at home.",
    ),
    HealthcareResourceCard(
        topic="gastrointestinal_symptoms",
        summary=(
            "GI complaints should document nausea, vomiting, diarrhea, abdominal pain location, "
            "dietary triggers, and signs of dehydration."
        ),
        source_name="MedQuAD",
        source_url="https://github.com/abachaa/MedQuAD",
        keywords=("stomach", "nausea", "vomiting", "diarrhea", "abdominal", "acidity", "gastric"),
        recommendation="Stay hydrated with ORS, eat bland foods, and seek care if symptoms persist beyond 48 hours.",
    ),
    HealthcareResourceCard(
        topic="skin_conditions",
        summary=(
            "Dermatological complaints should capture rash location, duration, itching, color changes, "
            "exposure history, and any systemic symptoms."
        ),
        source_name="MedlinePlus",
        source_url="https://medlineplus.gov/skinconditions.html",
        keywords=("rash", "skin", "itching", "allergy", "eczema", "dermatitis", "fungal"),
        recommendation="Keep the affected area clean and dry; use antihistamines for itching and consult a dermatologist.",
    ),
    HealthcareResourceCard(
        topic="mental_health",
        summary=(
            "Mental health intake should assess mood, sleep patterns, appetite changes, "
            "anxiety levels, substance use, and suicidal ideation as a red flag."
        ),
        source_name="MedlinePlus",
        source_url="https://medlineplus.gov/mentalhealth.html",
        keywords=("anxiety", "depression", "sleep", "stress", "mental", "mood", "suicidal"),
        recommendation="Practice stress management techniques and seek professional counseling. If suicidal, call emergency services immediately.",
    ),
)


# ---------------------------------------------------------------------------
# Public health resource search via MedlinePlus and ICD-11
# ---------------------------------------------------------------------------

_MEDLINEPLUS_API = "https://connect.medlineplus.gov/service"
_ICD11_API = "https://id.who.int/icd/release/11/2024-01/mms/search"


def _extract_symptom_keywords(texts: Iterable[str]) -> List[str]:
    """Extract likely symptom keywords from conversation texts."""
    corpus = " ".join(texts).lower()
    # Common symptom-related words
    symptom_patterns = re.compile(
        r"\b(fever|cough|pain|headache|nausea|vomiting|diarrhea|rash|"
        r"swelling|bleeding|dizziness|fatigue|weakness|breathing|"
        r"chest|stomach|throat|ear|eye|skin|joint|muscle|bone|"
        r"anxiety|depression|sleep|allergy|infection|inflammation|"
        r"diabetes|sugar|pressure|bp|injury|fracture|burn|cold|flu|"
        r"pregnant|pregnancy|immunization|vaccine|medication|"
        r"bukhar|dard|sir dard|pet dard|khansi|ulti|chakkar|"
        r"neeru|jwara|talenoovu|hotte noovu|kemmu)\b",
        re.IGNORECASE,
    )
    found = symptom_patterns.findall(corpus)
    return list(set(found))


async def search_medlineplus(symptoms: List[str]) -> List[dict]:
    """Query MedlinePlus Connect for health topic information."""
    results: List[dict] = []
    if not symptoms:
        return results

    try:
        import httpx

        query = " ".join(symptoms[:5])
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                _MEDLINEPLUS_API,
                params={
                    "mainSearchCriteria.v.c": query,
                    "mainSearchCriteria.v.cs": "2.16.840.1.113883.6.103",
                    "informationRecipient.languageCode.c": "en",
                    "knowledgeResponseType": "application/json",
                },
            )
            if response.status_code == 200:
                data = response.json()
                entries = data.get("feed", {}).get("entry", [])
                for entry in entries[:3]:
                    title = entry.get("title", {}).get("_value", "Health Information")
                    summary_val = entry.get("summary", {}).get("_value", "")
                    link = ""
                    for lnk in entry.get("link", []):
                        if lnk.get("href"):
                            link = lnk["href"]
                            break
                    results.append(
                        HealthcareResourceCard(
                            topic=title.lower().replace(" ", "_")[:40],
                            summary=summary_val[:300] if summary_val else title,
                            source_name="MedlinePlus",
                            source_url=link or "https://medlineplus.gov",
                            keywords=tuple(symptoms[:5]),
                            recommendation=f"See MedlinePlus for detailed guidance on {title}.",
                        ).to_payload()
                    )
    except Exception as exc:
        log.debug(f"MedlinePlus search skipped: {exc}")

    return results


async def search_icd11(symptoms: List[str]) -> List[dict]:
    """Query WHO ICD-11 coding tool for condition classification."""
    results: List[dict] = []
    if not symptoms:
        return results

    try:
        import httpx

        query = " ".join(symptoms[:3])
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                _ICD11_API,
                params={"q": query, "subtreesFilter": "", "flatResults": "true"},
                headers={
                    "Accept": "application/json",
                    "API-Version": "v2",
                    "Accept-Language": "en",
                },
            )
            if response.status_code == 200:
                data = response.json()
                for item in data.get("destinationEntities", [])[:3]:
                    title = item.get("title", "")
                    # Strip HTML tags from title
                    clean_title = re.sub(r"<[^>]+>", "", title) if title else "ICD-11 Classification"
                    the_id = item.get("theCode", "")
                    results.append(
                        HealthcareResourceCard(
                            topic=f"icd11_{the_id}".lower().replace(".", "_"),
                            summary=f"ICD-11 classification: {clean_title} (Code: {the_id})",
                            source_name="WHO ICD-11",
                            source_url=f"https://icd.who.int/browse/2024-01/mms/en#{the_id}",
                            keywords=tuple(symptoms[:3]),
                            recommendation=f"Classified as {clean_title} in ICD-11. Consult a healthcare professional for proper diagnosis.",
                        ).to_payload()
                    )
    except Exception as exc:
        log.debug(f"ICD-11 search skipped: {exc}")

    return results


async def search_public_resources(texts: Iterable[str]) -> List[dict]:
    """Search public health APIs for relevant resources based on symptoms."""
    symptoms = _extract_symptom_keywords(texts)
    if not symptoms:
        return []

    try:
        medline_results, icd_results = await asyncio.gather(
            search_medlineplus(symptoms),
            search_icd11(symptoms),
            return_exceptions=True,
        )
        results: List[dict] = []
        if isinstance(medline_results, list):
            results.extend(medline_results)
        if isinstance(icd_results, list):
            results.extend(icd_results)
        return results
    except Exception as exc:
        log.debug(f"Public resource search failed: {exc}")
        return []


def select_healthcare_resources(texts: Iterable[str], limit: int = 5) -> list[dict[str, object]]:
    """Select relevant healthcare resources from static cards and optionally public APIs."""
    text_list = list(texts)
    corpus = " ".join(text_list).lower()
    if not corpus.strip():
        return [PUBLIC_HEALTHCARE_RESOURCES[0].to_payload()]

    ranked: list[tuple[int, HealthcareResourceCard]] = []
    for card in PUBLIC_HEALTHCARE_RESOURCES:
        score = sum(1 for keyword in card.keywords if keyword in corpus)
        if score > 0:
            ranked.append((score, card))

    if not ranked:
        ranked = [(1, PUBLIC_HEALTHCARE_RESOURCES[0]), (1, PUBLIC_HEALTHCARE_RESOURCES[-1])]

    ranked.sort(key=lambda item: (-item[0], item[1].topic))
    static_results = [card.to_payload() for _, card in ranked[:limit]]

    # Try to add public API results asynchronously
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're already in an async context, schedule it
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, search_public_resources(text_list))
                try:
                    public_results = future.result(timeout=6.0)
                    if public_results:
                        # De-duplicate by topic
                        seen_topics = {r.get("topic") for r in static_results}
                        for pr in public_results:
                            if pr.get("topic") not in seen_topics:
                                static_results.append(pr)
                                seen_topics.add(pr.get("topic"))
                except Exception:
                    pass
        else:
            public_results = asyncio.run(search_public_resources(text_list))
            if public_results:
                seen_topics = {r.get("topic") for r in static_results}
                for pr in public_results:
                    if pr.get("topic") not in seen_topics:
                        static_results.append(pr)
                        seen_topics.add(pr.get("topic"))
    except Exception as exc:
        log.debug(f"Public resource enrichment skipped: {exc}")

    return static_results[:limit + 3]
