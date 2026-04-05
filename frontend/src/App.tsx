import {
  startTransition,
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
import { BrowserAudioCapture } from "./audio";
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
  ReportExtractResponse,
  RootInfo,
  SessionDetailResponse,
  SessionSummary,
  SpeakerRole,
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

const ASSISTANT_TTS_MIN_WORDS = 2;

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

export default function App() {
  const initialBaseUrl = window.localStorage.getItem(STORAGE_KEYS.baseUrl) || DEFAULT_BASE_URL;
  const initialSessionId = window.localStorage.getItem(STORAGE_KEYS.sessionId) || buildSessionId();
  const initialMode =
    (window.localStorage.getItem(STORAGE_KEYS.consultationMode) as ConsultationMode) || "consultation";
  const initialSpeakerRole =
    (window.localStorage.getItem(STORAGE_KEYS.speakerRole) as SpeakerRole) || "auto";
  const initialAutoSpeak = window.localStorage.getItem(STORAGE_KEYS.autoSpeak) !== "false";

  // -- View state --
  const [currentView, setCurrentView] = useState<AppView>("landing");

  const [baseUrl, setBaseUrl] = useState(initialBaseUrl);
  const [baseUrlDraft, setBaseUrlDraft] = useState(initialBaseUrl);
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [consultationMode, setConsultationMode] = useState<ConsultationMode>(initialMode);
  const [speakerRole, setSpeakerRole] = useState<SpeakerRole>(initialSpeakerRole);
  const [autoSpeak, setAutoSpeak] = useState(initialAutoSpeak);

  const [serviceInfo, setServiceInfo] = useState<RootInfo | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionDetail, setSessionDetail] = useState<SessionDetailResponse | null>(null);

  const [textInput, setTextInput] = useState("");
  const [textBusy, setTextBusy] = useState(false);
  const [assistantDraft, setAssistantDraft] = useState("");
  const [lastResponse, setLastResponse] = useState<FinalEvent | null>(null);
  const [lastTranscription, setLastTranscription] = useState<TranscriptionEvent | null>(null);
  const [captureState, setCaptureState] = useState<CaptureState>("idle");
  const [audioConfig, setAudioConfig] = useState<AudioConfigEvent | null>(null);
  const [micLevel, setMicLevel] = useState(0);
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
  const speechBufferRef = useRef("");
  const speechQueueRef = useRef<Array<{ url: string; meta: string }>>([]);
  const speechUrlsRef = useRef<string[]>([]);
  const speechAudioRef = useRef<HTMLAudioElement | null>(null);
  const speechMetaRef = useRef<AssistantSpeechMeta>({ language: undefined, languages: [] });
  const speechChainRef = useRef<Promise<void>>(Promise.resolve());
  const pendingSpeechJobsRef = useRef(0);
  const playbackActiveRef = useRef(false);
  const pausedSpeechRef = useRef(false);

  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.baseUrl, baseUrl); }, [baseUrl]);
  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.sessionId, sessionId); }, [sessionId]);
  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.consultationMode, consultationMode); }, [consultationMode]);
  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.speakerRole, speakerRole); }, [speakerRole]);
  useEffect(() => { window.localStorage.setItem(STORAGE_KEYS.autoSpeak, String(autoSpeak)); }, [autoSpeak]);

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

  async function refreshSessionDetail() {
    try {
      const payload = await getSessionDetail(baseUrl, sessionId);
      startTransition(() => {
        setSessionDetail(payload);
        setReportDraft(payload.structured_report || blankReport());
      });
    } catch (error) {
      pushActivity(setActivities, "warning", `Session refresh failed: ${formatError(error)}`);
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
      const response = await startConsultation(baseUrl, {
        session_id: sessionId,
        consultation_mode: consultationMode
      });
      const speechRunId = beginAssistantSpeechRun({
        language: response.language,
        languages: response.languages
      });
      setLastResponse(syntheticFinal(response));
      setAssistantDraft("");
      await refreshSessionDetail();
      pushActivity(setActivities, "info", `${consultationMode === "follow_up" ? "Follow-up" : "Consultation"} flow started.`);
      if (autoSpeak) {
        speechBufferRef.current = response.text;
        flushAssistantSpeechBuffer(speechRunId, true);
      }
    } catch (error) {
      pushActivity(setActivities, "error", `Unable to start consultation: ${formatError(error)}`);
    }
  }

  async function handleTextSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanedText = textInput.trim();
    if (!cleanedText || textBusy) return;

    setTextBusy(true);
    const speechRunId = beginAssistantSpeechRun();
    setAssistantDraft("");
    setLastResponse(null);

    try {
      const finalEvent = await streamTextChat(
        baseUrl, sessionId,
        { text: cleanedText, speaker_role: speakerRole === "auto" ? undefined : speakerRole, consultation_mode: consultationMode },
        (eventPayload) => {
          if (eventPayload.type === "language_info") {
            speechMetaRef.current = {
              language: eventPayload.dominant_language || speechMetaRef.current.language,
              languages: eventPayload.languages || []
            };
          }
          if (eventPayload.type === "delta") {
            setAssistantDraft((current) => current + eventPayload.text);
            if (autoSpeak) {
              speechBufferRef.current += eventPayload.text;
              flushAssistantSpeechBuffer(speechRunId);
            }
          }
          if (eventPayload.type === "final") {
            speechMetaRef.current = {
              language: eventPayload.tts_language || eventPayload.language,
              languages: eventPayload.languages || []
            };
            if (autoSpeak) {
              flushAssistantSpeechBuffer(speechRunId, true);
            }
            setLastResponse(eventPayload);
            setAssistantDraft("");
          }
        }
      );
      setLastResponse(finalEvent);
      setTextInput("");
      await refreshSessionDetail();
      pushActivity(setActivities, "info", `Captured ${speakerRole === "auto" ? "auto-detected" : speakerRole} text turn.`);
    } catch (error) {
      pushActivity(setActivities, "error", `Text consultation failed: ${formatError(error)}`);
    } finally {
      setTextBusy(false);
    }
  }

  async function handleAudioUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || uploadBusy) return;
    setUploadBusy(true);
    try {
      const result = await transcribeFile(baseUrl, file, sessionId);
      setAudioUploadResult(result);
      setLastTranscription({ type: "transcription", ...result, consultation_mode: consultationMode });
      await refreshSessionDetail();
      pushActivity(setActivities, "info", `Uploaded audio transcribed as ${result.speaker_role} speech.`);
    } catch (error) {
      pushActivity(setActivities, "error", `Audio upload failed: ${formatError(error)}`);
    } finally {
      setUploadBusy(false);
    }
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
      await refreshSessionDetail();
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
    const speechRunId = beginAssistantSpeechRun();
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
        speaker_role: speakerRole === "auto" ? undefined : speakerRole
      };
      const socketSession = createAudioSocketSession(baseUrl, sessionId, socketConfig,
        (eventPayload: AudioStreamEvent) => {
          if (eventPayload.type === "audio_config") setAudioConfig(eventPayload);
          if (eventPayload.type === "transcription") { setLastTranscription(eventPayload); setCaptureState("responding"); }
          if (eventPayload.type === "language_info") {
            speechMetaRef.current = {
              language: eventPayload.dominant_language || speechMetaRef.current.language,
              languages: eventPayload.languages || []
            };
          }
          if (eventPayload.type === "delta") {
            setAssistantDraft((current) => current + eventPayload.text);
            setCaptureState("responding");
            if (autoSpeak) {
              speechBufferRef.current += eventPayload.text;
              flushAssistantSpeechBuffer(speechRunId);
            }
          }
          if (eventPayload.type === "final") {
            speechMetaRef.current = {
              language: eventPayload.tts_language || eventPayload.language,
              languages: eventPayload.languages || []
            };
            if (autoSpeak) {
              flushAssistantSpeechBuffer(speechRunId, true);
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
        onLevel: (rms) => setMicLevel(rms)
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
        setCapturePreviewUrl((current) => { if (current) URL.revokeObjectURL(current); return URL.createObjectURL(stopResult.blob); });
        setCapturePreviewMeta(`${stopResult.sampleRate} Hz · ${formatDurationSeconds(stopResult.durationSeconds)}`);
      }
      socketSession.commit();
      const completion = await socketSession.completion;
      socketSession.close();
      audioSocketRef.current = null;
      captureRef.current = null;
      setMicLevel(0);
      setRecordingSeconds(0);
      if (completion.type === "final") {
        setLastResponse(completion);
        await refreshSessionDetail();
        pushActivity(setActivities, "info", `Live turn completed as ${completion.speaker_role || "unknown"} speech.`);
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
      setCaptureState("error");
      pushActivity(setActivities, "error", `Unable to stop recording: ${formatError(error)}`);
    }
  }

  // -- Transcription mode (two-speaker, no assistant) --
  async function startTranscriptionRecording() {
    if (transcriptRecording) return;
    setTranscriptRecording(true);
    setCaptureState("connecting");
    try {
      const capture = new BrowserAudioCapture();
      captureRef.current = capture;
      const prepared = await capture.prepare();
      const socketConfig: AudioSocketConfig = {
        sample_rate: prepared.sampleRate, channels: prepared.channels,
        sample_width: prepared.sampleWidth, encoding: "pcm_s16le",
        consultation_mode: "consultation"
      };
      let turnCount = 0;
      const socketSession = createAudioSocketSession(baseUrl, sessionId, socketConfig,
        (eventPayload: AudioStreamEvent) => {
          if (eventPayload.type === "audio_config") setAudioConfig(eventPayload);
          if (eventPayload.type === "transcription") {
            turnCount += 1;
            const speaker = eventPayload.speaker_role === "doctor" ? "Speaker 1 (Doctor)" : `Speaker ${turnCount % 2 === 0 ? 2 : 1}`;
            const newLine: TranscriptLine = {
              id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}`,
              speaker,
              text: eventPayload.text,
              timestamp: new Date().toLocaleTimeString(),
              language: eventPayload.language || "auto"
            };
            setTranscriptLines((prev) => [...prev, newLine]);
            setTranscriptText((prev) => prev + `[${newLine.timestamp}] ${newLine.speaker}: ${newLine.text}\n`);
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
        onLevel: (rms) => setMicLevel(rms)
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

  async function handleClearSession() {
    try {
      await clearSession(baseUrl, sessionId);
      setSessionDetail(null); setReportDraft(blankReport()); setLastResponse(null);
      setLastTranscription(null); setAudioUploadResult(null); setReportUploadResult(null);
      setAssistantDraft(""); clearGeneratedAudio();
      pushActivity(setActivities, "warning", `Cleared session ${sessionId}.`);
    } catch (error) {
      pushActivity(setActivities, "error", `Unable to clear session: ${formatError(error)}`);
    }
  }

  function handleNewSession() {
    const nextSessionId = buildSessionId();
    setSessionId(nextSessionId); setSessionDetail(null); setReportDraft(blankReport());
    setLastResponse(null); setLastTranscription(null); setAudioUploadResult(null);
    setReportUploadResult(null); setAssistantDraft(""); clearGeneratedAudio();
    setTranscriptLines([]); setTranscriptText("");
    pushActivity(setActivities, "info", `Created new healthcare session ${nextSessionId}.`);
  }

  function beginAssistantSpeechRun(meta?: AssistantSpeechMeta): number {
    clearAssistantAudio();
    const nextRunId = speechRunRef.current + 1;
    speechRunRef.current = nextRunId;
    speechBufferRef.current = "";
    speechMetaRef.current = {
      language: meta?.language,
      languages: meta?.languages || []
    };
    return nextRunId;
  }

  function extractAssistantSpeechChunks(
    text: string,
    minWords = ASSISTANT_TTS_MIN_WORDS,
    force = false
  ): { chunks: string[]; remainder: string } {
    const words = text.trim().split(/\s+/).filter(Boolean);
    if (words.length === 0) {
      return { chunks: [], remainder: "" };
    }

    if (!force && words.length < minWords) {
      return { chunks: [], remainder: words.join(" ") };
    }

    const chunks: string[] = [];
    while (words.length >= minWords) {
      chunks.push(words.splice(0, minWords).join(" "));
    }

    return {
      chunks,
      remainder: force ? words.join(" ") : words.join(" ")
    };
  }

  function flushAssistantSpeechBuffer(runId: number, force = false) {
    if (!autoSpeak || runId !== speechRunRef.current) {
      return;
    }

    const bufferedText = speechBufferRef.current;
    if (!bufferedText.trim()) {
      return;
    }

    const { chunks, remainder } = extractAssistantSpeechChunks(bufferedText, ASSISTANT_TTS_MIN_WORDS, force);
    speechBufferRef.current = force ? "" : remainder;
    const nextSegments = force && remainder.trim() ? [...chunks, remainder.trim()] : chunks;
    const { language, languages } = speechMetaRef.current;

    for (const chunk of nextSegments) {
      queueAssistantSpeechSegment(runId, chunk, language, languages);
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
    speechBufferRef.current = "";
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
    setCapturePreviewUrl((current) => { if (current) URL.revokeObjectURL(current); return ""; });
    setCapturePreviewMeta("");
  }

  const displayedReport = reportUploadResult?.structured_report || sessionDetail?.structured_report || blankReport();
  const displayedKnowledgeHits = lastResponse?.knowledge_hits || reportUploadResult?.knowledge_hits || sessionDetail?.knowledge_hits || [];
  const displayedQuestions = lastResponse?.suggested_questions || lastTranscription?.suggested_questions || sessionDetail?.suggested_questions || [];
  const consultationTurns = sessionDetail?.consultation_turns || [];
  const detectedLang = lastResponse?.language || lastTranscription?.language || sessionDetail?.selected_language || "auto";
  const ttsStack = health?.tts_real_providers?.length
    ? health.tts_real_providers.join(" + ")
    : health?.tts_providers?.join(" + ") || "Pending voice runtime";
  const asrStack = "Whisper + Indic ASR";

  // ======================== RENDER ========================

  if (currentView === "landing") {
    return (
      <div className="page-shell">
        <header className="hero">
          <div>
            <p className="eyebrow">NuDiscribe Healthcare Consultation</p>
            <h1>Multilingual Clinical Conversation Workspace</h1>
            <p className="hero-copy">
              Assistant-led intake and follow-up consultation with multilingual ASR, structured
              extraction, editable review, longitudinal history, and speech output.
            </p>
          </div>
          <div className="hero-pills">
            <StatusPill label={health?.status || "offline"} tone={statusTone(health?.status)} />
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
            <InfoBlock label="Languages" value="English, Hindi, Kannada, Code-mixed" />
            <InfoBlock label="Sessions" value={`${sessions.length} tracked`} />
          </div>
        </div>

        <main className="landing-view">
          <button className="option-card" type="button" onClick={() => { handleStartConsultation(); setCurrentView("consultation_text"); }}>
            <h2>Assistant-Led Consultation</h2>
            <p>Run guided intake or follow-up over text or voice. The assistant keeps the reply minimal, asks only the next necessary question, and updates the report live.</p>
            <div className="option-sub-choices">
              <span className="chip active" onClick={(e) => { e.stopPropagation(); handleStartConsultation(); setCurrentView("consultation_text"); }}>Text</span>
              <span className="chip active" onClick={(e) => { e.stopPropagation(); handleStartConsultation(); setCurrentView("consultation_voice"); }}>Voice</span>
            </div>
          </button>

          <button className="option-card" type="button" onClick={() => { handleNewSession(); setCurrentView("transcription"); }}>
            <h2>Two-Speaker Live Transcription</h2>
            <p>Capture a bilingual or code-mixed conversation, edit the transcript in place, and export it for review.</p>
            <div className="chip-row">
              <span className="chip active">Live Recording</span>
              <span className="chip active">Editable File</span>
            </div>
          </button>
        </main>
      </div>
    );
  }

  if (currentView === "consultation_text" || currentView === "consultation_voice") {
    return (
      <div className="page-shell">
        <div className="view-header">
          <button className="ghost-button" type="button" onClick={() => setCurrentView("landing")}>← Back</button>
          <h2>{currentView === "consultation_text" ? "Assistant Consultation · Text" : "Assistant Consultation · Voice"}</h2>
          <div className="hero-pills">
            <StatusPill label={captureState} tone={captureTone(captureState)} />
            {detectedLang !== "auto" && <span className="lang-badge">{detectedLang.toUpperCase()}</span>}
          </div>
        </div>

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
                    <p className="supporting-copy">Type in English, Hindi, Kannada, or code-mixed. The assistant responds in the same language and keeps the turn clinically focused.</p>
                    <form className="composer" onSubmit={handleTextSubmit}>
                      <textarea rows={4} value={textInput} onChange={(e) => setTextInput(e.target.value)}
                        placeholder="Describe the symptom, duration, medicines, or follow-up update..." />
                      <button className="primary-button" type="submit" disabled={textBusy}>
                        {textBusy ? "Sending..." : "Send"}
                      </button>
                    </form>
                  </article>
                ) : (
                  <article className="card">
                    <h3>Live Voice Turn</h3>
                    <p className="supporting-copy">Speak naturally in English, Hindi, Kannada, or code-mixed speech. The platform routes ASR, updates the report, and speaks the assistant response back.</p>
                    <div className="meter">
                      <div className="meter-fill" style={{ width: `${Math.min(micLevel * 180, 100)}%` }} />
                    </div>
                    <div className="inline-meta">
                      <span>{audioConfig ? `${audioConfig.sample_rate} Hz` : "Awaiting connection"}</span>
                      <span>{formatDurationSeconds(recordingSeconds)}</span>
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
                  {lastTranscription ? (
                    <>
                      <div className="chip-row">
                        <span className="data-chip">{lastTranscription.speaker_role}</span>
                        <span className="lang-badge">{lastTranscription.language}</span>
                        {lastTranscription.languages.map((l) => <span className="data-chip" key={l}>{l}</span>)}
                      </div>
                      <p>{lastTranscription.text}</p>
                    </>
                  ) : audioUploadResult ? (
                    <>
                      <div className="chip-row">
                        <span className="data-chip">{audioUploadResult.speaker_role}</span>
                        <span className="lang-badge">{audioUploadResult.language}</span>
                      </div>
                      <p>{audioUploadResult.text}</p>
                    </>
                  ) : (
                    <EmptyState title="No turn captured" copy="Record or upload speech to see transcript." />
                  )}
                </article>

                {/* Assistant response */}
                <article className="card">
                  <h3>Assistant Consultation {detectedLang !== "auto" && <span className="lang-badge">{detectedLang}</span>}</h3>
                  <p className="supporting-copy">Short clinical guidance, next-step questioning, and spoken response appear here.</p>
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
                    <button className="ghost-button" type="button" onClick={pauseAssistantSpeech} disabled={!ttsAudioUrl || ttsPaused}>
                      Pause speech
                    </button>
                    <button className="ghost-button" type="button" onClick={resumeAssistantSpeech} disabled={!ttsPaused}>
                      Resume speech
                    </button>
                    <button className="ghost-button" type="button" onClick={stopAssistantSpeech} disabled={!ttsAudioUrl && !ttsBusy}>
                      Stop speech
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
                {consultationTurns.map((turn) => (
                  <div className={`turn-card ${turn.speaker_role}`} key={`${turn.id || turn.created_at}-${turn.text}`}>
                    <div className="turn-head">
                      <span>{turn.speaker_role}</span>
                      <span>{formatDateValue(turn.created_at)}</span>
                    </div>
                    <p>{turn.text}</p>
                    <div className="chip-row">
                      <span className="data-chip">{turn.language}</span>
                      {turn.languages.map((l) => <span className="data-chip" key={`${turn.id}-${l}`}>{l}</span>)}
                    </div>
                  </div>
                ))}
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
          <h2>Two-Speaker Live Transcription</h2>
        <div className="hero-pills">
          <StatusPill label={transcriptRecording ? "recording" : "idle"} tone={transcriptRecording ? "good" : "neutral"} />
        </div>
      </div>

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
              {transcriptLines.map((line) => (
                <div className="turn-card patient" key={line.id}>
                  <div className="turn-head">
                    <span>{line.speaker}</span>
                    <span>{line.timestamp}</span>
                  </div>
                  <p>{line.text}</p>
                  <span className="lang-badge">{line.language}</span>
                </div>
              ))}
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

function clearAudioTimer(timerRef: MutableRefObject<number | null>) {
  if (timerRef.current !== null) { window.clearInterval(timerRef.current); timerRef.current = null; }
}
