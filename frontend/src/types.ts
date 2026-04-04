export type DomainMode = "healthcare" | "financial";
export type TransportMode = "rest" | "websocket";

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
}

export interface TranscribeResponse {
  text: string;
  language: string;
  languages: string[];
  is_code_mixed: boolean;
  segments: TranscriptSegment[];
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
}

export interface LanguageInfoEvent {
  type: "language_info";
  languages: string[];
  dominant_language?: string;
  is_code_mixed?: boolean;
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
}

export interface AudioSkippedEvent {
  type: "audio_skipped";
  reason: string;
}

export interface TranscriptionEvent extends TranscribeResponse {
  type: "transcription";
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

export interface ReviewFieldDefinition {
  key: string;
  label: string;
  placeholder: string;
}

export interface AudioSocketConfig {
  sample_rate: number;
  channels: number;
  sample_width: number;
  encoding: string;
}

export interface ActivityItem {
  id: string;
  level: "info" | "warning" | "error";
  text: string;
  created_at: string;
}
