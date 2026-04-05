import {
  startTransition,
  useDeferredValue,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type Dispatch,
  type FormEvent,
  type MutableRefObject,
  type SetStateAction
} from "react";

import {
  audioUrlFromBase64,
  clearSession,
  createAudioSocketSession,
  extractReportFile,
  getHealth,
  getRootInfo,
  getSessionDetail,
  getSessions,
  startConsultation,
  streamTextChat,
  transcribeFile,
  ttsRest
} from "./api";
import { BrowserAudioCapture, type VoiceActivityState } from "./audio";
import type {
  ActivityItem,
  AppView,
  AudioConfigEvent,
  AudioSocketConfig,
  AudioStreamEvent,
  ConsultationMode,
  FinalEvent,
  HealthResponse,
  KnowledgeHit,
  LanguageInfoEvent,
  ReportExtractResponse,
  RootInfo,
  SessionDetailResponse,
  SessionSummary,
  SpeakerRole,
  ResponseLanguageChoice,
  StructuredReport,
  TranscribeResponse,
  TranscriptLine,
  TranscriptionEvent
} from "./types";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";
const STORAGE_KEYS = {
  baseUrl: "nudiscribe.health.baseUrl",
  sessionId: "nudiscribe.health.sessionId",
  consultationMode: "nudiscribe.health.consultationMode",
  speakerRole: "nudiscribe.health.speakerRole",
  responseLanguage: "nudiscribe.health.responseLanguage",
  autoSpeak: "nudiscribe.health.autoSpeak"
};

const REPORT_FIELDS: Array<{ key: keyof StructuredReport; label: string; rows?: number }> = [
  { key: "complaint_query", label: "Complaint / Query" },
  { key: "background_history", label: "Background History" },
  { key: "observations_responses", label: "Observations / Responses" },
  { key: "diagnosis_classification_status", label: "Diagnosis / Classification / Status" },
  { key: "action_plan_treatment_plan", label: "Action Plan / Treatment Plan" },
  { key: "verification_survey_responses", label: "Verification / Survey Responses" },
  { key: "symptoms", label: "Symptoms" },
  { key: "past_history", label: "Past History" },
  { key: "clinical_observations", label: "Clinical Observations" },
  { key: "diagnosis", label: "Diagnosis" },
  { key: "treatment_advice", label: "Treatment Advice" },
  { key: "immunization_data", label: "Immunization Data" },
  { key: "pregnancy_data", label: "Pregnancy Data" },
  { key: "risk_indicators", label: "Risk Indicators" },
  { key: "injury_mobility", label: "Injury & Mobility" },
  { key: "ent_findings", label: "ENT Findings" },
  { key: "care_summary", label: "Care Summary", rows: 4 }
];

type CaptureState = "idle" | "connecting" | "recording" | "transcribing" | "responding" | "error";
type AssistantSpeechMeta = {
  language?: string;
  languages?: string[];
};

const LANG_DISPLAY_NAMES: Record<string, string> = {
  en: "English",
  hi: "Hindi",
  kn: "Kannada",
  auto: "Auto",
  unknown: "Unknown",
};

function getLanguageLabel(
  detectedInputLang?: string,
  isCodeMixed?: boolean,
  languages?: string[]
): { label: string; badgeClass: string } {
  if (isCodeMixed && languages && languages.length > 1) {
    const langCodes = languages
      .map((l) => l.toUpperCase())
      .join("+");
    return { label: `Code-Mixed (${langCodes})`, badgeClass: "lang-badge-mixed" };
  }
  const lang = detectedInputLang || "auto";
  switch (lang) {
    case "en":
      return { label: "English", badgeClass: "lang-badge-en" };
    case "hi":
      return { label: "Hindi", badgeClass: "lang-badge-hi" };
    case "kn":
      return { label: "Kannada", badgeClass: "lang-badge-kn" };
    default:
      return { label: LANG_DISPLAY_NAMES[lang] || lang.toUpperCase(), badgeClass: "lang-badge" };
  }
}

const NUDI_WORDMARKS = [
  { script: "\u0ca8\u0cc1\u0ca1\u0cbf", language: "Kannada" },
  { script: "\u0928\u0941\u0921\u0940", language: "Hindi" },
  { script: "\u0c28\u0c41\u0c21\u0c3f", language: "Telugu" },
  { script: "\u0ba8\u0bc1\u0b9f\u0bbf", language: "Tamil" },
  { script: "\u0d28\u0d41\u0d1f\u0d3f", language: "Malayalam" },
  { script: "\u09a8\u09c1\u09a1\u09bf", language: "Bengali" },
  { script: "\u0a28\u0a41\u0a21\u0a40", language: "Punjabi" },
  { script: "\u0b28\u0b41\u0b21\u0b3f", language: "Odia" },
];
function blankReport(): StructuredReport {
  return {
    complaint_query: "",
    background_history: "",
    observations_responses: "",
    diagnosis_classification_status: "",
    action_plan_treatment_plan: "",
    verification_survey_responses: "",
    symptoms: "",
    past_history: "",
    clinical_observations: "",
    diagnosis: "",
    treatment_advice: "",
    immunization_data: "",
    pregnancy_data: "",
    risk_indicators: "",
    injury_mobility: "",
    ent_findings: "",
    risk_level: "routine",
    red_flags: [],
    pending_questions: [],
    care_summary: ""
  };
}

function buildSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `care-${crypto.randomUUID().slice(0, 8)}`;
  }
  return `care-${Date.now().toString(36)}`;
}

function sanitizeBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, "");
  return trimmed || DEFAULT_BASE_URL;
}

function resolveResponseLanguage(choice: ResponseLanguageChoice): string | undefined {
  return choice === "auto" ? undefined : choice;
}

