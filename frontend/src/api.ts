import type {
  AudioSocketConfig,
  AudioStreamEvent,
  ChatResponse,
  DynamicExtractResponse,
  FinalEvent,
  HealthResponse,
  ReportExtractResponse,
  RootInfo,
  SessionDetailResponse,
  SessionListResponse,
  TTSResponse,
  TTSStreamEvent,
  TextStreamEvent,
  TranscribeResponse
} from "./types";

function normalizeHttpBaseUrl(rawBaseUrl: string): string {
  const trimmed = rawBaseUrl.trim().replace(/\/+$/, "");
  if (!trimmed) {
    return "http://127.0.0.1:8000";
  }
  if (trimmed.startsWith("ws://")) {
    return `http://${trimmed.slice(5)}`;
  }
  if (trimmed.startsWith("wss://")) {
    return `https://${trimmed.slice(6)}`;
  }
  return trimmed;
}

function buildWsUrl(baseUrl: string, path: string): string {
  const normalizedBaseUrl = normalizeHttpBaseUrl(baseUrl);
  if (normalizedBaseUrl.startsWith("https://")) {
    return `wss://${normalizedBaseUrl.slice(8)}${path}`;
  }
  if (normalizedBaseUrl.startsWith("http://")) {
    return `ws://${normalizedBaseUrl.slice(7)}${path}`;
  }
  return `${normalizedBaseUrl}${path}`;
}

