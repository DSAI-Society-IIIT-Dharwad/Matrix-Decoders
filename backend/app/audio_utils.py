from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AudioFormatConfig:
    """Runtime audio format for PCM audio WebSocket sessions."""

    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2
    encoding: str = "pcm_s16le"

    def validate(self) -> None:
        if self.encoding != "pcm_s16le":
            raise ValueError("Only 'pcm_s16le' encoding is currently supported.")
        if not 8000 <= self.sample_rate <= 48000:
            raise ValueError("Sample rate must be between 8000 and 48000 Hz.")
        if self.channels not in {1, 2}:
            raise ValueError("Only mono or stereo PCM audio is supported.")
        if self.sample_width != 2:
            raise ValueError("Only 16-bit PCM audio is supported.")

    @property
    def frame_size(self) -> int:
        return self.channels * self.sample_width

    def max_chunk_bytes(self, max_duration_seconds: float = 1.0) -> int:
        return max(int(self.sample_rate * self.frame_size * max_duration_seconds), self.frame_size)

    def max_buffer_bytes(self, max_duration_seconds: float = 3.0) -> int:
        return max(int(self.sample_rate * self.frame_size * max_duration_seconds), self.frame_size)

    @classmethod
    def from_message(cls, payload: dict) -> "AudioFormatConfig":
        config = cls(
            sample_rate=int(payload.get("sample_rate", 16000)),
            channels=int(payload.get("channels", 1)),
            sample_width=int(payload.get("sample_width", 2)),
            encoding=str(payload.get("encoding", "pcm_s16le")).lower(),
        )
        config.validate()
        return config


def trim_pcm16_silence(
    pcm_bytes: bytes,
    channels: int = 1,
    silence_threshold: int = 550,
) -> bytes:
    """Trim low-energy leading and trailing silence from PCM16 audio."""
    if not pcm_bytes:
        return pcm_bytes

    frame_size = max(channels, 1) * 2
    if len(pcm_bytes) < frame_size:
        return b""

    start = 0
    end = len(pcm_bytes)

    while start + frame_size <= end:
        frame = pcm_bytes[start:start + frame_size]
        samples = memoryview(frame).cast("h")
        if max(abs(sample) for sample in samples) >= silence_threshold:
            break
        start += frame_size

    while end - frame_size >= start:
        frame = pcm_bytes[end - frame_size:end]
        samples = memoryview(frame).cast("h")
        if max(abs(sample) for sample in samples) >= silence_threshold:
            break
        end -= frame_size

    if start >= end:
        return b""

    return pcm_bytes[start:end]
