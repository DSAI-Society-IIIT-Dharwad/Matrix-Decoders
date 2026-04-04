import {
  startTransition,
  useDeferredValue,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type FormEvent,
  type MutableRefObject,
  type SetStateAction
} from "react";

import {
  audioUrlFromBase64,
  chatRest,
  clearSession,
  createAudioSocketSession,
  getHealth,
  getRootInfo,
  getSessionDetail,
  getSessions,
  streamTextChat,
  streamTts,
  transcribeFile,
  ttsRest
} from "./api";
import { BrowserAudioCapture } from "./audio";
import { deriveStructuredReport, DOMAIN_FIELDS, GENERIC_FIELDS } from "./extraction";
import type {
  ActivityItem,
  AudioChunkEvent,
  AudioConfigEvent,
  AudioSocketConfig,
  AudioStreamEvent,
  ChatResponse,
  DomainMode,
  FinalEvent,
  HealthResponse,
  LanguageInfoEvent,
  RootInfo,
  SessionDetailResponse,
  SessionMessageRecord,
  SessionSummary,
  SessionTranscriptRecord,
  TransportMode,
  TranscribeResponse,
  TranscriptionEvent
} from "./types";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";
const STORAGE_KEYS = {
  baseUrl: "nudiscribe.frontend.baseUrl",
  sessionId: "nudiscribe.frontend.sessionId",
  domain: "nudiscribe.frontend.domain"
};

type CaptureState = "idle" | "arming" | "recording" | "transcribing" | "generating" | "error";
type TtsMode = "rest" | "websocket";

function syntheticFinalFromChatResponse(response: ChatResponse): FinalEvent {
  return {
    type: "final",
    text: response.text,
    language: response.language,
    languages: response.languages,
    is_code_mixed: response.is_code_mixed,
    tts_language: response.language,
    tts_segments: [
      {
        text: response.text,
        language: response.language,
        languages: response.languages
      }
    ]
  };
}

function buildSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `nudiscribe-${crypto.randomUUID().slice(0, 8)}`;
  }
  return `nudiscribe-${Date.now().toString(36)}`;
}

function sanitizeBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, "");
  return trimmed || DEFAULT_BASE_URL;
}

