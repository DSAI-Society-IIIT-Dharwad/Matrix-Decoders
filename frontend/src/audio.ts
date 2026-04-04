const DEFAULT_SAMPLE_RATE = 16000;
const STREAM_CHUNK_SECONDS = 0.25;

type CaptureCallbacks = {
  onChunk: (chunk: ArrayBuffer) => void;
  onLevel?: (rms: number) => void;
};

type PreparedCapture = {
  sampleRate: number;
  channels: number;
  sampleWidth: number;
};

type CaptureStopResult = {
  blob: Blob | null;
  sampleRate: number;
  durationSeconds: number;
};

function float32ToInt16(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index]));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function clonePcmBuffer(input: Int16Array): ArrayBuffer {
  const copy = new Int16Array(input.length);
  copy.set(input);
  return copy.buffer;
}

function createWavBlob(chunks: ArrayBuffer[], sampleRate: number, channels: number): Blob | null {
  if (chunks.length === 0) {
    return null;
  }

  let dataBytes = 0;
  for (const chunk of chunks) {
    dataBytes += chunk.byteLength;
  }

  const header = new ArrayBuffer(44);
  const view = new DataView(header);

  const writeString = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels * 2, true);
  view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataBytes, true);

  return new Blob([header, ...chunks], { type: "audio/wav" });
}

type WebkitWindow = Window & {
  webkitAudioContext?: typeof AudioContext;
};

export class BrowserAudioCapture {
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private processorNode: AudioWorkletNode | null = null;
  private sinkNode: GainNode | null = null;
  private prepared = false;
  private recording = false;
  private sampleRate = DEFAULT_SAMPLE_RATE;
  private readonly channels = 1;
  private readonly sampleWidth = 2;
  private samplesPerChunk = DEFAULT_SAMPLE_RATE * STREAM_CHUNK_SECONDS;
  private pendingChunks: Int16Array[] = [];
  private pendingSamples = 0;
  private capturedChunks: ArrayBuffer[] = [];
  private callbacks: CaptureCallbacks | null = null;
  private startedAt = 0;

  async prepare(): Promise<PreparedCapture> {
    if (this.prepared) {
      return {
        sampleRate: this.sampleRate,
        channels: this.channels,
        sampleWidth: this.sampleWidth
      };
    }

    const AudioContextCtor = window.AudioContext || (window as WebkitWindow).webkitAudioContext;
    if (!AudioContextCtor || typeof AudioWorkletNode === "undefined") {
      throw new Error("This browser does not support AudioWorklet-based PCM capture.");
    }

    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });

    this.audioContext = new AudioContextCtor({ sampleRate: DEFAULT_SAMPLE_RATE });
    await this.audioContext.audioWorklet.addModule("/audio-capture.worklet.js");

    this.sampleRate = this.audioContext.sampleRate;
    this.samplesPerChunk = Math.max(Math.floor(this.sampleRate * STREAM_CHUNK_SECONDS), 1);
    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
    this.processorNode = new AudioWorkletNode(this.audioContext, "nudiscribe-capture-processor");
    this.sinkNode = this.audioContext.createGain();
    this.sinkNode.gain.value = 0;

    this.processorNode.port.onmessage = (message) => {
      if (!this.recording) {
        return;
      }

      const payload = message.data;
      if (!payload || payload.type !== "audio") {
        return;
      }

      const samples =
        payload.samples instanceof Float32Array
          ? payload.samples
          : new Float32Array(payload.samples);
      const chunk = float32ToInt16(samples);
      this.capturedChunks.push(clonePcmBuffer(chunk));
      this.pendingChunks.push(chunk);
      this.pendingSamples += chunk.length;

      if (this.callbacks?.onLevel) {
        this.callbacks.onLevel(Number(payload.rms || 0));
      }

      while (this.pendingSamples >= this.samplesPerChunk) {
        const pcmChunk = this.consumeSamples(this.samplesPerChunk);
        this.callbacks?.onChunk(clonePcmBuffer(pcmChunk));
      }
    };

    this.prepared = true;

    return {
      sampleRate: this.sampleRate,
      channels: this.channels,
      sampleWidth: this.sampleWidth
    };
  }

  async start(callbacks: CaptureCallbacks): Promise<PreparedCapture> {
    const prepared = await this.prepare();
    if (!this.audioContext || !this.sourceNode || !this.processorNode || !this.sinkNode) {
      throw new Error("Audio capture is not prepared.");
    }

    this.callbacks = callbacks;
    this.pendingChunks = [];
    this.pendingSamples = 0;
    this.capturedChunks = [];

    await this.audioContext.resume();
    this.sourceNode.connect(this.processorNode);
    this.processorNode.connect(this.sinkNode);
    this.sinkNode.connect(this.audioContext.destination);
    this.recording = true;
    this.startedAt = performance.now();

    return prepared;
  }

  async stop(): Promise<CaptureStopResult> {
    if (!this.prepared) {
      return {
        blob: null,
        sampleRate: this.sampleRate,
        durationSeconds: 0
      };
    }

    if (this.recording) {
      while (this.pendingSamples > 0) {
        const pcmChunk = this.consumeSamples(this.pendingSamples);
        this.callbacks?.onChunk(clonePcmBuffer(pcmChunk));
      }
    }

    this.recording = false;
    this.callbacks = null;

    try {
      this.sourceNode?.disconnect();
    } catch {
      // Ignore disconnect errors during teardown.
    }
    try {
      this.processorNode?.disconnect();
    } catch {
      // Ignore disconnect errors during teardown.
    }
    try {
      this.sinkNode?.disconnect();
    } catch {
      // Ignore disconnect errors during teardown.
    }

    this.mediaStream?.getTracks().forEach((track) => track.stop());
    await this.audioContext?.close();

    const durationSeconds =
      this.startedAt > 0 ? (performance.now() - this.startedAt) / 1000 : 0;
    const blob = createWavBlob(this.capturedChunks, this.sampleRate, this.channels);

    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.processorNode = null;
    this.sinkNode = null;
    this.prepared = false;
    this.startedAt = 0;

    return {
      blob,
      sampleRate: this.sampleRate,
      durationSeconds
    };
  }

  getElapsedSeconds(): number {
    if (!this.recording || this.startedAt <= 0) {
      return 0;
    }
    return (performance.now() - this.startedAt) / 1000;
  }

  private consumeSamples(sampleCount: number): Int16Array {
    const output = new Int16Array(sampleCount);
    let offset = 0;

    while (offset < sampleCount && this.pendingChunks.length > 0) {
      const head = this.pendingChunks[0];
      const takeCount = Math.min(head.length, sampleCount - offset);
      output.set(head.subarray(0, takeCount), offset);

      if (takeCount >= head.length) {
        this.pendingChunks.shift();
      } else {
        this.pendingChunks[0] = head.subarray(takeCount);
      }

      offset += takeCount;
      this.pendingSamples -= takeCount;
    }

    return output;
  }
}