async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${normalizeHttpBaseUrl(baseUrl)}${path}`, init);
  const rawText = await response.text();
  const payload = rawText ? JSON.parse(rawText) : {};
  if (!response.ok) {
    throw new Error(payload.error || rawText || `${response.status} ${response.statusText}`);
  }
  return payload as T;
}

export async function getRootInfo(baseUrl: string): Promise<RootInfo> {
  return requestJson<RootInfo>(baseUrl, "/");
}

export async function getHealth(baseUrl: string): Promise<HealthResponse> {
  return requestJson<HealthResponse>(baseUrl, "/api/health");
}

export async function getSessions(baseUrl: string): Promise<SessionListResponse> {
  return requestJson<SessionListResponse>(baseUrl, "/api/sessions");
}

export async function getSessionDetail(baseUrl: string, sessionId: string): Promise<SessionDetailResponse> {
  return requestJson<SessionDetailResponse>(
    baseUrl,
    `/api/session/${encodeURIComponent(sessionId)}`
  );
}

export async function clearSession(baseUrl: string, sessionId: string): Promise<void> {
  await requestJson(baseUrl, `/api/session/${encodeURIComponent(sessionId)}`, {
    method: "DELETE"
  });
}

export async function startConsultation(
  baseUrl: string,
  payload: { session_id: string; consultation_mode: string; response_language?: string }
): Promise<ChatResponse> {
  return requestJson<ChatResponse>(baseUrl, "/api/consultation/start", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function chatRest(
  baseUrl: string,
  payload: {
    session_id: string;
    text: string;
    speaker_role?: string;
    consultation_mode: string;
  }
): Promise<ChatResponse> {
  return requestJson<ChatResponse>(baseUrl, "/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function transcribeFile(
  baseUrl: string,
  file: File,
  sessionId?: string
): Promise<TranscribeResponse> {
  const body = new FormData();
  body.set("file", file);
  if (sessionId) {
    body.set("session_id", sessionId);
  }
  return requestJson<TranscribeResponse>(baseUrl, "/api/transcribe", {
    method: "POST",
    body
  });
}

export async function extractReportFile(
  baseUrl: string,
  file: File,
  sessionId?: string
): Promise<ReportExtractResponse> {
  const body = new FormData();
  body.set("file", file);
  if (sessionId) {
    body.set("session_id", sessionId);
  }
  return requestJson<ReportExtractResponse>(baseUrl, "/api/report/extract", {
    method: "POST",
    body
  });
}

export async function dynamicExtract(
  baseUrl: string,
  payload: {
    text: string;
    schema: Record<string, unknown>;
    context?: string;
    session_id?: string;
  }
): Promise<DynamicExtractResponse> {
  return requestJson<DynamicExtractResponse>(baseUrl, "/api/extract/dynamic", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function ttsRest(
  baseUrl: string,
  payload: {
    text: string;
    language?: string;
    languages?: string[];
  }
): Promise<TTSResponse> {
  return requestJson<TTSResponse>(baseUrl, "/api/tts", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function streamTextChat(
  baseUrl: string,
  sessionId: string,
  payload: {
    text: string;
    speaker_role?: string;
    consultation_mode: string;
    response_language?: string;
  },
  onEvent: (event: TextStreamEvent) => void
): Promise<FinalEvent> {
  const socket = new WebSocket(buildWsUrl(baseUrl, `/ws/${encodeURIComponent(sessionId)}`));

  return new Promise<FinalEvent>((resolve, reject) => {
    let settled = false;

    const fail = (error: Error) => {
      if (settled) {
        return;
      }
      settled = true;
      socket.close();
      reject(error);
    };

    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({ type: "input", ...payload }));
    });

    socket.addEventListener("message", (message) => {
      try {
        const eventPayload = JSON.parse(String(message.data)) as TextStreamEvent;
        onEvent(eventPayload);
        if (eventPayload.type === "final") {
          settled = true;
          socket.close();
          resolve(eventPayload);
          return;
        }
        if (eventPayload.type === "error") {
          fail(new Error(eventPayload.error || "Text stream failed."));
        }
      } catch (error) {
        fail(error instanceof Error ? error : new Error("Invalid text stream payload."));
      }
    });

    socket.addEventListener("error", () => {
      fail(new Error("Text WebSocket connection failed."));
    });

    socket.addEventListener("close", () => {
      if (!settled) {
        fail(new Error("Text WebSocket closed before final response."));
      }
    });
  });
}

export interface AudioSocketSession {
  ready: Promise<AudioStreamEvent>;
  completion: Promise<AudioStreamEvent>;
  sendChunk: (chunk: ArrayBuffer) => void;
  commit: () => void;
  ping: () => void;
  reset: () => void;
  close: () => void;
}

export function createAudioSocketSession(
  baseUrl: string,
  sessionId: string,
  config: AudioSocketConfig,
  onEvent: (event: AudioStreamEvent) => void
): AudioSocketSession {
  const socket = new WebSocket(buildWsUrl(baseUrl, `/ws/audio/${encodeURIComponent(sessionId)}`));
  socket.binaryType = "arraybuffer";

  let readyResolve: (value: AudioStreamEvent) => void = () => undefined;
  let readyReject: (reason?: unknown) => void = () => undefined;
  let completionResolve: (value: AudioStreamEvent) => void = () => undefined;
  let completionReject: (reason?: unknown) => void = () => undefined;
  let completionSettled = false;

  const ready = new Promise<AudioStreamEvent>((resolve, reject) => {
    readyResolve = resolve;
    readyReject = reject;
  });

  const completion = new Promise<AudioStreamEvent>((resolve, reject) => {
    completionResolve = resolve;
    completionReject = reject;
  });

  socket.addEventListener("open", () => {
    socket.send(
      JSON.stringify({
        type: "start",
        sample_rate: config.sample_rate,
        channels: config.channels,
        sample_width: config.sample_width,
        encoding: config.encoding,
        consultation_mode: config.consultation_mode,
        speaker_role: config.speaker_role,
        response_language: config.response_language,
        turn_timeout_seconds: config.turn_timeout_seconds,
        transcription_only: config.transcription_only
      })
    );
  });

  socket.addEventListener("message", (message) => {
    try {
      const payload = JSON.parse(String(message.data)) as AudioStreamEvent;
      onEvent(payload);
      if (payload.type === "audio_config") {
        readyResolve(payload);
      }
      if (
        payload.type === "final" ||
        payload.type === "stream_complete" ||
        payload.type === "audio_skipped" ||
        payload.type === "error"
      ) {
        completionSettled = true;
        completionResolve(payload);
      }
    } catch (error) {
      if (!completionSettled) {
        completionReject(error instanceof Error ? error : new Error("Invalid audio payload."));
      }
    }
  });

  socket.addEventListener("error", () => {
    const error = new Error("Audio WebSocket connection failed.");
    readyReject(error);
    if (!completionSettled) {
      completionReject(error);
    }
  });

  socket.addEventListener("close", () => {
    if (!completionSettled) {
      completionReject(new Error("Audio WebSocket closed before a terminal event."));
    }
  });

  return {
    ready,
    completion,
    sendChunk(chunk) {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(chunk);
      }
    },
    commit() {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send("commit");
      }
    },
    ping() {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send("ping");
      }
    },
    reset() {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send("reset");
      }
    },
    close() {
      socket.close();
    }
  };
}

export async function streamTts(
  baseUrl: string,
  sessionId: string,
  payload: {
    text: string;
    language?: string;
    languages?: string[];
    segments?: Array<string | { text: string; language?: string; languages?: string[] }>;
  },
  onEvent: (event: TTSStreamEvent) => void
): Promise<FinalEvent> {
  const socket = new WebSocket(buildWsUrl(baseUrl, `/ws/tts/${encodeURIComponent(sessionId)}`));

  return new Promise<FinalEvent>((resolve, reject) => {
    let settled = false;

    const fail = (error: Error) => {
      if (settled) {
        return;
      }
      settled = true;
      socket.close();
      reject(error);
    };

    socket.addEventListener("message", (message) => {
      try {
        const payloadEvent = JSON.parse(String(message.data)) as TTSStreamEvent;
        onEvent(payloadEvent);
        if (payloadEvent.type === "final") {
          settled = true;
          socket.close();
          resolve(payloadEvent);
          return;
        }
        if (payloadEvent.type === "error") {
          fail(new Error(payloadEvent.error || "TTS stream failed."));
        }
      } catch (error) {
        fail(error instanceof Error ? error : new Error("Invalid TTS payload."));
      }
    });

    socket.addEventListener("error", () => {
      fail(new Error("TTS WebSocket connection failed."));
    });

    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({ type: "synthesize", ...payload }));
    });

    socket.addEventListener("close", () => {
      if (!settled) {
        fail(new Error("TTS WebSocket closed before final response."));
      }
    });
  });
}

export function audioUrlFromBase64(audioBase64: string, mimeType = "audio/wav"): string {
  const raw = window.atob(audioBase64);
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) {
    bytes[index] = raw.charCodeAt(index);
  }
  return URL.createObjectURL(new Blob([bytes], { type: mimeType }));
}
