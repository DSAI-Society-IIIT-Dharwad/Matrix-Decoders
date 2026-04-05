from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class KnowledgeHit(BaseModel):
    topic: str
    summary: str
    source_name: str
    source_url: str
    keywords: List[str] = Field(default_factory=list)
    recommendation: str = Field(default="", description="Actionable recommendation from the resource")


class StructuredReport(BaseModel):
    complaint_query: str = ""
    background_history: str = ""
    observations_responses: str = ""
    diagnosis_classification_status: str = ""
    action_plan_treatment_plan: str = ""
    verification_survey_responses: str = ""
    symptoms: str = ""
    past_history: str = ""
    clinical_observations: str = ""
    diagnosis: str = ""
    treatment_advice: str = ""
    immunization_data: str = ""
    pregnancy_data: str = ""
    risk_indicators: str = ""
    injury_mobility: str = ""
    ent_findings: str = ""
    risk_level: str = "routine"
    red_flags: List[str] = Field(default_factory=list)
    pending_questions: List[str] = Field(default_factory=list)
    care_summary: str = ""


class ConsultationTurn(BaseModel):
    id: int | None = None
    speaker_role: str
    text: str
    language: str = "en"
    languages: List[str] = Field(default_factory=list)
    created_at: str = ""


class ChatRequest(BaseModel):
    session_id: str = Field(default="default", description="Session identifier")
    text: str = Field(..., description="Speaker utterance")
    speaker_role: str | None = Field(default=None, description="Optional speaker role hint")
    consultation_mode: str = Field(default="consultation", description="consultation or follow_up")
    response_language: str | None = Field(default=None, description="Preferred output language")


class ChatResponse(BaseModel):
    text: str
    language: str
    languages: List[str] = Field(default_factory=list)
    is_code_mixed: bool = False
    session_id: str
    speaker_role: str = "patient"
    consultation_mode: str = "consultation"
    structured_report: StructuredReport = Field(default_factory=StructuredReport)
    knowledge_hits: List[KnowledgeHit] = Field(default_factory=list)
    suggested_questions: List[str] = Field(default_factory=list)


class StartConsultationRequest(BaseModel):
    session_id: str = Field(default="default")
    consultation_mode: str = Field(default="consultation")
    response_language: str | None = Field(default=None, description="Preferred output language")


class TranscriptSegment(BaseModel):
    index: Optional[int] = None
    text: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    language: Optional[str] = None
    languages: Optional[List[str]] = None
    dominant_language: Optional[str] = None
    engine: Optional[str] = None
    is_code_mixed: Optional[bool] = None
    is_final: bool = True


class TranscribeResponse(BaseModel):
    text: str
    language: str
    languages: List[str] = Field(default_factory=list)
    is_code_mixed: bool = False
    segments: List[TranscriptSegment] = Field(default_factory=list)
    speaker_role: str = "patient"
    structured_report: StructuredReport = Field(default_factory=StructuredReport)
    knowledge_hits: List[KnowledgeHit] = Field(default_factory=list)
    suggested_questions: List[str] = Field(default_factory=list)


class ReportExtractResponse(BaseModel):
    filename: str
    text: str
    structured_report: StructuredReport = Field(default_factory=StructuredReport)
    knowledge_hits: List[KnowledgeHit] = Field(default_factory=list)
    dynamic_json: dict[str, Any] = Field(default_factory=dict)
    dynamic_issues: List[str] = Field(default_factory=list)
    dynamic_used_llm: bool = False
    dynamic_fallback_used: bool = False


class DynamicExtractRequest(BaseModel):
    text: str = Field(..., description="Source text to extract from")
    schema: dict[str, Any] = Field(
        ...,
        description="JSON schema object that defines extraction fields and types",
    )
    context: str = Field(default="", description="Optional extraction context or instructions")
    session_id: Optional[str] = Field(default=None, description="Optional session identifier for telemetry")


class DynamicExtractResponse(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    normalized_schema: dict[str, Any] = Field(default_factory=dict)
    issues: List[str] = Field(default_factory=list)
    used_llm: bool = False
    fallback_used: bool = False


class HealthResponse(BaseModel):
    status: str = "ok"
    model: str
    uptime_seconds: float
    sessions_active: int
    tts_enabled: bool = False
    tts_ready: bool = False
    tts_providers: List[str] = Field(default_factory=list)
    tts_real_speech_ready: bool = False
    tts_real_providers: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    language: Optional[str] = Field(default=None, description="Preferred response language")
    languages: List[str] = Field(default_factory=list)


class TTSResponse(BaseModel):
    text: str
    language: str
    provider: str
    mime_type: str
    sample_rate: int
    audio_b64: str


class SessionSummary(BaseModel):
    session_id: str
    created_at: str
    updated_at: str
    languages: List[str] = Field(default_factory=list)
    selected_language: str = ""
    message_count: int = 0
    transcript_count: int = 0
    telemetry_count: int = 0
    last_message: str = ""
    last_transcript: str = ""


class SessionMessageRecord(BaseModel):
    id: int
    role: str
    content: str
    created_at: str


class SessionTranscriptRecord(BaseModel):
    id: int
    source: str
    text: str
    dominant_language: str = ""
    languages: List[str] = Field(default_factory=list)
    is_code_mixed: bool = False
    segments: List[TranscriptSegment] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class SessionTelemetryRecord(BaseModel):
    id: int
    kind: str
    name: str
    status: str = ""
    latency_ms: Optional[float] = None
    error_message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class SessionDetailResponse(BaseModel):
    session_id: str
    created_at: str
    updated_at: str
    languages: List[str] = Field(default_factory=list)
    selected_language: str = ""
    message_count: int = 0
    transcript_count: int = 0
    telemetry_count: int = 0
    messages: List[SessionMessageRecord] = Field(default_factory=list)
    transcripts: List[SessionTranscriptRecord] = Field(default_factory=list)
    telemetry: List[SessionTelemetryRecord] = Field(default_factory=list)
    consultation_turns: List[ConsultationTurn] = Field(default_factory=list)
    structured_report: StructuredReport = Field(default_factory=StructuredReport)
    knowledge_hits: List[KnowledgeHit] = Field(default_factory=list)
    suggested_questions: List[str] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    sessions: List[str] = Field(default_factory=list)
    count: int = 0
    items: List[SessionSummary] = Field(default_factory=list)


class OrchestratorEvent(BaseModel):
    type: str
    text: Optional[str] = None
    language: Optional[str] = None
    languages: Optional[List[str]] = None
    is_code_mixed: Optional[bool] = None
    segments: Optional[List[TranscriptSegment]] = None
    tts_plan: Optional[List[str]] = None
    tts_segments: Optional[List[dict[str, Any]]] = None
    tts_language: Optional[str] = None
    provider: Optional[str] = None
    mime_type: Optional[str] = None
    sample_rate: Optional[int] = None
    audio_b64: Optional[str] = None
    error: Optional[str] = None
    speaker_role: Optional[str] = None
    consultation_mode: Optional[str] = None
    structured_report: Optional[StructuredReport] = None
    knowledge_hits: Optional[List[KnowledgeHit]] = None
    suggested_questions: Optional[List[str]] = None