export default function App() {
  const initialBaseUrl = window.localStorage.getItem(STORAGE_KEYS.baseUrl) || DEFAULT_BASE_URL;
  const initialSessionId = window.localStorage.getItem(STORAGE_KEYS.sessionId) || buildSessionId();
  const initialMode =
    (window.localStorage.getItem(STORAGE_KEYS.consultationMode) as ConsultationMode) || "consultation";
  const initialSpeakerRole =
    (window.localStorage.getItem(STORAGE_KEYS.speakerRole) as SpeakerRole) || "auto";
  const initialResponseLanguage =
    (window.localStorage.getItem(STORAGE_KEYS.responseLanguage) as ResponseLanguageChoice) || "auto";
  const initialAutoSpeak = window.localStorage.getItem(STORAGE_KEYS.autoSpeak) !== "false";

  // -- View state --
  const [currentView, setCurrentView] = useState<AppView>("landing");

  const [baseUrl, setBaseUrl] = useState(initialBaseUrl);
  const [baseUrlDraft, setBaseUrlDraft] = useState(initialBaseUrl);
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [consultationMode, setConsultationMode] = useState<ConsultationMode>(initialMode);
  const [speakerRole, setSpeakerRole] = useState<SpeakerRole>(initialSpeakerRole);
  const [responseLanguage, setResponseLanguage] = useState<ResponseLanguageChoice>(initialResponseLanguage);
  const [autoSpeak, setAutoSpeak] = useState(initialAutoSpeak);
  const [wordmarkIndex, setWordmarkIndex] = useState(0);
  const [sessionSyncing, setSessionSyncing] = useState(false);

  const [serviceInfo, setServiceInfo] = useState<RootInfo | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionDetail, setSessionDetail] = useState<SessionDetailResponse | null>(null);

  const [textInput, setTextInput] = useState("");
  const [textBusy, setTextBusy] = useState(false);
  const [assistantDraft, setAssistantDraft] = useState("");
  const [lastResponse, setLastResponse] = useState<FinalEvent | null>(null);
  const [lastTranscription, setLastTranscription] = useState<TranscriptionEvent | null>(null);
  const [inputLanguageInfo, setInputLanguageInfo] = useState<LanguageInfoEvent | null>(null);
  const [captureState, setCaptureState] = useState<CaptureState>("idle");
  const [audioConfig, setAudioConfig] = useState<AudioConfigEvent | null>(null);
  const [micLevel, setMicLevel] = useState(0);
  const [vadState, setVadState] = useState<VoiceActivityState | null>(null);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [capturePreviewUrl, setCapturePreviewUrl] = useState("");
  const [capturePreviewMeta, setCapturePreviewMeta] = useState("");

  const [audioUploadResult, setAudioUploadResult] = useState<TranscribeResponse | null>(null);
  const [reportUploadResult, setReportUploadResult] = useState<ReportExtractResponse | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [ttsBusy, setTtsBusy] = useState(false);
  const [ttsPaused, setTtsPaused] = useState(false);
  const [ttsAudioUrl, setTtsAudioUrl] = useState("");
  const [ttsMeta, setTtsMeta] = useState("");

  const [reportDraft, setReportDraft] = useState<StructuredReport>(blankReport());
  const [activities, setActivities] = useState<ActivityItem[]>([]);

  // Transcription mode state
  const [transcriptLines, setTranscriptLines] = useState<TranscriptLine[]>([]);
  const [transcriptText, setTranscriptText] = useState("");
  const [transcriptRecording, setTranscriptRecording] = useState(false);

  const captureRef = useRef<BrowserAudioCapture | null>(null);
  const audioSocketRef = useRef<ReturnType<typeof createAudioSocketSession> | null>(null);
  const audioTimerRef = useRef<number | null>(null);
  const speechRunRef = useRef(0);
  const speechQueueRef = useRef<Array<{ url: string; meta: string }>>([]);
  const speechUrlsRef = useRef<string[]>([]);
  const speechAudioRef = useRef<HTMLAudioElement | null>(null);
  const speechMetaRef = useRef<AssistantSpeechMeta>({ language: undefined, languages: [] });
  const speechChainRef = useRef<Promise<void>>(Promise.resolve());
  const pendingSpeechJobsRef = useRef(0);
  const playbackActiveRef = useRef(false);
  const pausedSpeechRef = useRef(false);
  const recordedClipRef = useRef<Blob | null>(null);
  const latestVoiceFinalRef = useRef<FinalEvent | null>(null);
  const latestVoiceTranscriptionRef = useRef<TranscriptionEvent | null>(null);
  const deferredSessionDetail = useDeferredValue(sessionDetail);
  const deferredActivities = useDeferredValue(activities);

  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.baseUrl, baseUrl); }, [baseUrl]);
  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.sessionId, sessionId); }, [sessionId]);
  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.consultationMode, consultationMode); }, [consultationMode]);
  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.speakerRole, speakerRole); }, [speakerRole]);
  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.responseLanguage, responseLanguage); }, [responseLanguage]);
  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.autoSpeak, String(autoSpeak)); }, [autoSpeak]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setWordmarkIndex((current) => (current + 1) % NUDI_WORDMARKS.length);
    }, 2000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function refreshControlPlane() {
      try {
        const [rootPayload, healthPayload, sessionPayload] = await Promise.all([
          getRootInfo(baseUrl), getHealth(baseUrl), getSessions(baseUrl)
        ]);
        if (cancelled) return;
        startTransition(() => {
          setServiceInfo(rootPayload);
          setHealth(healthPayload);
          setSessions(sessionPayload.items || []);
        });
      } catch (error) {
        if (!cancelled) pushActivity(setActivities, "error", `Control refresh failed: ${formatError(error)}`);
      }
    }
    refreshControlPlane();
    const interval = window.setInterval(refreshControlPlane, 15000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [baseUrl]);

  useEffect(() => {
    let cancelled = false;
    async function refreshSession() {
      try {
        const payload = await getSessionDetail(baseUrl, sessionId);
        if (cancelled) return;
        startTransition(() => {
          setSessionDetail(payload);
          setReportDraft(payload.structured_report || blankReport());
        });
      } catch (error) {
        if (!cancelled && String(error).toLowerCase().indexOf("not found") === -1) {
          pushActivity(setActivities, "warning", `Session refresh failed: ${formatError(error)}`);
        }
      }
    }
    refreshSession();
    return () => { cancelled = true; };
  }, [baseUrl, sessionId]);

  useEffect(() => {
    return () => {
      clearGeneratedAudio();
      clearAudioTimer(audioTimerRef);
      audioSocketRef.current?.close();
    };
  }, []);

  async function refreshSessionDetail(options?: { background?: boolean }) {
    if (options?.background) {
      setSessionSyncing(true);
    }
    try {
      const payload = await getSessionDetail(baseUrl, sessionId);
      startTransition(() => {
        setSessionDetail(payload);
        setReportDraft(payload.structured_report || blankReport());
      });
    } catch (error) {
      pushActivity(setActivities, "warning", `Session refresh failed: ${formatError(error)}`);
    } finally {
      if (options?.background) {
        setSessionSyncing(false);
      }
    }
  }

  async function handleApplyBaseUrl(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextBaseUrl = sanitizeBaseUrl(baseUrlDraft);
    setBaseUrl(nextBaseUrl);
    pushActivity(setActivities, "info", `Backend URL set to ${nextBaseUrl}.`);
  }

  async function handleStartConsultation() {
    try {
      const preferredLanguage = resolveResponseLanguage(responseLanguage);
      const response = await startConsultation(baseUrl, {
        session_id: sessionId,
        consultation_mode: consultationMode,
        response_language: preferredLanguage
      });
      const speechRunId = beginAssistantSpeechRun({
        language: preferredLanguage || response.language,
        languages: response.languages
      });
      setLastResponse(syntheticFinal(response));
      setAssistantDraft("");
      void refreshSessionDetail({ background: true });
      pushActivity(setActivities, "info", `${consultationMode === "follow_up" ? "Follow-up" : "Consultation"} flow started.`);
      if (autoSpeak) {
        queueAssistantSpeechResponse(speechRunId, syntheticFinal(response));
      }
    } catch (error) {
      pushActivity(setActivities, "error", `Unable to start consultation: ${formatError(error)}`);
    }
  }

  async function handleTextSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanedText = textInput.trim();
    if (!cleanedText || textBusy) return;

    await submitConsultationTurn(cleanedText, {
      speakerRoleHint: speakerRole === "auto" ? undefined : speakerRole,
      activityText: `Captured ${speakerRole === "auto" ? "auto-detected" : speakerRole} text turn.`,
    });
    setTextInput("");
  }

  async function handleAudioUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || uploadBusy) return;
    await handleConsultationAudioFile(file, file.name || "uploaded audio");
  }

  async function handleReportUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || reportBusy) return;
    setReportBusy(true);
    try {
      const result = await extractReportFile(baseUrl, file, sessionId);
      setReportUploadResult(result);
      setReportDraft(result.structured_report);
      void refreshSessionDetail({ background: true });
      pushActivity(setActivities, "info", `Extracted structured healthcare report from ${result.filename}.`);
    } catch (error) {
      pushActivity(setActivities, "error", `Report extraction failed: ${formatError(error)}`);
    } finally {
      setReportBusy(false);
    }
  }

  async function startRecording() {
    if (captureState !== "idle") return;
    setCaptureState("connecting");
    setVadState(null);
    latestVoiceFinalRef.current = null;
    latestVoiceTranscriptionRef.current = null;
    const preferredLanguage = resolveResponseLanguage(responseLanguage);
    const speechRunId = beginAssistantSpeechRun({ language: preferredLanguage });
    setAssistantDraft("");
    setLastResponse(null);
    try {
      const capture = new BrowserAudioCapture();
      captureRef.current = capture;
      const prepared = await capture.prepare();
      const socketConfig: AudioSocketConfig = {
        sample_rate: prepared.sampleRate, channels: prepared.channels,
        sample_width: prepared.sampleWidth, encoding: "pcm_s16le",
        consultation_mode: consultationMode,
        speaker_role: speakerRole === "auto" ? undefined : speakerRole,
        response_language: preferredLanguage
      };
      const socketSession = createAudioSocketSession(baseUrl, sessionId, socketConfig,
        (eventPayload: AudioStreamEvent) => {
          if (eventPayload.type === "audio_config") setAudioConfig(eventPayload);
          if (eventPayload.type === "transcription") {
            latestVoiceTranscriptionRef.current = eventPayload;
            setLastTranscription(eventPayload);
            setCaptureState("responding");
          }
          if (eventPayload.type === "language_info") {
            speechMetaRef.current = {
              language: eventPayload.dominant_language || speechMetaRef.current.language,
              languages: eventPayload.languages || []
            };
          }
          if (eventPayload.type === "delta") {
            setAssistantDraft((current) => current + eventPayload.text);
            setCaptureState("responding");
          }
          if (eventPayload.type === "final") {
            latestVoiceFinalRef.current = eventPayload;
            speechMetaRef.current = {
              language: eventPayload.tts_language || eventPayload.language,
              languages: eventPayload.languages || []
            };
            if (autoSpeak) {
              queueAssistantSpeechResponse(speechRunId, eventPayload);
            }
            setLastResponse(eventPayload);
            setAssistantDraft("");
            setCaptureState("idle");
          }
          if (eventPayload.type === "audio_skipped") setCaptureState("idle");
          if (eventPayload.type === "error") { setCaptureState("error"); pushActivity(setActivities, "error", eventPayload.error); }
        }
      );
      audioSocketRef.current = socketSession;
      const readyEvent = await socketSession.ready;
      if (readyEvent.type !== "audio_config") throw new Error("Unexpected audio negotiation event.");
      await capture.start({
        onChunk: (chunk) => socketSession.sendChunk(chunk),
        onLevel: (rms) => setMicLevel(rms),
        onVadState: (state) => setVadState(state)
      });
      clearAudioTimer(audioTimerRef);
      audioTimerRef.current = window.setInterval(() => { setRecordingSeconds(capture.getElapsedSeconds()); }, 100);
      setCaptureState("recording");
      pushActivity(setActivities, "info", `Recording live audio for ${consultationMode === "follow_up" ? "follow-up" : "consultation"} mode.`);
    } catch (error) {
      captureRef.current = null;
      audioSocketRef.current?.close();
      audioSocketRef.current = null;
      clearAudioTimer(audioTimerRef);
      setVadState(null);
      setCaptureState("error");
      pushActivity(setActivities, "error", `Unable to start recording: ${formatError(error)}`);
    }
  }

  async function stopRecording() {
    const capture = captureRef.current;
    const socketSession = audioSocketRef.current;
    if (!capture || !socketSession) return;
    setCaptureState("transcribing");
    clearAudioTimer(audioTimerRef);
    try {
      const stopResult = await capture.stop();
      if (stopResult.blob) {
        recordedClipRef.current = stopResult.blob;
        setCapturePreviewUrl((current) => { if (current) URL.revokeObjectURL(current); return URL.createObjectURL(stopResult.blob); });
        setCapturePreviewMeta(`${stopResult.sampleRate} Hz · ${formatDurationSeconds(stopResult.durationSeconds)}`);
      } else {
        recordedClipRef.current = null;
      }
      socketSession.commit();
      const completion = await socketSession.completion;
      socketSession.close();
      audioSocketRef.current = null;
      captureRef.current = null;
      setMicLevel(0);
      setVadState(null);
      setRecordingSeconds(0);
      if (completion.type === "final") {
        setLastResponse(completion);
        void refreshSessionDetail({ background: true });
        pushActivity(setActivities, "info", `Live turn completed as ${completion.speaker_role || "unknown"} speech.`);
      } else if (completion.type === "stream_complete") {
        const streamStatus = completion.status || "";
        const streamError = typeof completion.details?.error === "string" ? completion.details.error : "";
        if (streamStatus === "error") {
          setCaptureState("error");
          pushActivity(setActivities, "error", streamError || "Live audio consultation did not complete.");
        } else if (latestVoiceFinalRef.current) {
          setLastResponse(latestVoiceFinalRef.current);
          void refreshSessionDetail({ background: true });
          setCaptureState("idle");
        } else {
          setCaptureState("idle");
          pushActivity(setActivities, "warning", "No assistant reply arrived from live voice. Use the recorded-audio upload fallback below.");
        }
      } else if (completion.type === "audio_skipped") {
        pushActivity(setActivities, "warning", "Captured audio was treated as silence.");
        setCaptureState("idle");
      } else if (completion.type === "error") {
        setCaptureState("error");
      }
    } catch (error) {
      captureRef.current = null;
      audioSocketRef.current?.close();
      audioSocketRef.current = null;
      setVadState(null);
      setCaptureState("error");
      pushActivity(setActivities, "error", `Unable to stop recording: ${formatError(error)}`);
    }
  }

  // -- Transcription mode (two-speaker, no assistant) --
  async function startTranscriptionRecording() {
    if (transcriptRecording) return;
    setTranscriptRecording(true);
    setCaptureState("connecting");
    setVadState(null);
    try {
      const capture = new BrowserAudioCapture();
      captureRef.current = capture;
      const prepared = await capture.prepare();
      const socketConfig: AudioSocketConfig = {
        sample_rate: prepared.sampleRate, channels: prepared.channels,
        sample_width: prepared.sampleWidth, encoding: "pcm_s16le",
        consultation_mode: "consultation",
        transcription_only: true,
        turn_timeout_seconds: 0.85
      };
      let turnCount = 0;
      const socketSession = createAudioSocketSession(baseUrl, sessionId, socketConfig,
        (eventPayload: AudioStreamEvent) => {
          if (eventPayload.type === "audio_config") setAudioConfig(eventPayload);
          if (eventPayload.type === "transcription") {
            turnCount += 1;
            const speakerIndex = turnCount % 2 === 1 ? 1 : 2;
            const speaker = `Speaker ${speakerIndex}`;
            const detectedInputLang = eventPayload.detected_input_language || eventPayload.language || eventPayload.languages?.[0] || "auto";
            const detectedLanguage = eventPayload.language || eventPayload.languages?.[0] || "auto";
            const codeMixed = eventPayload.is_code_mixed || false;
            const languageInfo = getLanguageLabel(detectedInputLang, codeMixed, eventPayload.languages);
            const newLine: TranscriptLine = {
              id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}`,
              speaker,
              speaker_role: eventPayload.speaker_role || undefined,
              text: eventPayload.text,
              timestamp: new Date().toLocaleTimeString(),
              language: detectedLanguage,
              detected_input_language: detectedInputLang,
              is_code_mixed: codeMixed,
            };
            setTranscriptLines((prev) => [...prev, newLine]);
            setTranscriptText((prev) => {
              const speakerLabel = newLine.speaker_role ? `${newLine.speaker} (${newLine.speaker_role})` : newLine.speaker;
              return prev + `[${newLine.timestamp}] ${speakerLabel} [${languageInfo.label.toUpperCase()}]: ${newLine.text}\n`;
            });
            setCaptureState("recording");
          }
          if (eventPayload.type === "final") setCaptureState("recording");
          if (eventPayload.type === "audio_skipped") setCaptureState("recording");
          if (eventPayload.type === "error") { pushActivity(setActivities, "error", eventPayload.error); }
        }
      );
      audioSocketRef.current = socketSession;
      await socketSession.ready;
      await capture.start({
        onChunk: (chunk) => socketSession.sendChunk(chunk),
        onLevel: (rms) => setMicLevel(rms),
        onVadState: (state) => setVadState(state)
      });
      clearAudioTimer(audioTimerRef);
      audioTimerRef.current = window.setInterval(() => { setRecordingSeconds(capture.getElapsedSeconds()); }, 100);
      setCaptureState("recording");
      pushActivity(setActivities, "info", "Live two-speaker transcription started.");
    } catch (error) {
      captureRef.current = null;
      audioSocketRef.current?.close();
      audioSocketRef.current = null;
      clearAudioTimer(audioTimerRef);
      setVadState(null);
      setTranscriptRecording(false);
      setCaptureState("error");
      pushActivity(setActivities, "error", `Unable to start transcription: ${formatError(error)}`);
    }
  }

  async function stopTranscriptionRecording() {
    const capture = captureRef.current;
    const socketSession = audioSocketRef.current;
    clearAudioTimer(audioTimerRef);
    setTranscriptRecording(false);
    setCaptureState("idle");
    setMicLevel(0);
    setVadState(null);
    setRecordingSeconds(0);
    if (capture) { try { await capture.stop(); } catch { /* ignore */ } captureRef.current = null; }
    if (socketSession) {
      try { socketSession.commit(); await socketSession.completion; } catch { /* ignore */ }
      socketSession.close();
      audioSocketRef.current = null;
    }
    pushActivity(setActivities, "info", "Live transcription stopped.");
  }

  function downloadTranscript() {
    const blob = new Blob([transcriptText], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `transcription_${sessionId}_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function submitConsultationTurn(
    cleanedText: string,
    options?: {
      speakerRoleHint?: string;
      detectedLanguageHint?: string;
      activityText?: string;
    }
  ) {
    if (!cleanedText.trim()) {
      return;
    }

    setTextBusy(true);
    const explicitLanguage = resolveResponseLanguage(responseLanguage);
    const detectedLanguage =
      options?.detectedLanguageHint && ["en", "hi", "kn"].includes(options.detectedLanguageHint)
        ? options.detectedLanguageHint
        : undefined;
    const responseLanguageHint = explicitLanguage || detectedLanguage;
    const speechRunId = beginAssistantSpeechRun({ language: responseLanguageHint });
    setAssistantDraft("");
    setLastResponse(null);

    try {
      const finalEvent = await streamTextChat(
        baseUrl,
        sessionId,
        {
          text: cleanedText,
          speaker_role: options?.speakerRoleHint,
          consultation_mode: consultationMode,
          response_language: responseLanguageHint,
        },
        (eventPayload) => {
          if (eventPayload.type === "language_info") {
            speechMetaRef.current = {
              language: eventPayload.dominant_language || speechMetaRef.current.language,
              languages: eventPayload.languages || []
            };
            setInputLanguageInfo(eventPayload);
          }
          if (eventPayload.type === "delta") {
            setAssistantDraft((current) => current + eventPayload.text);
          }
          if (eventPayload.type === "final") {
            speechMetaRef.current = {
              language: eventPayload.tts_language || eventPayload.language,
              languages: eventPayload.languages || []
            };
            if (autoSpeak) {
              queueAssistantSpeechResponse(speechRunId, eventPayload);
            }
            setLastResponse(eventPayload);
            setAssistantDraft("");
          }
        }
      );
      setLastResponse(finalEvent);
      void refreshSessionDetail({ background: true });
      if (options?.activityText) {
        pushActivity(setActivities, "info", options.activityText);
      }
    } catch (error) {
      pushActivity(setActivities, "error", `Consultation failed: ${formatError(error)}`);
    } finally {
      setTextBusy(false);
    }
  }

  async function handleConsultationAudioFile(file: File, sourceLabel: string) {
    setUploadBusy(true);
    try {
      const result = await transcribeFile(baseUrl, file, sessionId);
      setAudioUploadResult(result);
      const transcriptionEvent: TranscriptionEvent = { type: "transcription", ...result, consultation_mode: consultationMode };
      setLastTranscription(transcriptionEvent);
      latestVoiceTranscriptionRef.current = transcriptionEvent;
      void refreshSessionDetail({ background: true });

      if (currentView === "consultation_voice") {
        await submitConsultationTurn(result.text, {
          speakerRoleHint: result.speaker_role || undefined,
          detectedLanguageHint: result.language,
          activityText: `Uploaded ${sourceLabel} and generated consultation output in ${result.language.toUpperCase()}.`,
        });
      } else {
        pushActivity(setActivities, "info", `Uploaded ${sourceLabel} transcribed as ${result.speaker_role} speech.`);
      }
    } catch (error) {
      pushActivity(setActivities, "error", `Audio upload failed: ${formatError(error)}`);
    } finally {
      setUploadBusy(false);
    }
  }

  async function uploadRecordedConsultationAudio() {
    const blob = recordedClipRef.current;
    if (!blob || uploadBusy) {
      return;
    }

    const file = new File(
      [blob],
      `recorded_consultation_${sessionId}_${Date.now()}.wav`,
      { type: blob.type || "audio/wav" }
    );
    await handleConsultationAudioFile(file, "recorded audio");
  }

  async function handleClearSession() {
    try {
      await clearSession(baseUrl, sessionId);
      setSessionDetail(null); setReportDraft(blankReport()); setLastResponse(null);
      setLastTranscription(null); setAudioUploadResult(null); setReportUploadResult(null);
      setAssistantDraft(""); clearGeneratedAudio(); setVadState(null); setInputLanguageInfo(null);
      pushActivity(setActivities, "warning", `Cleared session ${sessionId}.`);
    } catch (error) {
      pushActivity(setActivities, "error", `Unable to clear session: ${formatError(error)}`);
    }
  }

  function handleNewSession() {
    const nextSessionId = buildSessionId();
    setSessionId(nextSessionId); setSessionDetail(null); setReportDraft(blankReport());
    setLastResponse(null); setLastTranscription(null); setAudioUploadResult(null);
    setReportUploadResult(null); setAssistantDraft(""); clearGeneratedAudio(); setVadState(null); setInputLanguageInfo(null);
    setTranscriptLines([]); setTranscriptText("");
    pushActivity(setActivities, "info", `Created new healthcare session ${nextSessionId}.`);
  }

  function beginAssistantSpeechRun(meta?: AssistantSpeechMeta): number {
    clearAssistantAudio();
    const nextRunId = speechRunRef.current + 1;
    speechRunRef.current = nextRunId;
    speechMetaRef.current = {
      language: meta?.language,
      languages: meta?.languages || []
    };
    return nextRunId;
  }

  function extractAssistantSpeechChunks(
    text: string
  ): { chunks: string[]; remainder: string } {
    const normalized = text.replace(/\s+/g, " ").trim();
    if (!normalized) {
      return { chunks: [], remainder: "" };
    }

    const parts = normalized
      .split(/(?<=[.!?।])\s+/)
      .map((part) => part.trim())
      .filter(Boolean);

    if (parts.length === 0) {
      return { chunks: [normalized], remainder: "" };
    }

    return {
      chunks: parts,
      remainder: ""
    };
  }

  function queueAssistantSpeechResponse(runId: number, response: FinalEvent) {
    if (!autoSpeak || runId !== speechRunRef.current) {
      return;
    }

    const fallbackLanguage = response.tts_language || response.language || speechMetaRef.current.language;
    const fallbackLanguages = response.languages || speechMetaRef.current.languages || [];
    const segments = response.tts_segments?.length
      ? response.tts_segments
          .map((segment) => ({
            text: segment.text.trim(),
            language: segment.language || fallbackLanguage,
            languages: segment.languages || fallbackLanguages
          }))
          .filter((segment) => segment.text)
      : extractAssistantSpeechChunks(response.text || "").chunks.map((text) => ({
          text,
          language: fallbackLanguage,
          languages: fallbackLanguages
        }));

    if (segments.length === 0) {
      return;
    }

    for (const segment of segments) {
      queueAssistantSpeechSegment(runId, segment.text, segment.language, segment.languages);
    }
  }

  function queueAssistantSpeechSegment(
    runId: number,
    text: string,
    language?: string,
    languages?: string[]
  ) {
    const cleaned = text.trim();
    if (!cleaned || runId !== speechRunRef.current) {
      return;
    }

    pendingSpeechJobsRef.current += 1;
    setTtsBusy(true);

    speechChainRef.current = speechChainRef.current
      .catch(() => undefined)
      .then(async () => {
        const response = await ttsRest(baseUrl, { text: cleaned, language, languages: languages || [] });
        if (runId !== speechRunRef.current) {
          return;
        }

        const url = audioUrlFromBase64(response.audio_b64, response.mime_type);
        speechUrlsRef.current.push(url);
        speechQueueRef.current.push({
          url,
          meta: `${response.provider} · ${response.language} · ${response.sample_rate} Hz`
        });
        playNextAssistantSegment();
      })
      .catch((error) => {
        if (runId === speechRunRef.current) {
          pushActivity(setActivities, "warning", `Assistant voice playback failed: ${formatError(error)}`);
        }
      })
      .finally(() => {
        pendingSpeechJobsRef.current = Math.max(0, pendingSpeechJobsRef.current - 1);
        if (pendingSpeechJobsRef.current === 0) {
          setTtsBusy(false);
        }
      });
  }

  function playNextAssistantSegment() {
    if (playbackActiveRef.current || pausedSpeechRef.current) {
      return;
    }

    const nextItem = speechQueueRef.current.shift();
    if (!nextItem) {
      return;
    }

    playbackActiveRef.current = true;
    setTtsAudioUrl(nextItem.url);
    setTtsMeta(nextItem.meta);

    const audio = new Audio(nextItem.url);
    speechAudioRef.current = audio;
    const onComplete = () => {
      playbackActiveRef.current = false;
      speechAudioRef.current = null;
      playNextAssistantSegment();
    };

    audio.addEventListener("ended", onComplete, { once: true });
    audio.addEventListener("error", onComplete, { once: true });
    audio.play().catch(() => {
      onComplete();
    });
  }

  function pauseAssistantSpeech() {
    const audio = speechAudioRef.current;
    if (!audio || audio.paused) {
      return;
    }

    pausedSpeechRef.current = true;
    setTtsPaused(true);
    audio.pause();
  }

  function resumeAssistantSpeech() {
    const audio = speechAudioRef.current;
    pausedSpeechRef.current = false;
    setTtsPaused(false);

    if (audio) {
      audio.play().catch(() => undefined);
      return;
    }

    if (speechQueueRef.current.length > 0) {
      playNextAssistantSegment();
    }
  }

  function stopAssistantSpeech() {
    clearAssistantAudio(true);
  }

  function clearAssistantAudio(invalidateRun = false) {
    if (invalidateRun) {
      speechRunRef.current += 1;
    }
    playbackActiveRef.current = false;
    pausedSpeechRef.current = false;
    speechQueueRef.current = [];
    pendingSpeechJobsRef.current = 0;
    speechAudioRef.current?.pause();
    speechAudioRef.current = null;
    speechChainRef.current = Promise.resolve();
    for (const url of speechUrlsRef.current) {
      URL.revokeObjectURL(url);
    }
    speechUrlsRef.current = [];
    setTtsAudioUrl("");
    setTtsMeta("");
    setTtsBusy(false);
    setTtsPaused(false);
  }

  function clearGeneratedAudio() {
    clearAssistantAudio(true);
    recordedClipRef.current = null;
    setCapturePreviewUrl((current) => { if (current) URL.revokeObjectURL(current); return ""; });
    setCapturePreviewMeta("");
  }

  const currentWordmark = NUDI_WORDMARKS[wordmarkIndex];
  const displayedReport = reportUploadResult?.structured_report || deferredSessionDetail?.structured_report || blankReport();
  const displayedKnowledgeHits = lastResponse?.knowledge_hits || reportUploadResult?.knowledge_hits || deferredSessionDetail?.knowledge_hits || [];
  const displayedQuestions = lastResponse?.suggested_questions || lastTranscription?.suggested_questions || deferredSessionDetail?.suggested_questions || [];
  const consultationTurns = deferredSessionDetail?.consultation_turns || [];
  const detectedLang = lastResponse?.language || lastTranscription?.language || deferredSessionDetail?.selected_language || "auto";
  const assistantLanguage = responseLanguage === "auto" ? detectedLang : responseLanguage;
  const ttsStack = health?.tts_real_providers?.length
    ? health.tts_real_providers.join(" + ")
    : health?.tts_providers?.join(" + ") || "Pending voice runtime";
  const asrStack = "Whisper + Indic ASR";
  const syncStatusLabel = sessionSyncing ? "Background sync running" : "History synced";
  const responseStatusLabel = textBusy
    ? "Streaming response"
    : captureState === "recording" || captureState === "responding"
      ? "Live voice path"
      : transcriptRecording
        ? "Turn detection active"
        : "Ready";
  const recentActivityItems = deferredActivities.slice(0, 4);

  // ======================== RENDER ========================

  if (currentView === "landing") {
    return (
      <div className="page-shell">
        <header className="hero enterprise-hero">
          <div className="hero-primary">
            <div className="brand-row">
              <div className="wordmark-stage" aria-label={`Nudi wordmark in ${currentWordmark.language}`}>
                <span className="wordmark-label">Nudi across Indian scripts</span>
                <div className="wordmark-window">
                  <span key={`${currentWordmark.language}-${wordmarkIndex}`} className="wordmark-roll">
                    {currentWordmark.script}
                  </span>
                </div>
                <span className="wordmark-language">{currentWordmark.language}</span>
              </div>
              <div className="hero-copy-block">
                <p className="eyebrow">Enterprise Speech Operations</p>
                <h1>Nudi Scribe</h1>
                <p className="hero-copy">
                  A production-grade workspace for multilingual consultation, live transcription,
                  structured clinical capture, and fast review without consumer-app noise.
                </p>
              </div>
            </div>

            <div className="hero-pills">
              <StatusPill label={health?.status || "offline"} tone={statusTone(health?.status)} />
              <span className="data-chip">{responseStatusLabel}</span>
              <span className="data-chip">{syncStatusLabel}</span>
            </div>

            <div className="hero-language-strip">
              {NUDI_WORDMARKS.map((item) => (
                <span
                  key={item.language}
                  className={item.language === currentWordmark.language ? "language-pill active" : "language-pill"}
                >
                  {item.script}
                </span>
              ))}
            </div>
          </div>

          <div className="hero-dashboard">
            <div className="dashboard-tile">
              <span>Model</span>
              <strong>{health?.model || serviceInfo?.model || "Pending runtime"}</strong>
              <p>Aligned for multilingual consultation and transcription workloads.</p>
            </div>
            <div className="dashboard-tile">
              <span>Voice Runtime</span>
              <strong>{ttsStack}</strong>
              <p>Final-only TTS playback reduces fragmented speech and keeps responses coherent.</p>
            </div>
            <div className="dashboard-tile">
              <span>Live Footprint</span>
              <strong>{sessions.length} tracked sessions</strong>
              <p>Session history sync now stays off the interaction critical path.</p>
            </div>
          </div>
        </header>

        <div className="landing-settings">
          <form className="connection-form" onSubmit={handleApplyBaseUrl}>
            <label>
              Backend URL
              <input value={baseUrlDraft} onChange={(e) => setBaseUrlDraft(e.target.value)} placeholder={DEFAULT_BASE_URL} />
            </label>
            <button className="primary-button" type="submit">Connect</button>
          </form>
          <div className="metric-strip">
            <InfoBlock label="ASR" value={asrStack} />
            <InfoBlock label="TTS" value={ttsStack} />
            <InfoBlock label="Scripts" value="Kannada, Hindi, Telugu, Tamil, Malayalam, Bengali, Punjabi, Odia" />
            <InfoBlock label="Latency" value="Optimistic UI + background sync" />
          </div>
        </div>

        <main className="landing-view">
          <button className="option-card" type="button" onClick={() => { handleStartConsultation(); setCurrentView("consultation_text"); }}>
            <p className="panel-kicker">Clinical Workflow</p>
            <h2>Assistant Consultation</h2>
            <p>Run intake or follow-up over text or voice with brief solution-focused responses, structured capture, and clean speech playback.</p>
            <div className="option-sub-choices">
              <span className="chip active" onClick={(e) => { e.stopPropagation(); handleStartConsultation(); setCurrentView("consultation_text"); }}>Text</span>
              <span className="chip active" onClick={(e) => { e.stopPropagation(); handleStartConsultation(); setCurrentView("consultation_voice"); }}>Voice</span>
            </div>
          </button>

          <button className="option-card" type="button" onClick={() => { handleNewSession(); setCurrentView("transcription"); }}>
            <p className="panel-kicker">Operations Capture</p>
            <h2>Two-Speaker Transcription</h2>
            <p>Capture bilingual or code-mixed conversations, review turn-separated transcript output, and export a clean operational record.</p>
            <div className="chip-row">
              <span className="chip active">Live Recording</span>
              <span className="chip active">Editable File</span>
            </div>
          </button>
        </main>

        <section className="panel enterprise-strip">
          <div className="panel-head">
            <div>
              <p className="panel-kicker">Operations Snapshot</p>
              <h2>Enterprise readiness</h2>
            </div>
          </div>
          <div className="enterprise-grid">
            <div className="enterprise-note">
              <span>Interaction path</span>
              <strong>Streaming-first</strong>
              <p>Primary actions update the visible response immediately and leave session reconciliation to background sync.</p>
            </div>
            <div className="enterprise-note">
              <span>Speech quality</span>
              <strong>Sentence-level playback</strong>
              <p>Assistant TTS now waits for finalized segments instead of reading draft fragments word by word.</p>
            </div>
            <div className="enterprise-note">
              <span>Recent activity</span>
              <strong>{recentActivityItems.length ? "Live event trail" : "No events yet"}</strong>
              <p>{recentActivityItems[0]?.text || "Launch a workflow to start recording activity and system feedback."}</p>
            </div>
          </div>
          {recentActivityItems.length > 0 && (
            <div className="activity-rail">
              {recentActivityItems.map((item) => (
                <div className={`activity-card ${item.level}`} key={item.id}>
                  <div className="turn-head">
                    <strong>{item.level}</strong>
                    <span>{formatDateValue(item.created_at)}</span>
                  </div>
                  <p>{item.text}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    );
  }

  if (currentView === "consultation_text" || currentView === "consultation_voice") {
    return (
      <div className="page-shell">
        <div className="view-header">
          <button className="ghost-button" type="button" onClick={() => setCurrentView("landing")}>← Back</button>
          <div className="view-title-block">
            <p className="eyebrow">Nudi Scribe</p>
            <h2>{currentView === "consultation_text" ? "Assistant Consultation · Text" : "Assistant Consultation · Voice"}</h2>
          </div>
          <div className="hero-pills">
            <StatusPill label={captureState} tone={captureTone(captureState)} />
            {assistantLanguage !== "auto" && <span className="lang-badge">{assistantLanguage.toUpperCase()}</span>}
          </div>
        </div>

        <section className="panel operational-banner">
          <div className="enterprise-grid">
            <div className="enterprise-note">
              <span>Brand wordmark</span>
              <strong>{currentWordmark.script}</strong>
              <p>{currentWordmark.language} rendering of Nudi Scribe rolls every two seconds.</p>
            </div>
            <div className="enterprise-note">
              <span>Response path</span>
              <strong>{responseStatusLabel}</strong>
              <p>Streaming output is shown immediately while heavier report state sync is deferred.</p>
            </div>
            <div className="enterprise-note">
              <span>Session state</span>
              <strong>{syncStatusLabel}</strong>
              <p>{sessionId} · {consultationMode === "follow_up" ? "Follow-up" : "Consultation"} · {assistantLanguage.toUpperCase()}</p>
            </div>
          </div>
        </section>

        {/* Mode toggle */}
        <div className="mode-toggle">
          <button className={currentView === "consultation_text" ? "chip active" : "chip"} type="button"
            onClick={() => setCurrentView("consultation_text")}>Text Input</button>
          <button className={currentView === "consultation_voice" ? "chip active" : "chip"} type="button"
            onClick={() => setCurrentView("consultation_voice")}>Voice Input</button>
          <div className="control-card inline-settings">
            <span className="control-label">Mode</span>
            <div className="chip-row">
              <button type="button" className={consultationMode === "consultation" ? "chip active" : "chip"}
                onClick={() => setConsultationMode("consultation")}>Consultation</button>
              <button type="button" className={consultationMode === "follow_up" ? "chip active" : "chip"}
                onClick={() => setConsultationMode("follow_up")}>Follow-up</button>
            </div>
          </div>
          <div className="control-card inline-settings">
            <span className="control-label">Reply in</span>
            <div className="chip-row">
              <button type="button" className={responseLanguage === "auto" ? "chip active" : "chip"}
                onClick={() => setResponseLanguage("auto")}>Auto</button>
              <button type="button" className={responseLanguage === "en" ? "chip active" : "chip"}
                onClick={() => setResponseLanguage("en")}>EN</button>
              <button type="button" className={responseLanguage === "hi" ? "chip active" : "chip"}
                onClick={() => setResponseLanguage("hi")}>HI</button>
              <button type="button" className={responseLanguage === "kn" ? "chip active" : "chip"}
                onClick={() => setResponseLanguage("kn")}>KN</button>
            </div>
          </div>
          <label className="checkbox-row">
            <input type="checkbox" checked={autoSpeak} onChange={(e) => setAutoSpeak(e.target.checked)} />
            Auto-play assistant speech
          </label>
        </div>

        <main className="workspace">
          <section className="panel">
            <div className="report-meta-grid" style={{ marginBottom: "18px" }}>
              <InfoBlock label="ASR Stack" value={asrStack} />
              <InfoBlock label="TTS Stack" value={ttsStack} />
            </div>
            <div className="two-column">
              <div className="stack">
                {currentView === "consultation_text" ? (
                  <article className="card">
                    <h3>Patient Input</h3>
                    <p className="supporting-copy">Type in English, Hindi, Kannada, or code-mixed speech. The system auto-detects your input language and provides consultation accordingly.</p>
                    <form className="composer" onSubmit={handleTextSubmit}>
                      <textarea rows={4} value={textInput} onChange={(e) => setTextInput(e.target.value)}
                        placeholder="Describe the symptom, duration, medicines, or follow-up update..." />
                      <button className="primary-button" type="submit" disabled={textBusy}>
                        {textBusy ? "Sending..." : "Send"}
                      </button>
                    </form>
                    {inputLanguageInfo && (
                      <div className="chip-row" style={{ marginTop: "8px" }}>
                        <span className="data-chip">Detected input</span>
                        {(() => {
                          const info = getLanguageLabel(
                            inputLanguageInfo.dominant_language,
                            inputLanguageInfo.is_code_mixed,
                            inputLanguageInfo.languages
                          );
                          return <span className={`lang-badge ${info.badgeClass}`}>{info.label}</span>;
                        })()}
                        {inputLanguageInfo.is_code_mixed && <span className="data-chip">Code-Mixed</span>}
                      </div>
                    )}
                  </article>
                ) : (
                  <article className="card">
                    <h3>Live Voice Turn</h3>
                    <p className="supporting-copy">Speak naturally in English, Hindi, Kannada, or code-mixed speech. The interface prioritizes quick turn capture and polished sentence-level playback.</p>
                    <div className="button-row">
                      <StatusPill label={vadLabel(vadState)} tone={vadTone(vadState)} />
                      <span className="data-chip">Frontend silence gate active</span>
                    </div>
                    <p className="supporting-copy">
                      {vadState?.phase === "speech"
                        ? "Speech is open and only voice energy is being forwarded."
                        : "The browser is calibrating ambient noise and suppressing silence before upload."}
                    </p>
                    <div className="meter">
                      <div className="meter-fill" style={{ width: `${Math.min(micLevel * 180, 100)}%` }} />
                    </div>
                    <div className="inline-meta">
                      <span>{audioConfig ? `${audioConfig.sample_rate} Hz` : "Awaiting connection"}</span>
                      <span>{formatDurationSeconds(recordingSeconds)}</span>
                      {lastTranscription ? (() => {
                        const info = getLanguageLabel(
                          lastTranscription.detected_input_language || lastTranscription.language,
                          lastTranscription.is_code_mixed,
                          lastTranscription.languages
                        );
                        return <span className={`lang-badge ${info.badgeClass}`}>{info.label}</span>;
                      })() : <span>Language detection pending</span>}
                    </div>
                    <div className="button-row">
                      <button className="primary-button" type="button" onClick={startRecording} disabled={captureState !== "idle"}>
                        Start Recording
                      </button>
                      <button className="ghost-button" type="button" onClick={stopRecording} disabled={captureState !== "recording"}>
                        Stop
                      </button>
                    </div>
                    {capturePreviewUrl && (
                      <div className="mini-block">
                        <audio controls src={capturePreviewUrl} />
                        <p className="supporting-copy">{capturePreviewMeta}</p>
                        <div className="button-row">
                          <button
                            className="primary-button"
                            type="button"
                            onClick={uploadRecordedConsultationAudio}
                            disabled={uploadBusy}
                          >
                            {uploadBusy ? "Uploading..." : "Upload Recording"}
                          </button>
                          <span className="data-chip">Fallback if live voice misses the assistant reply</span>
                        </div>
                      </div>
                    )}
                  </article>
                )}

                {/* Uploads */}
                <article className="card">
                  <h3>Review Inputs</h3>
                  <div className="upload-stack">
                    <label className="upload-box">
                      <span>{uploadBusy ? "Transcribing audio..." : "Upload consultation audio"}</span>
                      <input type="file" accept=".wav,.mp3,.m4a,.ogg,.webm,.flac,audio/*" onChange={handleAudioUpload} disabled={uploadBusy} />
                    </label>
                    <label className="upload-box">
                      <span>{reportBusy ? "Extracting report..." : "Upload PDF/TXT/JSON report"}</span>
                      <input type="file" accept=".pdf,.txt,.md,.json,.csv" onChange={handleReportUpload} disabled={reportBusy} />
                    </label>
                  </div>
                </article>
              </div>

              <div className="stack">
                {/* Transcription result */}
                <article className="card">
                  <h3>Transcript Capture</h3>
                  {lastTranscription ? (() => {
                    const langInfo = getLanguageLabel(
                      lastTranscription.detected_input_language || lastTranscription.language,
                      lastTranscription.is_code_mixed,
                      lastTranscription.languages
                    );
                    return (
                      <>
                        <div className="chip-row">
                          <span className="data-chip">{lastTranscription.speaker_role}</span>
                          <span className={`lang-badge ${langInfo.badgeClass}`}>{langInfo.label}</span>
                          {lastTranscription.is_code_mixed && (
                            <span className="lang-badge lang-badge-mixed">Code-Mixed</span>
                          )}
                        </div>
                        <p>{lastTranscription.text}</p>
                        {lastTranscription.languages.length > 1 && (
                          <div className="chip-row">
                            <span className="data-chip" style={{ fontSize: "0.75rem" }}>Languages detected:</span>
                            {lastTranscription.languages.map((l) => {
                              const lInfo = getLanguageLabel(l, false, [l]);
                              return <span className={`lang-badge ${lInfo.badgeClass}`} key={l} style={{ fontSize: "0.72rem", padding: "3px 8px" }}>{lInfo.label}</span>;
                            })}
                          </div>
                        )}
                      </>
                    );
                  })() : audioUploadResult ? (() => {
                    const langInfo = getLanguageLabel(
                      audioUploadResult.detected_input_language || audioUploadResult.language,
                      audioUploadResult.is_code_mixed,
                      audioUploadResult.languages
                    );
                    return (
                      <>
                        <div className="chip-row">
                          <span className="data-chip">{audioUploadResult.speaker_role}</span>
                          <span className={`lang-badge ${langInfo.badgeClass}`}>{langInfo.label}</span>
                          {audioUploadResult.is_code_mixed && (
                            <span className="lang-badge lang-badge-mixed">Code-Mixed</span>
                          )}
                        </div>
                        <p>{audioUploadResult.text}</p>
                      </>
                    );
                  })() : (
                    <EmptyState title="No turn captured" copy="Record or upload speech to see transcript and start medical consultation." />
                  )}
                </article>

                {/* Assistant response */}
                <article className="card">
                  <h3>Assistant Consultation {assistantLanguage !== "auto" && <span className="lang-badge">{assistantLanguage.toUpperCase()}</span>}</h3>
                  <p className="supporting-copy">Brief probable-solution guidance and spoken response appear here.</p>
                  {assistantDraft ? <p>{assistantDraft}</p> : null}
                  {lastResponse?.text ? <p>{lastResponse.text}</p> : null}
                  {!assistantDraft && !lastResponse?.text && (
                    <EmptyState title="No reply yet" copy="Start a consultation or submit a turn." />
                  )}
                  {ttsAudioUrl && (
                    <div className="mini-block">
                      <audio controls src={ttsAudioUrl} />
                      <p className="supporting-copy">{ttsMeta || (ttsBusy ? "Generating audio..." : "")}</p>
                    </div>
                  )}
                  <div className="button-row speech-controls">
                    <button className="ghost-button icon-button" type="button" title="Pause speech" aria-label="Pause speech" onClick={pauseAssistantSpeech} disabled={!ttsAudioUrl || ttsPaused}>
                      ⏸
                    </button>
                    <button className="ghost-button icon-button" type="button" title="Resume speech" aria-label="Resume speech" onClick={resumeAssistantSpeech} disabled={!ttsPaused}>
                      ▶
                    </button>
                    <button className="ghost-button icon-button" type="button" title="Stop speech" aria-label="Stop speech" onClick={stopAssistantSpeech} disabled={!ttsAudioUrl && !ttsBusy}>
                      ■
                    </button>
                  </div>
                  {ttsPaused && <p className="supporting-copy">Assistant speech is paused.</p>}
                </article>

                {/* Public Healthcare Resources & Recommendations */}
                <article className="card">
                  <h3>Reference Guidance</h3>
                  {displayedKnowledgeHits.length === 0 ? (
                    <EmptyState title="No resource hits" copy="Resources appear when symptoms match public healthcare topics." />
                  ) : (
                    <div className="resource-list">
                      {displayedKnowledgeHits.map((resource) => (
                        <ResourceCard key={`${resource.topic}-${resource.source_url}`} resource={resource} />
                      ))}
                    </div>
                  )}
                </article>

                {/* Suggested questions */}
                <article className="card">
                  <h3>Next Best Questions</h3>
                  {displayedQuestions.length === 0 ? (
                    <EmptyState title="No pending questions" copy="Follow-up prompts appear as consultation progresses." />
                  ) : (
                    <ul className="plain-list">
                      {displayedQuestions.map((q) => <li key={q}>{q}</li>)}
                    </ul>
                  )}
                </article>
              </div>
            </div>
          </section>

          {/* Structured Report */}
          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="panel-kicker">Structured Report</p>
                <h2>Editable healthcare report</h2>
              </div>
              <button className="ghost-button" type="button" onClick={() => setReportDraft(displayedReport)}>Refresh</button>
            </div>
            <div className="report-grid">
              {REPORT_FIELDS.map((field) => (
                <label className="field-block" key={field.key}>
                  <span>{field.label}</span>
                  <textarea rows={field.rows || 3} value={reportDraft[field.key] || ""}
                    onChange={(e) => setReportDraft((c) => ({ ...c, [field.key]: e.target.value }))} />
                </label>
              ))}
            </div>
            <div className="report-meta-grid">
              <InfoBlock label="Risk Level" value={reportDraft.risk_level || displayedReport.risk_level || "routine"} />
              <InfoBlock label="Red Flags" value={(reportDraft.red_flags || displayedReport.red_flags || []).join(", ") || "none"} />
            </div>
          </section>

          {/* Consultation Timeline */}
          <section className="panel">
            <div className="panel-head">
              <div><p className="panel-kicker">History</p><h2>Consultation timeline</h2></div>
              <div className="button-row">
                <button className="ghost-button" type="button" onClick={handleNewSession}>New Session</button>
                <button className="ghost-button" type="button" onClick={handleClearSession}>Clear</button>
              </div>
            </div>
            {consultationTurns.length === 0 ? (
              <EmptyState title="No turns yet" copy="Turns appear here as the session progresses." />
            ) : (
              <div className="turn-list">
                {consultationTurns.map((turn) => {
                  const isCodeMixed = turn.languages.length > 1;
                  const turnLangInfo = getLanguageLabel(turn.language, isCodeMixed, turn.languages);
                  return (
                    <div className={`turn-card ${turn.speaker_role}`} key={`${turn.id || turn.created_at}-${turn.text}`}>
                      <div className="turn-head">
                        <span>{turn.speaker_role}</span>
                        <span>{formatDateValue(turn.created_at)}</span>
                      </div>
                      <p>{turn.text}</p>
                      <div className="chip-row">
                        <span className={`lang-badge ${turnLangInfo.badgeClass}`}>{turnLangInfo.label}</span>
                        {isCodeMixed && turn.languages.map((l) => {
                          const lInfo = getLanguageLabel(l, false, [l]);
                          return <span className={`lang-badge ${lInfo.badgeClass}`} key={`${turn.id}-${l}`} style={{ fontSize: "0.72rem", padding: "3px 8px" }}>{lInfo.label}</span>;
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </main>
      </div>
    );
  }

  // ======================== TRANSCRIPTION VIEW ========================
  return (
    <div className="page-shell">
      <div className="view-header">
        <button className="ghost-button" type="button" onClick={() => { if (transcriptRecording) stopTranscriptionRecording(); setCurrentView("landing"); }}>← Back</button>
        <div className="view-title-block">
          <p className="eyebrow">Nudi Scribe</p>
          <h2>Two-Speaker Live Transcription</h2>
        </div>
        <div className="hero-pills">
          <StatusPill label={transcriptRecording ? "recording" : "idle"} tone={transcriptRecording ? "good" : "neutral"} />
        </div>
      </div>

      <section className="panel operational-banner">
        <div className="enterprise-grid">
          <div className="enterprise-note">
            <span>Wordmark</span>
            <strong>{currentWordmark.script}</strong>
            <p>{currentWordmark.language} mode keeps the identity visibly multilingual without feeling decorative.</p>
          </div>
          <div className="enterprise-note">
            <span>Turn logic</span>
            <strong>{transcriptRecording ? "Active turn detection" : "Standby"}</strong>
            <p>Frontend silence gating and alternating speaker layout keep transcription review faster.</p>
          </div>
          <div className="enterprise-note">
            <span>Buffering mode</span>
            <strong>{syncStatusLabel}</strong>
            <p>Editing remains responsive while background state updates continue asynchronously.</p>
          </div>
        </div>
      </section>

      <main className="workspace">
        <section className="panel">
          <div className="panel-head">
            <div><p className="panel-kicker">Live Recording</p><h2>Record and transcribe a two-speaker conversation</h2></div>
          </div>

          <div className="meter">
            <div className="meter-fill" style={{ width: `${Math.min(micLevel * 180, 100)}%` }} />
          </div>
          <div className="inline-meta">
            <span>{audioConfig ? `${audioConfig.sample_rate} Hz` : "Awaiting connection"}</span>
            <span>{formatDurationSeconds(recordingSeconds)}</span>
            <span>{vadLabel(vadState)}</span>
          </div>
          <div className="button-row" style={{ marginTop: "12px" }}>
            <StatusPill label={vadLabel(vadState)} tone={vadTone(vadState)} />
            <span className="data-chip">Frontend silence gate active</span>
            <span className="data-chip">Turns alternate after silence</span>
          </div>

          <div className="button-row" style={{ marginTop: "16px" }}>
            <button className="primary-button" type="button" onClick={startTranscriptionRecording} disabled={transcriptRecording}>
              Start Recording
            </button>
            <button className="ghost-button" type="button" onClick={stopTranscriptionRecording} disabled={!transcriptRecording}>
              Stop Recording
            </button>
            <button className="primary-button download-btn" type="button" onClick={downloadTranscript} disabled={!transcriptText}>
              Download Transcript
            </button>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div><p className="panel-kicker">Live Transcript</p><h2>Editable transcription (edit below and download)</h2></div>
          </div>

          {/* Live transcript lines */}
          {transcriptLines.length > 0 && (
            <div className="turn-list" style={{ marginBottom: "16px" }}>
              {transcriptLines.map((line) => {
                const langInfo = getLanguageLabel(line.detected_input_language, line.is_code_mixed, line.language ? [line.language] : undefined);
                return (
                <div className="turn-card patient" key={line.id}>
                  <div className="turn-head">
                    <span>{line.speaker}</span>
                    <span>{line.timestamp}</span>
                  </div>
                  <p>{line.text}</p>
                  <div className="chip-row">
                    <span className={`lang-badge ${langInfo.badgeClass}`}>{langInfo.label}</span>
                    {line.speaker_role && <span className="data-chip">{line.speaker_role}</span>}
                  </div>
                </div>
                );
              })}
            </div>
          )}

          <textarea
            className="transcript-editor"
            rows={15}
            value={transcriptText}
            onChange={(e) => setTranscriptText(e.target.value)}
            placeholder="Transcription will appear here as speakers talk. You can edit this text freely..."
          />
        </section>
      </main>
    </div>
  );
}

// ======================== HELPER COMPONENTS ========================

function syntheticFinal(response: {
  text: string; language: string; languages: string[]; speaker_role: string;
  consultation_mode: ConsultationMode; structured_report: StructuredReport;
  knowledge_hits: KnowledgeHit[]; suggested_questions: string[];
}): FinalEvent {
  return {
    type: "final", text: response.text, language: response.language,
    languages: response.languages, speaker_role: response.speaker_role,
    consultation_mode: response.consultation_mode, structured_report: response.structured_report,
    knowledge_hits: response.knowledge_hits, suggested_questions: response.suggested_questions,
    tts_language: response.language
  };
}

function InfoBlock(props: { label: string; value: string }) {
  return (<div className="info-block"><span>{props.label}</span><strong>{props.value}</strong></div>);
}

function StatusPill(props: { label: string; tone: "good" | "warning" | "error" | "neutral" }) {
  return <span className={`status-pill ${props.tone}`}>{props.label}</span>;
}

function EmptyState(props: { title: string; copy: string }) {
  return (<div className="empty-state"><strong>{props.title}</strong><p>{props.copy}</p></div>);
}

function ResourceCard(props: { resource: KnowledgeHit }) {
  return (
    <div className="resource-card">
      <div className="turn-head">
        <strong>{props.resource.topic.replace(/_/g, " ")}</strong>
        <span>{props.resource.source_name}</span>
      </div>
      <p>{props.resource.summary}</p>
      {props.resource.recommendation && (
        <p className="recommendation-text">{props.resource.recommendation}</p>
      )}
      <a href={props.resource.source_url} target="_blank" rel="noreferrer">Open source</a>
    </div>
  );
}

function pushActivity(setActivities: Dispatch<SetStateAction<ActivityItem[]>>, level: ActivityItem["level"], text: string) {
  const nextItem: ActivityItem = {
    id: typeof crypto !== "undefined" && typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
    level, text, created_at: new Date().toISOString()
  };
  setActivities((current) => [nextItem, ...current].slice(0, 12));
}

function formatError(error: unknown): string { return error instanceof Error ? error.message : String(error); }

function formatDateValue(value: string): string {
  if (!value) return "now";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatDurationSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0.0s";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  return `${m}m ${(seconds % 60).toFixed(0)}s`;
}

function statusTone(status?: string) {
  if (status === "ok") return "good";
  if (status === "degraded") return "warning";
  if (!status) return "neutral";
  return "error";
}

function captureTone(state: CaptureState) {
  if (state === "idle") return "neutral";
  if (state === "recording" || state === "responding") return "good";
  if (state === "error") return "error";
  return "warning";
}

function vadTone(state?: VoiceActivityState | null) {
  if (!state) return "neutral";
  if (state.phase === "speech") return "good";
  if (state.phase === "calibrating") return "warning";
  return "neutral";
}

function vadLabel(state?: VoiceActivityState | null) {
  if (!state) return "VAD idle";
  if (state.phase === "speech") return "VAD speech gate";
  if (state.phase === "calibrating") return "VAD calibrating";
  return "VAD listening";
}

function clearAudioTimer(timerRef: MutableRefObject<number | null>) {
  if (timerRef.current !== null) { window.clearInterval(timerRef.current); timerRef.current = null; }
}
