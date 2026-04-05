export type ConsultationMode = "consultation" | "follow_up";
export type SpeakerRole = "auto" | "patient" | "doctor" | "assistant" | "document";
export type AppView = "landing" | "consultation_text" | "consultation_voice" | "transcription";

export interface TranscriptLine {
  id: string;
  speaker: string;
  text: string;
  timestamp: string;
  language: string;
}

export interface RootInfo {
  service: string;
  version: string;
  status: string;
  model: string;
  features: string[];
}

export interface HealthResponse {
  status: string;
  model: string;
  uptime_seconds: number;
  sessions_active: number;
  tts_enabled: boolean;
  tts_ready: boolean;
  tts_providers: string[];
  tts_real_speech_ready: boolean;
  tts_real_providers: string[];
  errors: string[];
  warnings: string[];
}

export interface KnowledgeHit {
  topic: string;
  summary: string;
  source_name: string;
  source_url: string;
  keywords: string[];
  recommendation: string;
}

export interface StructuredReport {
  complaint_query: string;
  background_history: string;
  observations_responses: string;
  diagnosis_classification_status: string;
  action_plan_treatment_plan: string;
  verification_survey_responses: string;
  symptoms: string;
  past_history: string;
  clinical_observations: string;
  diagnosis: string;
  treatment_advice: string;
  immunization_data: string;
  pregnancy_data: string;
  risk_indicators: string;
  injury_mobility: string;
  ent_findings: string;
  risk_level: string;
  red_flags: string[];
  pending_questions: string[];
  care_summary: string;
}

export interface ConsultationTurn {
  id?: number | null;
  speaker_role: string;
  text: string;
  language: string;
  languages: string[];
  created_at: string;
}

export interface TranscriptSegment {
  index?: number | null;
  text: string;
  start_ms?: number | null;
  end_ms?: number | null;
  language?: string | null;
  languages?: string[] | null;
  dominant_language?: string | null;
  engine?: string | null;
  is_code_mixed?: boolean | null;
  is_final?: boolean;
}

export interface ChatResponse {
  text: string;
  language: string;
  languages: string[];
  is_code_mixed: boolean;
  session_id: string;
  speaker_role: string;
  consultation_mode: ConsultationMode;
  structured_report: StructuredReport;
  knowledge_hits: KnowledgeHit[];
  suggested_questions: string[];
}

export interface TranscribeResponse {
  text: string;
  language: string;
  languages: string[];
  is_code_mixed: boolean;
  segments: TranscriptSegment[];
  speaker_role: string;
  structured_report: StructuredReport;
  knowledge_hits: KnowledgeHit[];
  suggested_questions: string[];
}

export interface ReportExtractResponse {
  filename: string;
  text: string;
  structured_report: StructuredReport;
  knowledge_hits: KnowledgeHit[];
  dynamic_json: Record<string, unknown>;
  dynamic_issues: string[];
  dynamic_used_llm: boolean;
  dynamic_fallback_used: boolean;
}

export interface DynamicExtractResponse {
  result: Record<string, unknown>;
  normalized_schema: Record<string, unknown>;
  issues: string[];
  used_llm: boolean;
  fallback_used: boolean;
}

export interface TTSResponse {
  text: string;
  language: string;
  provider: string;
  mime_type: string;
  sample_rate: number;
  audio_b64: string;
}

export interface SessionSummary {
  session_id: string;
  created_at: string;
  updated_at: string;
  languages: string[];
  selected_language: string;
  message_count: number;
  transcript_count: number;
  telemetry_count: number;
  last_message: string;
  last_transcript: string;
}

export interface SessionListResponse {
  sessions: string[];
  count: number;
  items: SessionSummary[];
}

export interface SessionMessageRecord {
  id: number;
  role: string;
  content: string;
  created_at: string;
}

export interface SessionTranscriptRecord {
  id: number;
  source: string;
  text: string;
  dominant_language: string;
  languages: string[];
  is_code_mixed: boolean;
  segments: TranscriptSegment[];
  details: Record<string, unknown>;
  created_at: string;
}

export interface SessionTelemetryRecord {
  id: number;
  kind: string;
  name: string;
  status: string;
  latency_ms: number | null;
  error_message: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface SessionDetailResponse {
  session_id: string;
  created_at: string;
  updated_at: string;
  languages: string[];
  selected_language: string;
  message_count: number;
  transcript_count: number;
  telemetry_count: number;
  messages: SessionMessageRecord[];
  transcripts: SessionTranscriptRecord[];
  telemetry: SessionTelemetryRecord[];
  consultation_turns: ConsultationTurn[];
  structured_report: StructuredReport;
  knowledge_hits: KnowledgeHit[];
  suggested_questions: string[];
}

export interface LanguageInfoEvent {
  type: "language_info";
  languages: string[];
  dominant_language?: string;
  is_code_mixed?: boolean;
  speaker_role?: string;
  consultation_mode?: ConsultationMode;
}

export interface DeltaEvent {
  type: "delta";
  text: string;
}

export interface FinalEvent {
  type: "final";
  status?: string;
  text?: string;
  language?: string;
  languages?: string[];
  is_code_mixed?: boolean;
  tts_plan?: string[];
  tts_segments?: Array<{
    text: string;
    language?: string;
    languages?: string[];
  }>;
  tts_language?: string;
  provider?: string;
  mime_type?: string;
  sample_rate?: number;
  audio_b64?: string;
  segment_count?: number;
  speaker_role?: string;
  consultation_mode?: ConsultationMode;
  structured_report?: StructuredReport;
  knowledge_hits?: KnowledgeHit[];
  suggested_questions?: string[];
}

export interface ErrorEvent {
  type: "error";
  error: string;
}

export interface AudioConfigEvent {
  type: "audio_config";
  sample_rate: number;
  channels: number;
  sample_width: number;
  encoding: string;
  max_chunk_bytes: number;
  consultation_mode?: ConsultationMode;
}

export interface AudioSkippedEvent {
  type: "audio_skipped";
  reason: string;
}

export interface TranscriptionEvent extends TranscribeResponse {
  type: "transcription";
  consultation_mode?: ConsultationMode;
}

export interface PongEvent {
  type: "pong";
}

export interface AudioResetEvent {
  type: "audio_reset";
}

export interface TTSInfoEvent {
  type: "tts_info";
  session_id: string;
  segment_count: number;
  available_providers: string[];
}

export interface AudioChunkEvent {
  type: "audio_chunk";
  segment_index: number;
  text: string;
  language: string;
  provider: string;
  mime_type: string;
  sample_rate: number;
  duration_ms?: number;
  audio_b64: string;
}

export type TextStreamEvent = LanguageInfoEvent | DeltaEvent | FinalEvent | ErrorEvent;

export type AudioStreamEvent =
  | AudioConfigEvent
  | TranscriptionEvent
  | LanguageInfoEvent
  | DeltaEvent
  | FinalEvent
  | AudioSkippedEvent
  | AudioResetEvent
  | PongEvent
  | ErrorEvent;

export type TTSStreamEvent = TTSInfoEvent | AudioChunkEvent | FinalEvent | ErrorEvent;

export interface AudioSocketConfig {
  sample_rate: number;
  channels: number;
  sample_width: number;
  encoding: string;
  consultation_mode?: ConsultationMode;
  speaker_role?: string;
}

export interface ActivityItem {
  id: string;
  level: "info" | "warning" | "error";
  text: string;
  created_at: string;
}