export default function App() {
  const initialBaseUrl =
    window.localStorage.getItem(STORAGE_KEYS.baseUrl) || DEFAULT_BASE_URL;
  const initialSessionId =
    window.localStorage.getItem(STORAGE_KEYS.sessionId) || buildSessionId();
  const initialDomain =
    (window.localStorage.getItem(STORAGE_KEYS.domain) as DomainMode) || "healthcare";

  const [baseUrl, setBaseUrl] = useState(initialBaseUrl);
  const [baseUrlDraft, setBaseUrlDraft] = useState(initialBaseUrl);
  const [domain, setDomain] = useState<DomainMode>(initialDomain);
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [serviceInfo, setServiceInfo] = useState<RootInfo | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionDetail, setSessionDetail] = useState<SessionDetailResponse | null>(null);
  const [controlRefreshTick, setControlRefreshTick] = useState(0);
  const [sessionRefreshTick, setSessionRefreshTick] = useState(0);
  const [activities, setActivities] = useState<ActivityItem[]>([]);

  const [textInput, setTextInput] = useState("");
  const [textMode, setTextMode] = useState<TransportMode>("websocket");
  const [textBusy, setTextBusy] = useState(false);
  const [assistantDraft, setAssistantDraft] = useState("");
  const [languageInfo, setLanguageInfo] = useState<LanguageInfoEvent | null>(null);
  const [lastResponse, setLastResponse] = useState<FinalEvent | null>(null);

  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadResult, setUploadResult] = useState<TranscribeResponse | null>(null);

  const [captureState, setCaptureState] = useState<CaptureState>("idle");
  const [audioConfig, setAudioConfig] = useState<AudioConfigEvent | null>(null);
  const [liveTranscript, setLiveTranscript] = useState<TranscriptionEvent | null>(null);
  const [micLevel, setMicLevel] = useState(0);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [capturePreviewUrl, setCapturePreviewUrl] = useState("");
  const [capturePreviewMeta, setCapturePreviewMeta] = useState("");

  const [ttsMode, setTtsMode] = useState<TtsMode>("websocket");
  const [ttsBusy, setTtsBusy] = useState(false);
  const [ttsText, setTtsText] = useState("");
  const [ttsAudioUrl, setTtsAudioUrl] = useState("");
  const [ttsChunks, setTtsChunks] = useState<AudioChunkEvent[]>([]);
  const [ttsMeta, setTtsMeta] = useState("");

  const [historySearch, setHistorySearch] = useState("");
  const deferredHistorySearch = useDeferredValue(historySearch);
  const [reportDraft, setReportDraft] = useState<Record<string, string>>({});

  const captureRef = useRef<BrowserAudioCapture | null>(null);
  const audioSocketRef = useRef<ReturnType<typeof createAudioSocketSession> | null>(null);
  const audioTimerRef = useRef<number | null>(null);
  const capturePreviewUrlRef = useRef("");
  const ttsAudioUrlRef = useRef("");

  const currentSummary = sessions.find((item) => item.session_id === sessionId) || null;
  const latestAssistantMessage = lastMessageByRole(sessionDetail?.messages || [], "assistant");
  const latestUserMessage = lastMessageByRole(sessionDetail?.messages || [], "user");
  const derivedReport = deriveStructuredReport({
    domain,
    snapshot: sessionDetail,
    uploadedTranscript: uploadResult?.text,
    liveTranscript: liveTranscript?.text,
    latestAssistant: latestAssistantMessage?.content || lastResponse?.text || "",
    assistantDraft
  });
  const reportStorageKey = `${sessionId}:${domain}`;

  const filteredSessions = sessions.filter((item) => {
    const query = deferredHistorySearch.trim().toLowerCase();
    if (!query) {
      return true;
    }
    return [
      item.session_id,
      item.selected_language,
      item.languages.join(" "),
      item.last_message,
      item.last_transcript
    ]
      .join(" ")
      .toLowerCase()
      .includes(query);
  });

  const filteredMessages = (sessionDetail?.messages || []).filter((message) => {
    const query = deferredHistorySearch.trim().toLowerCase();
    if (!query) {
      return true;
    }
    return `${message.role} ${message.content}`.toLowerCase().includes(query);
  });

  const filteredTranscripts = (sessionDetail?.transcripts || []).filter((record) => {
    const query = deferredHistorySearch.trim().toLowerCase();
    if (!query) {
      return true;
    }
    return `${record.source} ${record.text} ${record.languages.join(" ")}`
      .toLowerCase()
      .includes(query);
  });

  const filteredTelemetry = (sessionDetail?.telemetry || []).filter((record) => {
    const query = deferredHistorySearch.trim().toLowerCase();
    if (!query) {
      return true;
    }
    return `${record.kind} ${record.name} ${record.status} ${record.error_message}`
      .toLowerCase()
      .includes(query);
  });

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.baseUrl, baseUrl);
  }, [baseUrl]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.sessionId, sessionId);
  }, [sessionId]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.domain, domain);
  }, [domain]);

  useEffect(() => {
    capturePreviewUrlRef.current = capturePreviewUrl;
  }, [capturePreviewUrl]);

  useEffect(() => {
    ttsAudioUrlRef.current = ttsAudioUrl;
  }, [ttsAudioUrl]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setControlRefreshTick((value) => value + 1);
    }, 15000);
    return () => {
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function refreshControlSurface() {
      try {
        const [rootPayload, healthPayload, sessionPayload] = await Promise.all([
          getRootInfo(baseUrl),
          getHealth(baseUrl),
          getSessions(baseUrl)
        ]);
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setServiceInfo(rootPayload);
          setHealth(healthPayload);
          setSessions(sessionPayload.items || []);
        });
      } catch (error) {
        if (!cancelled) {
          pushActivity(
            setActivities,
            "error",
            `Control-surface refresh failed: ${formatError(error)}`
          );
        }
      }
    }

    refreshControlSurface();

    return () => {
      cancelled = true;
    };
  }, [baseUrl, controlRefreshTick]);

  useEffect(() => {
    let cancelled = false;

    async function refreshSessionSnapshot() {
      if (!sessionId) {
        startTransition(() => setSessionDetail(null));
        return;
      }

      try {
        const snapshot = await getSessionDetail(baseUrl, sessionId);
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setSessionDetail(snapshot);
        });
      } catch (error) {
        if (cancelled) {
          return;
        }
        const message = formatError(error);
        if (message.toLowerCase().includes("session not found")) {
          startTransition(() => setSessionDetail(null));
          return;
        }
        pushActivity(setActivities, "error", `Session detail failed: ${message}`);
      }
    }

    refreshSessionSnapshot();

    return () => {
      cancelled = true;
    };
  }, [baseUrl, sessionId, sessionRefreshTick]);

  useEffect(() => {
    const storedDraft = window.localStorage.getItem(`nudiscribe.report.${reportStorageKey}`);
    if (storedDraft) {
      try {
        setReportDraft(JSON.parse(storedDraft));
        return;
      } catch {
        // Fall through to derived report.
      }
    }
    setReportDraft(derivedReport);
  }, [reportStorageKey]);

  useEffect(() => {
    window.localStorage.setItem(
      `nudiscribe.report.${reportStorageKey}`,
      JSON.stringify(reportDraft)
    );
  }, [reportDraft, reportStorageKey]);

  useEffect(() => {
    return () => {
      clearAudioTimer(audioTimerRef);
      audioSocketRef.current?.close();
      if (captureRef.current) {
        captureRef.current.stop().catch(() => undefined);
      }
      clearObjectUrl(capturePreviewUrlRef.current);
      clearObjectUrl(ttsAudioUrlRef.current);
    };
  }, []);

  useEffect(() => {
    setUploadResult(null);
    setLiveTranscript(null);
    setLastResponse(null);
    setAssistantDraft("");
    setLanguageInfo(null);
    setTtsChunks([]);
    setCaptureState("idle");
    setRecordingSeconds(0);
    setMicLevel(0);
    setAudioConfig(null);
    clearGeneratedMedia();
  }, [sessionId]);

  useEffect(() => {
    if (!sessionDetail) {
      return;
    }

    const persistedAssistant = lastMessageByRole(sessionDetail.messages || [], "assistant");
    if (persistedAssistant) {
      setTtsText((current) => (current.trim() ? current : persistedAssistant.content));
    }

    const latestTranscriptRecord =
      lastTranscriptBySource(sessionDetail.transcripts || [], "ws.audio") ||
      lastTranscriptBySource(sessionDetail.transcripts || [], "api.transcribe") ||
      lastTranscript(sessionDetail.transcripts || []);

    if (latestTranscriptRecord) {
      setLanguageInfo({
        type: "language_info",
        languages: latestTranscriptRecord.languages,
        dominant_language:
          latestTranscriptRecord.dominant_language || sessionDetail.selected_language,
        is_code_mixed: latestTranscriptRecord.is_code_mixed
      });
    }
  }, [sessionDetail]);

  function clearGeneratedMedia() {
    setCapturePreviewUrl((current) => {
      clearObjectUrl(current);
      return "";
    });
    setCapturePreviewMeta("");
    setTtsAudioUrl((current) => {
      clearObjectUrl(current);
      return "";
    });
    setTtsChunks([]);
    setTtsMeta("");
  }

  async function handleApplyBaseUrl(event: FormEvent) {
    event.preventDefault();
    const nextBaseUrl = sanitizeBaseUrl(baseUrlDraft);
    setBaseUrl(nextBaseUrl);
    setControlRefreshTick((value) => value + 1);
    setSessionRefreshTick((value) => value + 1);
    pushActivity(setActivities, "info", `Backend target set to ${nextBaseUrl}`);
  }

  async function handleTextSubmit(event: FormEvent) {
    event.preventDefault();
    const cleanedText = textInput.trim();
    if (!cleanedText || textBusy) {
      return;
    }

    setTextBusy(true);
    setAssistantDraft("");
    setLanguageInfo(null);
    setTextInput("");
    pushActivity(setActivities, "info", `Sending ${textMode} text input to session ${sessionId}.`);

    try {
      let finalPayload: FinalEvent;

      if (textMode === "rest") {
        const response = await chatRest(baseUrl, {
          session_id: sessionId,
          text: cleanedText
        });
        finalPayload = syntheticFinalFromChatResponse(response);
        setLanguageInfo({
          type: "language_info",
          languages: response.languages,
          dominant_language: response.language,
          is_code_mixed: response.is_code_mixed
        });
      } else {
        finalPayload = await streamTextChat(baseUrl, sessionId, cleanedText, (eventPayload) => {
          if (eventPayload.type === "language_info") {
            setLanguageInfo(eventPayload);
          }
          if (eventPayload.type === "delta") {
            setAssistantDraft((current) => current + eventPayload.text);
          }
        });
      }

      setAssistantDraft("");
      setLastResponse(finalPayload);
      setTtsText(finalPayload.text || "");
      if (finalPayload.language || finalPayload.languages?.length) {
        setLanguageInfo({
          type: "language_info",
          languages: finalPayload.languages || [],
          dominant_language: finalPayload.language || "auto",
          is_code_mixed: Boolean(finalPayload.is_code_mixed)
        });
      }
      setControlRefreshTick((value) => value + 1);
      setSessionRefreshTick((value) => value + 1);
      pushActivity(
        setActivities,
        "info",
        `Assistant response complete in ${finalPayload.language || "auto"} mode.`
      );
    } catch (error) {
      pushActivity(setActivities, "error", `Text interaction failed: ${formatError(error)}`);
    } finally {
      setTextBusy(false);
    }
  }

  async function handleUploadChange(event: FormEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (!file) {
      return;
    }

    setUploadBusy(true);
    pushActivity(setActivities, "info", `Uploading ${file.name} for transcription.`);

    try {
      const result = await transcribeFile(baseUrl, file, sessionId);
      setUploadResult(result);
      setLanguageInfo({
        type: "language_info",
        languages: result.languages,
        dominant_language: result.language,
        is_code_mixed: result.is_code_mixed
      });
      setControlRefreshTick((value) => value + 1);
      setSessionRefreshTick((value) => value + 1);
      pushActivity(
        setActivities,
        "info",
        `Upload transcript ready: ${result.language} / ${result.languages.join(", ") || "en"}.`
      );
    } catch (error) {
      pushActivity(setActivities, "error", `Upload transcription failed: ${formatError(error)}`);
    } finally {
      setUploadBusy(false);
      event.currentTarget.value = "";
    }
  }

  async function startRecording() {
    if (captureState !== "idle") {
      return;
    }

    setCaptureState("arming");
    setLiveTranscript(null);
    setAudioConfig(null);
    setAssistantDraft("");
    setMicLevel(0);
    pushActivity(setActivities, "info", `Preparing live microphone stream for ${sessionId}.`);

    try {
      const capture = new BrowserAudioCapture();
      const prepared = await capture.prepare();
      captureRef.current = capture;

      const socketConfig: AudioSocketConfig = {
        sample_rate: prepared.sampleRate,
        channels: prepared.channels,
        sample_width: prepared.sampleWidth,
        encoding: "pcm_s16le"
      };

      const socketSession = createAudioSocketSession(
        baseUrl,
        sessionId,
        socketConfig,
        (eventPayload) => {
          if (eventPayload.type === "audio_config") {
            setAudioConfig(eventPayload);
            pushActivity(
              setActivities,
              "info",
              `Audio stream negotiated at ${eventPayload.sample_rate} Hz, ${eventPayload.channels} channel, ${eventPayload.encoding}.`
            );
          }
          if (eventPayload.type === "transcription") {
            setLiveTranscript(eventPayload);
            setLanguageInfo({
              type: "language_info",
              languages: eventPayload.languages,
              dominant_language: eventPayload.language,
              is_code_mixed: eventPayload.is_code_mixed
            });
            setCaptureState("generating");
          }
          if (eventPayload.type === "language_info") {
            setLanguageInfo(eventPayload);
          }
          if (eventPayload.type === "delta") {
            setAssistantDraft((current) => current + eventPayload.text);
            setCaptureState("generating");
          }
          if (eventPayload.type === "final") {
            setLastResponse(eventPayload);
            setTtsText(eventPayload.text || "");
            setAssistantDraft("");
            if (eventPayload.language || eventPayload.languages?.length) {
              setLanguageInfo({
                type: "language_info",
                languages: eventPayload.languages || [],
                dominant_language: eventPayload.language || "auto",
                is_code_mixed: Boolean(eventPayload.is_code_mixed)
              });
            }
          }
          if (eventPayload.type === "audio_skipped") {
            setCaptureState("idle");
            setAssistantDraft("");
            pushActivity(setActivities, "warning", `Audio skipped: ${eventPayload.reason}.`);
          }
          if (eventPayload.type === "audio_reset") {
            pushActivity(setActivities, "warning", "Audio buffer reset on the backend.");
          }
          if (eventPayload.type === "error") {
            setCaptureState("error");
            pushActivity(setActivities, "error", eventPayload.error);
          }
        }
      );
      audioSocketRef.current = socketSession;

      const readyEvent = await socketSession.ready;
      if (readyEvent.type !== "audio_config") {
        throw new Error("Unexpected audio negotiation event.");
      }

      await capture.start({
        onChunk: (chunk) => {
          socketSession.sendChunk(chunk);
        },
        onLevel: (rms) => {
          setMicLevel(rms);
        }
      });

      clearAudioTimer(audioTimerRef);
      audioTimerRef.current = window.setInterval(() => {
        setRecordingSeconds(capture.getElapsedSeconds());
      }, 100);

      setCaptureState("recording");
      pushActivity(
        setActivities,
        "info",
        `Recording live audio at ${readyEvent.sample_rate} Hz with ${readyEvent.max_chunk_bytes} byte max chunks.`
      );
    } catch (error) {
      clearAudioTimer(audioTimerRef);
      captureRef.current = null;
      audioSocketRef.current?.close();
      audioSocketRef.current = null;
      setCaptureState("error");
      pushActivity(setActivities, "error", `Microphone start failed: ${formatError(error)}`);
    }
  }

  async function stopRecording() {
    const capture = captureRef.current;
    const socketSession = audioSocketRef.current;
    if (!capture || !socketSession) {
      return;
    }

    setCaptureState("transcribing");
    clearAudioTimer(audioTimerRef);

    try {
      const stopResult = await capture.stop();
      if (stopResult.blob) {
        setCapturePreviewUrl((current) => {
          if (current) {
            URL.revokeObjectURL(current);
          }
          return URL.createObjectURL(stopResult.blob as Blob);
        });
        setCapturePreviewMeta(
          `${stopResult.sampleRate} Hz · ${formatDurationSeconds(stopResult.durationSeconds)}`
        );
      }

      socketSession.commit();
      const completion = await socketSession.completion;
      socketSession.close();
      captureRef.current = null;
      audioSocketRef.current = null;

      if (completion.type === "final") {
        setCaptureState("idle");
        setControlRefreshTick((value) => value + 1);
        setSessionRefreshTick((value) => value + 1);
        pushActivity(setActivities, "info", "Live audio session completed successfully.");
      } else if (completion.type === "audio_skipped") {
        setCaptureState("idle");
        pushActivity(setActivities, "warning", "Captured audio was treated as silence.");
      } else if (completion.type === "error") {
        setCaptureState("error");
        pushActivity(setActivities, "error", completion.error || "Audio session failed.");
      } else {
        setCaptureState("error");
        pushActivity(setActivities, "error", "Audio session ended unexpectedly.");
      }
    } catch (error) {
      captureRef.current = null;
      audioSocketRef.current?.close();
      audioSocketRef.current = null;
      setCaptureState("error");
      pushActivity(setActivities, "error", `Microphone stop failed: ${formatError(error)}`);
    } finally {
      setMicLevel(0);
      setRecordingSeconds(0);
    }
  }

  async function handleSpeak() {
    const cleanedText = ttsText.trim();
    if (!cleanedText || ttsBusy) {
      return;
    }

    setTtsBusy(true);
    setTtsChunks([]);
    setTtsMeta("");
    pushActivity(setActivities, "info", `Requesting ${ttsMode} TTS for the current response.`);

    try {
      const fallbackLanguages =
        lastResponse?.languages || sessionDetail?.languages || [];
      const preferredLanguage =
        lastResponse?.tts_language || lastResponse?.language || sessionDetail?.selected_language || undefined;

      if (ttsMode === "rest") {
        const response = await ttsRest(baseUrl, {
          text: cleanedText,
          language: preferredLanguage,
          languages: fallbackLanguages
        });
        setTtsAudioUrl((current) => {
          if (current) {
            URL.revokeObjectURL(current);
          }
          return audioUrlFromBase64(response.audio_b64, response.mime_type);
        });
        setTtsMeta(
          `${response.provider} · ${response.language} · ${response.sample_rate} Hz`
        );
      } else {
        const chunkRecords: AudioChunkEvent[] = [];
        const finalEvent = await streamTts(
          baseUrl,
          sessionId,
          {
            text: cleanedText,
            language: preferredLanguage,
            languages: fallbackLanguages,
            segments: lastResponse?.tts_segments || [cleanedText]
          },
          (eventPayload) => {
            if (eventPayload.type === "tts_info") {
              pushActivity(
                setActivities,
                "info",
                `TTS streaming ready with ${eventPayload.segment_count} segments and providers ${eventPayload.available_providers.join(", ") || "none"}.`
              );
            }
            if (eventPayload.type === "audio_chunk") {
              chunkRecords.push(eventPayload);
              setTtsChunks([...chunkRecords]);
            }
          }
        );

        if (finalEvent.audio_b64) {
          setTtsAudioUrl((current) => {
            if (current) {
              URL.revokeObjectURL(current);
            }
            return audioUrlFromBase64(finalEvent.audio_b64, finalEvent.mime_type || "audio/wav");
          });
          setTtsMeta(
            `${finalEvent.provider || "unknown"} · ${finalEvent.language || preferredLanguage || "auto"} · ${
              finalEvent.sample_rate || 22050
            } Hz`
          );
        }
      }

      setControlRefreshTick((value) => value + 1);
      setSessionRefreshTick((value) => value + 1);
      pushActivity(setActivities, "info", "Speech synthesis completed.");
    } catch (error) {
      pushActivity(setActivities, "error", `TTS failed: ${formatError(error)}`);
    } finally {
      setTtsBusy(false);
    }
  }

  async function handleClearCurrentSession() {
    if (!sessionId) {
      return;
    }

    try {
      await clearSession(baseUrl, sessionId);
      setSessionDetail(null);
      setUploadResult(null);
      setLiveTranscript(null);
      setLastResponse(null);
      setAssistantDraft("");
      setLanguageInfo(null);
      setTtsText("");
      setReportDraft({});
      clearGeneratedMedia();
      setControlRefreshTick((value) => value + 1);
      setSessionRefreshTick((value) => value + 1);
      pushActivity(setActivities, "warning", `Cleared session ${sessionId}.`);
    } catch (error) {
      pushActivity(setActivities, "error", `Session clear failed: ${formatError(error)}`);
    }
  }

  function handleCreateSession() {
    const nextSessionId = buildSessionId();
    setSessionId(nextSessionId);
    setSessionDetail(null);
    setUploadResult(null);
    setLiveTranscript(null);
    setLastResponse(null);
    setAssistantDraft("");
    setLanguageInfo(null);
    setTtsText("");
    setReportDraft({});
    clearGeneratedMedia();
    pushActivity(setActivities, "info", `Created new working session ${nextSessionId}.`);
  }

  function hydrateReportFromConversation() {
    setReportDraft(deriveStructuredReport({
      domain,
      snapshot: sessionDetail,
      uploadedTranscript: uploadResult?.text,
      liveTranscript: liveTranscript?.text,
      latestAssistant: latestAssistantMessage?.content || lastResponse?.text || "",
      assistantDraft
    }));
    pushActivity(setActivities, "info", "Structured review draft refreshed from the latest conversation.");
  }

  const transcriptCards = [
    ...(liveTranscript
      ? [
          {
            id: "live-transcript",
            source: "live-stream",
            text: liveTranscript.text,
            dominant_language: liveTranscript.language,
            languages: liveTranscript.languages || [],
            is_code_mixed: liveTranscript.is_code_mixed || false,
            segments: liveTranscript.segments || [],
            created_at: "active"
          }
        ]
      : []),
    ...(uploadResult
      ? [
          {
            id: "upload-transcript",
            source: "upload-preview",
            text: uploadResult.text,
            dominant_language: uploadResult.language,
            languages: uploadResult.languages || [],
            is_code_mixed: uploadResult.is_code_mixed || false,
            segments: uploadResult.segments || [],
            created_at: "active"
          }
        ]
      : []),
    ...(filteredTranscripts
      .slice()
      .reverse()
      .map((record) => ({
        id: String(record.id),
        source: record.source,
        text: record.text,
        dominant_language: record.dominant_language,
        languages: record.languages,
        is_code_mixed: record.is_code_mixed,
        segments: record.segments,
        created_at: record.created_at
      })))
  ];

  const assistantCards = [
    ...(assistantDraft
      ? [
          {
            id: "assistant-draft",
            text: assistantDraft,
            language: (lastResponse?.language || languageInfo?.dominant_language || "auto") as string,
            created_at: "streaming"
          }
        ]
      : []),
    ...filteredMessages
      .filter((message) => message.role === "assistant")
      .slice()
      .reverse()
      .map((message) => ({
        id: String(message.id),
        text: message.content,
        language:
          sessionDetail?.selected_language ||
          (lastResponse?.language as string) ||
          "auto",
        created_at: message.created_at
      }))
  ];

  const averageLatency = computeAverageLatency(sessionDetail?.telemetry || []);
  const errorCount = (sessionDetail?.telemetry || []).filter(
    (record) => record.kind === "error"
  ).length;

  return (
    <div className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">NudiScribe Voice Operations Surface</p>
          <h1>Live multilingual conversation, review, and session control.</h1>
          <p className="hero-copy">
            This frontend is wired to the current FastAPI backend without changing the
            existing speech workflow: REST chat and transcription, streamed text chat,
            live PCM audio ingestion, streamed TTS, session management, and persisted
            history.
          </p>
        </div>
        <div className="hero-status">
          <StatusPill label={health?.status || "offline"} tone={statusTone(health?.status)} />
          <StatusPill
            label={health?.tts_real_speech_ready ? "real-tts-ready" : "tone-fallback"}
            tone={health?.tts_real_speech_ready ? "good" : "warning"}
          />
          <StatusPill label={domain === "healthcare" ? "healthcare" : "financial"} tone="neutral" />
        </div>
      </header>

      <main className="app-grid">
        <section className="panel">
          <div className="section-head">
            <div>
              <p className="section-kicker">Command Center</p>
              <h2>Backend status, session control, and domain mode.</h2>
            </div>
            <button
              className="ghost-button"
              type="button"
              onClick={() => {
                setControlRefreshTick((value) => value + 1);
                setSessionRefreshTick((value) => value + 1);
              }}
            >
              Refresh
            </button>
          </div>

          <form className="connection-form" onSubmit={handleApplyBaseUrl}>
            <label>
              Backend URL
              <input
                value={baseUrlDraft}
                onChange={(event) => setBaseUrlDraft(event.target.value)}
                placeholder="http://127.0.0.1:8000"
              />
            </label>
            <button className="primary-button" type="submit">
              Reconnect
            </button>
          </form>

          <div className="domain-toggle">
            <button
              type="button"
              className={domain === "healthcare" ? "toggle active" : "toggle"}
              onClick={() => setDomain("healthcare")}
            >
              Healthcare
            </button>
            <button
              type="button"
              className={domain === "financial" ? "toggle active" : "toggle"}
              onClick={() => setDomain("financial")}
            >
              Financial / Survey
            </button>
          </div>

          <div className="metric-grid">
            <MetricCard label="Service" value={serviceInfo?.service || "Unavailable"} />
            <MetricCard label="Model" value={health?.model || serviceInfo?.model || "Unknown"} />
            <MetricCard
              label="Active Sessions"
              value={String(health?.sessions_active ?? sessions.length ?? 0)}
            />
            <MetricCard
              label="Uptime"
              value={health ? formatDurationSeconds(health.uptime_seconds) : "Unavailable"}
            />
          </div>

          <div className="feature-strip">
            {(serviceInfo?.features || []).map((feature) => (
              <span className="feature-pill" key={feature}>
                {feature}
              </span>
            ))}
          </div>

          <div className="status-columns">
            <div className="status-card">
              <h3>Health Diagnostics</h3>
              <p>
                Current status: <strong>{health?.status || "offline"}</strong>
              </p>
              <p className="supporting-copy">
                Live audio uses the backend-selected ASR runtime. This frontend only
                streams raw PCM into the existing workflow.
              </p>
              <p>
                TTS providers:{" "}
                <strong>{health?.tts_providers?.join(", ") || "none available"}</strong>
              </p>
              <p>
                Real speech providers:{" "}
                <strong>{health?.tts_real_providers?.join(", ") || "none configured"}</strong>
              </p>
              <ul className="issue-list">
                {(health?.warnings || []).slice(0, 5).map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
                {(health?.errors || []).slice(0, 5).map((error) => (
                  <li key={error} className="issue-error">
                    {error}
                  </li>
                ))}
              </ul>
            </div>

            <div className="status-card">
              <h3>Session Control</h3>
              <label>
                Active session
                <select
                  value={sessionId}
                  onChange={(event) => setSessionId(event.target.value)}
                >
                  <option value={sessionId}>{sessionId}</option>
                  {sessions
                    .filter((item) => item.session_id !== sessionId)
                    .map((item) => (
                      <option key={item.session_id} value={item.session_id}>
                        {item.session_id}
                      </option>
                    ))}
                </select>
              </label>
              <div className="button-row">
                <button className="primary-button" type="button" onClick={handleCreateSession}>
                  New Session
                </button>
                <button className="ghost-button" type="button" onClick={handleClearCurrentSession}>
                  Clear Session
                </button>
              </div>
              <p className="supporting-copy">
                Selected language:{" "}
                <strong>{sessionDetail?.selected_language || currentSummary?.selected_language || "auto"}</strong>
              </p>
              <p className="supporting-copy">
                Tracked languages:{" "}
                <strong>{(sessionDetail?.languages || currentSummary?.languages || []).join(", ") || "none yet"}</strong>
              </p>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="section-head">
            <div>
              <p className="section-kicker">Live Conversation Workspace</p>
              <h2>Every current endpoint is wired into one operator flow.</h2>
            </div>
            <div className="status-stack">
              <StatusPill label={textMode} tone="neutral" />
              <StatusPill label={captureState} tone={captureTone(captureState)} />
              <StatusPill label={ttsMode} tone="neutral" />
            </div>
          </div>

          <div className="workspace-grid">
            <div className="stack">
              <article className="subpanel">
                <h3>Text Conversation</h3>
                <p className="supporting-copy">
                  Use REST for one-shot validation or WebSocket for streamed assistant output.
                </p>
                <div className="button-row compact">
                  <button
                    type="button"
                    className={textMode === "websocket" ? "toggle active" : "toggle"}
                    onClick={() => setTextMode("websocket")}
                  >
                    WebSocket
                  </button>
                  <button
                    type="button"
                    className={textMode === "rest" ? "toggle active" : "toggle"}
                    onClick={() => setTextMode("rest")}
                  >
                    REST
                  </button>
                </div>
                <form className="composer" onSubmit={handleTextSubmit}>
                  <textarea
                    value={textInput}
                    onChange={(event) => setTextInput(event.target.value)}
                    placeholder="Type in English, Hindi, Kannada, or code-mixed speech text."
                    rows={4}
                  />
                  <div className="button-row">
                    <button className="primary-button" type="submit" disabled={textBusy}>
                      {textBusy ? "Sending..." : "Send"}
                    </button>
                    <button
                      className="ghost-button"
                      type="button"
                      onClick={() => {
                        setTextInput(latestUserMessage?.content || "");
                      }}
                    >
                      Reuse Last User Input
                    </button>
                  </div>
                </form>
              </article>

              <article className="subpanel">
                <h3>Audio Upload Transcription</h3>
                <p className="supporting-copy">
                  Uploads now attach to the current session when possible so they appear in
                  history and the structured review surface.
                </p>
                <label className="file-input">
                  <span>{uploadBusy ? "Transcribing..." : "Upload audio file"}</span>
                  <input
                    type="file"
                    accept=".wav,.mp3,.m4a,.ogg,.webm,.flac,audio/*"
                    onChange={handleUploadChange}
                    disabled={uploadBusy}
                  />
                </label>
                {uploadResult ? (
                  <div className="micro-card">
                    <p className="micro-label">Latest upload transcript</p>
                    <p>{uploadResult.text}</p>
                    <p className="supporting-copy">
                      {uploadResult.language} · {uploadResult.languages.join(", ") || "en"} ·{" "}
                      {uploadResult.is_code_mixed ? "code-mixed" : "single-language"}
                    </p>
                  </div>
                ) : null}
              </article>

              <article className="subpanel">
                <h3>Live Microphone Stream</h3>
                <p className="supporting-copy">
                  Raw PCM streaming mirrors the workflow in <code>audio_test_client.py</code>:
                  negotiate audio config, stream chunks, then send <code>commit</code>.
                </p>
                <p className="supporting-copy">
                  The browser does not run ASR locally. It sends <code>pcm_s16le</code>{" "}
                  audio so the backend-selected base Whisper path remains authoritative.
                </p>
                <div className="mic-meter">
                  <div
                    className="mic-meter-bar"
                    style={{ width: `${Math.min(micLevel * 180, 100)}%` }}
                  />
                </div>
                <div className="mic-meta">
                  <span>{audioConfig ? `${audioConfig.sample_rate} Hz mono` : "Awaiting audio config"}</span>
                  <span>{recordingSeconds > 0 ? formatDurationSeconds(recordingSeconds) : "0.0s"}</span>
                </div>
                <div className="button-row">
                  <button
                    className="primary-button"
                    type="button"
                    onClick={startRecording}
                    disabled={captureState !== "idle"}
                  >
                    Start Live Capture
                  </button>
                  <button
                    className="ghost-button"
                    type="button"
                    onClick={stopRecording}
                    disabled={captureState !== "recording"}
                  >
                    Stop & Commit
                  </button>
                </div>
                {capturePreviewUrl ? (
                  <div className="micro-card">
                    <p className="micro-label">Captured WAV preview</p>
                    <audio controls src={capturePreviewUrl} />
                    <p className="supporting-copy">{capturePreviewMeta}</p>
                    <a className="text-link" href={capturePreviewUrl} download={`${sessionId}-capture.wav`}>
                      Download capture
                    </a>
                  </div>
                ) : null}
              </article>

              <article className="subpanel">
                <h3>Speech Synthesis</h3>
                <p className="supporting-copy">
                  Supports both <code>POST /api/tts</code> and <code>WS /ws/tts</code>.
                </p>
                <div className="button-row compact">
                  <button
                    type="button"
                    className={ttsMode === "websocket" ? "toggle active" : "toggle"}
                    onClick={() => setTtsMode("websocket")}
                  >
                    WebSocket
                  </button>
                  <button
                    type="button"
                    className={ttsMode === "rest" ? "toggle active" : "toggle"}
                    onClick={() => setTtsMode("rest")}
                  >
                    REST
                  </button>
                </div>
                <textarea
                  value={ttsText}
                  onChange={(event) => setTtsText(event.target.value)}
                  rows={4}
                  placeholder="Use the latest assistant response or type custom text to synthesize."
                />
                <div className="button-row">
                  <button className="primary-button" type="button" onClick={handleSpeak} disabled={ttsBusy}>
                    {ttsBusy ? "Synthesizing..." : "Speak"}
                  </button>
                  <button
                    className="ghost-button"
                    type="button"
                    onClick={() => setTtsText(lastResponse?.text || latestAssistantMessage?.content || "")}
                  >
                    Use Latest Response
                  </button>
                </div>
                {ttsAudioUrl ? (
                  <div className="micro-card">
                    <p className="micro-label">Synthesized output</p>
                    <audio controls src={ttsAudioUrl} autoPlay />
                    <p className="supporting-copy">{ttsMeta}</p>
                    <a className="text-link" href={ttsAudioUrl} download={`${sessionId}-tts.wav`}>
                      Download audio
                    </a>
                  </div>
                ) : null}
                {ttsChunks.length > 0 ? (
                  <div className="chunk-list">
                    {ttsChunks.map((chunk) => (
                      <div className="chunk-card" key={`${chunk.segment_index}-${chunk.provider}`}>
                        <p>
                          Segment {chunk.segment_index}: {chunk.language} via {chunk.provider}
                        </p>
                        <p className="supporting-copy">{chunk.text}</p>
                      </div>
                    ))}
                  </div>
                ) : null}
              </article>
            </div>

            <div className="stack">
              <article className="subpanel transcript-panel">
                <h3>Transcript Panel</h3>
                <p className="supporting-copy">
                  Live microphone transcripts, upload transcripts, and persisted session
                  transcripts are all surfaced here.
                </p>
                <div className="card-list">
                  {transcriptCards.length === 0 ? (
                    <EmptyState
                      title="No transcripts yet"
                      copy="Start a live capture or upload an audio file to populate the transcription stream."
                    />
                  ) : (
                    transcriptCards.map((record) => (
                      <div className="record-card" key={record.id}>
                        <div className="record-head">
                          <span className="record-source">{record.source}</span>
                          <span className="record-date">{formatDateValue(record.created_at)}</span>
                        </div>
                        <p>{record.text}</p>
                        <div className="meta-pill-row">
                          <span className="meta-pill">{record.dominant_language || "auto"}</span>
                          {record.languages.map((language) => (
                            <span className="meta-pill" key={`${record.id}-${language}`}>
                              {language}
                            </span>
                          ))}
                          {record.segments.length > 0 ? (
                            <span className="meta-pill">{record.segments.length} segments</span>
                          ) : null}
                          {record.is_code_mixed ? <span className="meta-pill warning">code-mixed</span> : null}
                        </div>
                        {record.segments.length > 0 ? (
                          <div className="segment-list">
                            {record.segments.slice(0, 3).map((segment, index) => (
                              <div className="segment-card" key={`${record.id}-segment-${index}`}>
                                <p className="segment-time">
                                  {formatSegmentTime(segment.start_ms)} to {formatSegmentTime(segment.end_ms)}
                                </p>
                                <p>{segment.text}</p>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))
                  )}
                </div>
              </article>

              <article className="subpanel transcript-panel">
                <h3>Assistant Response Panel</h3>
                <p className="supporting-copy">
                  Streamed assistant output is shown before persistence catches up.
                </p>
                <div className="card-list">
                  {assistantCards.length === 0 ? (
                    <EmptyState
                      title="No assistant output yet"
                      copy="Send text or audio to receive a response."
                    />
                  ) : (
                    assistantCards.map((message) => (
                      <div className="record-card assistant-card" key={message.id}>
                        <div className="record-head">
                          <span className="record-source">{message.language || "auto"}</span>
                          <span className="record-date">{formatDateValue(message.created_at)}</span>
                        </div>
                        <p>{message.text}</p>
                      </div>
                    ))
                  )}
                </div>
                {languageInfo ? (
                  <div className="micro-card">
                    <p className="micro-label">Latest language analysis</p>
                    <p>
                      Languages:{" "}
                      {Array.isArray(languageInfo.languages) && languageInfo.languages.length > 0
                        ? languageInfo.languages.join(", ")
                        : "unknown"}
                    </p>
                    <p className="supporting-copy">
                      Dominant: {String(languageInfo.dominant_language || "auto")} ·{" "}
                      {languageInfo.is_code_mixed ? "code-mixed" : "single-language"}
                    </p>
                  </div>
                ) : null}
              </article>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="section-head">
            <div>
              <p className="section-kicker">Editable Structured Review</p>
              <h2>Problem-statement fields, derived locally, then editable by a human.</h2>
            </div>
            <button className="ghost-button" type="button" onClick={hydrateReportFromConversation}>
              Refresh Suggestions
            </button>
          </div>

          <div className="review-grid">
            <div className="field-stack">
              <h3>Generic fields</h3>
              {GENERIC_FIELDS.map((field) => (
                <label className="field-group" key={field.key}>
                  <span>{field.label}</span>
                  <textarea
                    rows={3}
                    placeholder={field.placeholder}
                    value={reportDraft[field.key] || ""}
                    onChange={(event) =>
                      setReportDraft((current) => ({
                        ...current,
                        [field.key]: event.target.value
                      }))
                    }
                  />
                </label>
              ))}
            </div>

            <div className="field-stack">
              <h3>{domain === "healthcare" ? "Healthcare fields" : "Financial / Survey fields"}</h3>
              {DOMAIN_FIELDS[domain].map((field) => (
                <label className="field-group" key={field.key}>
                  <span>{field.label}</span>
                  <textarea
                    rows={3}
                    placeholder={field.placeholder}
                    value={reportDraft[field.key] || ""}
                    onChange={(event) =>
                      setReportDraft((current) => ({
                        ...current,
                        [field.key]: event.target.value
                      }))
                    }
                  />
                </label>
              ))}
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="section-head">
            <div>
              <p className="section-kicker">Longitudinal Dashboard</p>
              <h2>Searchable sessions, persisted history, and telemetry snapshots.</h2>
            </div>
            <label className="search-field">
              <span>Search</span>
              <input
                value={historySearch}
                onChange={(event) => setHistorySearch(event.target.value)}
                placeholder="Search sessions, transcripts, telemetry, or messages."
              />
            </label>
          </div>

          <div className="dashboard-grid">
            <div className="subpanel">
              <h3>Session Cards</h3>
              <div className="session-card-list">
                {filteredSessions.length === 0 ? (
                  <EmptyState
                    title="No persisted sessions yet"
                    copy="Conversations will appear here once a session stores messages or transcripts."
                  />
                ) : (
                  filteredSessions.map((item) => (
                    <button
                      className={item.session_id === sessionId ? "session-card active" : "session-card"}
                      type="button"
                      key={item.session_id}
                      onClick={() => setSessionId(item.session_id)}
                    >
                      <div className="session-card-head">
                        <strong>{item.session_id}</strong>
                        <span>{formatDateValue(item.updated_at)}</span>
                      </div>
                      <p>{trimText(item.last_message || item.last_transcript || "No recent summary.", 120)}</p>
                      <div className="meta-pill-row">
                        <span className="meta-pill">{item.selected_language || "auto"}</span>
                        <span className="meta-pill">{item.message_count} msgs</span>
                        <span className="meta-pill">{item.transcript_count} tx</span>
                        <span className="meta-pill">{item.telemetry_count} telem</span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>

            <div className="subpanel">
              <h3>Selected Session Snapshot</h3>
              <div className="metric-grid compact-metrics">
                <MetricCard label="Session" value={sessionId} />
                <MetricCard label="Messages" value={String(sessionDetail?.message_count || 0)} />
                <MetricCard label="Transcripts" value={String(sessionDetail?.transcript_count || 0)} />
                <MetricCard label="Avg Latency" value={averageLatency ? `${averageLatency} ms` : "n/a"} />
              </div>
              <div className="metric-grid compact-metrics">
                <MetricCard label="Errors" value={String(errorCount)} />
                <MetricCard
                  label="Languages"
                  value={(sessionDetail?.languages || currentSummary?.languages || []).join(", ") || "n/a"}
                />
                <MetricCard
                  label="Selected"
                  value={sessionDetail?.selected_language || currentSummary?.selected_language || "auto"}
                />
                <MetricCard label="Updated" value={formatDateValue(sessionDetail?.updated_at || currentSummary?.updated_at || "")} />
              </div>

              <div className="history-columns">
                <div className="history-column">
                  <h4>Messages</h4>
                  <div className="record-scroll">
                    {filteredMessages.length === 0 ? (
                      <EmptyState title="No messages" copy="Persisted user and assistant turns will appear here." />
                    ) : (
                      filteredMessages.map((message: SessionMessageRecord) => (
                        <div className="record-card" key={message.id}>
                          <div className="record-head">
                            <span className="record-source">{message.role}</span>
                            <span className="record-date">{formatDateValue(message.created_at)}</span>
                          </div>
                          <p>{message.content}</p>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div className="history-column">
                  <h4>Telemetry</h4>
                  <div className="record-scroll">
                    {filteredTelemetry.length === 0 ? (
                      <EmptyState title="No telemetry" copy="Latency and error records will appear here." />
                    ) : (
                      filteredTelemetry.map((record) => (
                        <div className="record-card" key={record.id}>
                          <div className="record-head">
                            <span className="record-source">{record.kind}</span>
                            <span className="record-date">{formatDateValue(record.created_at)}</span>
                          </div>
                          <p>
                            <strong>{record.name}</strong> · {record.status || "n/a"}
                          </p>
                          {record.latency_ms !== null ? (
                            <p className="supporting-copy">{record.latency_ms.toFixed(0)} ms</p>
                          ) : null}
                          {record.error_message ? (
                            <p className="supporting-copy issue-error">{record.error_message}</p>
                          ) : null}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="section-head">
            <div>
              <p className="section-kicker">Outbound Workflow Placeholder</p>
              <h2>Future-facing shell for automated outbound engagement.</h2>
            </div>
          </div>
          <div className="placeholder-grid">
            <div className="placeholder-card">
              <h3>What exists now</h3>
              <ul className="plain-list">
                <li>Session-aware conversation state</li>
                <li>Live microphone ingestion over raw PCM WebSocket</li>
                <li>Streaming assistant responses and streamed TTS</li>
                <li>Editable structured review draft for the current session</li>
              </ul>
            </div>
            <div className="placeholder-card">
              <h3>What is still missing</h3>
              <ul className="plain-list">
                <li>Telephony or dialer integration</li>
                <li>Automated outbound orchestration</li>
                <li>Domain-configurable decision trees on the backend</li>
                <li>Compliance/security workflow hardening</li>
              </ul>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="section-head">
            <div>
              <p className="section-kicker">Operator Feed</p>
              <h2>Live validation notes from this frontend session.</h2>
            </div>
          </div>
          <div className="activity-list">
            {activities.length === 0 ? (
              <EmptyState
                title="No activity yet"
                copy="Actions, warnings, and live integration notes appear here."
              />
            ) : (
              activities.map((item) => (
                <div className={`activity-card ${item.level}`} key={item.id}>
                  <div className="record-head">
                    <span className="record-source">{item.level}</span>
                    <span className="record-date">{formatDateValue(item.created_at)}</span>
                  </div>
                  <p>{item.text}</p>
                </div>
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function MetricCard(props: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <p className="metric-label">{props.label}</p>
      <p className="metric-value">{props.value}</p>
    </div>
  );
}

function StatusPill(props: { label: string; tone: "good" | "warning" | "error" | "neutral" }) {
  return <span className={`status-pill ${props.tone}`}>{props.label}</span>;
}

function EmptyState(props: { title: string; copy: string }) {
  return (
    <div className="empty-state">
      <strong>{props.title}</strong>
      <p>{props.copy}</p>
    </div>
  );
}

function lastMessageByRole(messages: SessionMessageRecord[], role: string) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === role) {
      return messages[index];
    }
  }
  return null;
}

function pushActivity(
  setActivities: Dispatch<SetStateAction<ActivityItem[]>>,
  level: ActivityItem["level"],
  text: string
) {
  const nextItem: ActivityItem = {
    id:
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`,
    level,
    text,
    created_at: new Date().toISOString()
  };
  setActivities((current) => [nextItem, ...current].slice(0, 16));
}

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function formatDateValue(value: string): string {
  if (!value || value === "active" || value === "streaming") {
    return value || "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function formatDurationSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "0.0s";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const wholeMinutes = Math.floor(seconds / 60);
  const remainderSeconds = seconds % 60;
  return `${wholeMinutes}m ${remainderSeconds.toFixed(0)}s`;
}

function trimText(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

function computeAverageLatency(telemetry: SessionDetailResponse["telemetry"]): string {
  const latencies = telemetry
    .filter((record) => record.kind === "latency" && record.latency_ms !== null)
    .map((record) => Number(record.latency_ms));
  if (latencies.length === 0) {
    return "";
  }
  const total = latencies.reduce((sum, value) => sum + value, 0);
  return (total / latencies.length).toFixed(0);
}

function statusTone(status?: string) {
  if (status === "ok") {
    return "good";
  }
  if (status === "degraded") {
    return "warning";
  }
  if (!status) {
    return "neutral";
  }
  return "error";
}

function captureTone(state: CaptureState) {
  if (state === "idle") {
    return "neutral";
  }
  if (state === "recording" || state === "generating") {
    return "good";
  }
  if (state === "error") {
    return "error";
  }
  return "warning";
}

function clearAudioTimer(timerRef: MutableRefObject<number | null>) {
  if (timerRef.current !== null) {
    window.clearInterval(timerRef.current);
    timerRef.current = null;
  }
}

function lastTranscript(transcripts: SessionTranscriptRecord[]) {
  return transcripts.length > 0 ? transcripts[transcripts.length - 1] : null;
}

function lastTranscriptBySource(transcripts: SessionTranscriptRecord[], source: string) {
  for (let index = transcripts.length - 1; index >= 0; index -= 1) {
    if (transcripts[index].source === source) {
      return transcripts[index];
    }
  }
  return null;
}

function clearObjectUrl(url: string) {
  if (url) {
    URL.revokeObjectURL(url);
  }
}

function formatSegmentTime(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "n/a";
  }
  return `${(Number(value) / 1000).toFixed(2)}s`;
}
