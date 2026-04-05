from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.consultation import (
    build_structured_report,
    build_consultation_guidance,
    build_deterministic_response,
    infer_speaker_role,
    normalize_consultation_mode,
    shape_assistant_response,
)
from app.document_parser import extract_document_text


class HealthcareConsultationTests(unittest.TestCase):
    def test_patient_role_is_inferred_from_symptom_language(self) -> None:
        role = infer_speaker_role("I have fever and cough since yesterday")
        self.assertEqual(role, "patient")

    def test_doctor_role_is_inferred_from_clinical_prompt(self) -> None:
        role = infer_speaker_role("How long has the fever been there and do you have allergies?")
        self.assertEqual(role, "doctor")

    def test_hindi_and_kannada_role_inference_cover_patient_and_doctor_turns(self) -> None:
        patient_role = infer_speaker_role("मुझे दो दिन से बुखार और खांसी है")
        doctor_role = infer_speaker_role("ಎಷ್ಟು ದಿನದಿಂದ ಜ್ವರ ಇದೆ ಮತ್ತು ಔಷಧಿ ತೆಗೆದುಕೊಳ್ಳುತ್ತಿದ್ದೀರಾ?")

        self.assertEqual(patient_role, "patient")
        self.assertEqual(doctor_role, "doctor")

    def test_structured_report_extracts_core_healthcare_fields(self) -> None:
        report = build_structured_report(
            [
                {"role": "patient", "content": "I have fever and cough since yesterday."},
                {"role": "doctor", "content": "Likely viral upper respiratory infection. Take rest, fluids, and paracetamol."},
            ]
        )

        self.assertIn("fever", str(report["symptoms"]).lower())
        self.assertIn("viral", str(report["diagnosis"]).lower())
        self.assertIn("paracetamol", str(report["treatment_advice"]).lower())
        self.assertEqual(normalize_consultation_mode("follow up"), "follow_up")

    def test_text_report_file_is_extracted(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("Symptoms: fever, cough. Treatment: rest and fluids.")
            temp_path = Path(handle.name)

        try:
            extracted = extract_document_text(str(temp_path))
            self.assertIn("Symptoms", extracted)
            self.assertIn("Treatment", extracted)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_deterministic_response_localizes_to_detected_language(self) -> None:
        response = build_deterministic_response(
            speaker_role="patient",
            consultation_mode="consultation",
            report={
                "complaint_query": "मुझे बुखार है",
                "symptoms": "बुखार",
                "pending_questions": ["What symptoms are present, and when did they start?"],
                "red_flags": [],
            },
            knowledge_hits=[],
            response_language="hi",
        )

        self.assertIn("मुख्य शिकायत", response)
        self.assertIn("लक्षण", response)

    def test_follow_up_response_includes_consultation_guidance(self) -> None:
        response = build_deterministic_response(
            speaker_role="patient",
            consultation_mode="follow_up",
            report={
                "complaint_query": "cough and mild fever",
                "symptoms": "cough and mild fever",
                "treatment_advice": "",
                "pending_questions": ["Any new side effects or breathing issues?"],
                "red_flags": [],
            },
            knowledge_hits=[],
            response_language="en",
        )

        self.assertIn("continue the advised medicines", response.lower())
        self.assertIn("Has the patient improved", response)

    def test_shape_assistant_response_prepends_guidance_for_follow_up(self) -> None:
        response = shape_assistant_response(
            "How is the cough now? Are you taking medicines regularly? Do you have fever today?",
            speaker_role="patient",
            consultation_mode="follow_up",
            report={
                "complaint_query": "cough",
                "symptoms": "cough",
                "treatment_advice": "",
                "pending_questions": [],
                "red_flags": [],
            },
            knowledge_hits=[],
            response_language="en",
        )

        self.assertIn("Monitor cough", response)
        self.assertLessEqual(response.count("?"), 1)

    def test_consultation_guidance_prefers_existing_treatment_advice(self) -> None:
        guidance = build_consultation_guidance(
            {
                "treatment_advice": "Take steam inhalation, fluids, and paracetamol if needed.",
                "symptoms": "cough",
            },
            knowledge_hits=[],
            response_language="en",
        )

        self.assertIn("Take steam inhalation", guidance)


if __name__ == "__main__":
    unittest.main()
