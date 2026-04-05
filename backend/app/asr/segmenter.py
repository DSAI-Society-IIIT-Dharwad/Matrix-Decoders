from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

import torch
import torchaudio

from ..logger import get_logger


TARGET_SAMPLE_RATE = 16000
log = get_logger("asr.segmenter")


@dataclass
class AudioSegment:
    index: int
    start_ms: int
    end_ms: int
    path: str


def _normalize_waveform(waveform: torch.Tensor, sample_rate: int) -> torch.Tensor:
    if waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)

    if waveform.size(0) > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    if sample_rate != TARGET_SAMPLE_RATE:
        resampler = torchaudio.transforms.Resample(sample_rate, TARGET_SAMPLE_RATE)
        waveform = resampler(waveform)

    return waveform


def _trim_edges_with_torchaudio_vad(waveform: torch.Tensor) -> torch.Tensor:
    """Trim non-speech leading/trailing regions using torchaudio VAD when available."""
    try:
        vad = torchaudio.transforms.Vad(
            sample_rate=TARGET_SAMPLE_RATE,
            trigger_level=7.0,
            trigger_time=0.20,
            search_time=0.8,
            allowed_gap=0.20,
        )
        trimmed = vad(waveform)
        if trimmed.numel() == 0:
            return waveform

        # Trim trailing silence by applying VAD on reversed waveform.
        reversed_trimmed = torch.flip(trimmed, dims=[-1])
        reversed_trimmed = vad(reversed_trimmed)
        if reversed_trimmed.numel() == 0:
            return trimmed
        return torch.flip(reversed_trimmed, dims=[-1])
    except Exception as exc:
        log.debug(f"torchaudio VAD trim unavailable, using adaptive frame VAD only: {exc}")
        return waveform


def _estimate_vad_thresholds(energies: list[float], floor_threshold: float) -> tuple[float, float]:
    if not energies:
        return floor_threshold, floor_threshold * 0.8

    energy_tensor = torch.tensor(energies, dtype=torch.float32)
    noise_floor = float(torch.quantile(energy_tensor, 0.20).item())
    speech_peak = float(torch.quantile(energy_tensor, 0.90).item())
    dynamic_range = max(speech_peak - noise_floor, 1e-4)

    enter_threshold = max(
        floor_threshold,
        noise_floor + dynamic_range * 0.35,
    )
    exit_threshold = max(
        floor_threshold * 0.75,
        noise_floor + dynamic_range * 0.22,
    )

    # Ensure stable hysteresis (exit must stay below enter).
    if exit_threshold >= enter_threshold:
        exit_threshold = max(enter_threshold * 0.85, floor_threshold * 0.75)

    return enter_threshold, exit_threshold


def segment_audio(
    audio_path: str,
    output_dir: str,
    frame_ms: int = 30,
    min_speech_ms: int = 300,
    min_silence_ms: int = 350,
    max_segment_ms: int = 8000,
    energy_threshold: float = 0.012,
) -> List[AudioSegment]:
    """Split audio into speech-like segments using adaptive VAD + hysteresis."""
    waveform, sample_rate = torchaudio.load(audio_path)
    waveform = _normalize_waveform(waveform, sample_rate)
    waveform = _trim_edges_with_torchaudio_vad(waveform)

    samples = waveform.squeeze(0).float()
    total_samples = samples.numel()
    if total_samples == 0:
        return []

    frame_size = max(int(TARGET_SAMPLE_RATE * frame_ms / 1000), 1)
    min_speech_frames = max(int(min_speech_ms / frame_ms), 1)
    min_silence_frames = max(int(min_silence_ms / frame_ms), 1)
    max_segment_frames = max(int(max_segment_ms / frame_ms), min_speech_frames)

    energies: list[float] = []
    for start in range(0, total_samples, frame_size):
        frame = samples[start:start + frame_size]
        if frame.numel() == 0:
            continue
        energies.append(float(torch.sqrt(torch.mean(frame ** 2)).item()))

    if not energies:
        return []

    enter_threshold, exit_threshold = _estimate_vad_thresholds(energies, floor_threshold=energy_threshold)
    max_energy = max(energies)

    speech_ranges = []
    in_speech = False
    speech_start = 0
    silence_frames = 0
    speech_frames = 0
    pre_speech_frames = 0

    for index, energy in enumerate(energies):
        if in_speech:
            if energy >= exit_threshold:
                silence_frames = 0
                speech_frames += 1
            else:
                silence_frames += 1
                if silence_frames >= min_silence_frames:
                    speech_end = index - silence_frames + 1
                    if speech_end - speech_start >= min_speech_frames:
                        speech_ranges.append((speech_start, speech_end))
                    in_speech = False
                    silence_frames = 0
                    speech_frames = 0
                    pre_speech_frames = 0
        else:
            if energy >= enter_threshold:
                pre_speech_frames += 1
            else:
                pre_speech_frames = 0
            if pre_speech_frames >= min_speech_frames:
                in_speech = True
                speech_start = max(0, index - pre_speech_frames + 1)
                speech_frames = pre_speech_frames
                silence_frames = 0

    if in_speech:
        speech_end = len(energies)
        if speech_end - speech_start >= min_speech_frames:
            speech_ranges.append((speech_start, speech_end))

    if not speech_ranges:
        # Keep previous fallback behavior only when clear speech energy is present.
        if max_energy < max(enter_threshold * 1.15, 0.006):
            return []
        duration_ms = int(total_samples * 1000 / TARGET_SAMPLE_RATE)
        return _save_segments(samples, [(0, len(energies))], output_dir, frame_size, duration_ms)

    split_ranges = []
    for start_frame, end_frame in speech_ranges:
        current_start = start_frame
        while end_frame - current_start > max_segment_frames:
            split_ranges.append((current_start, current_start + max_segment_frames))
            current_start += max_segment_frames
        split_ranges.append((current_start, end_frame))

    duration_ms = int(total_samples * 1000 / TARGET_SAMPLE_RATE)
    return _save_segments(samples, split_ranges, output_dir, frame_size, duration_ms)


def _save_segments(
    samples: torch.Tensor,
    frame_ranges: list[tuple[int, int]],
    output_dir: str,
    frame_size: int,
    duration_ms: int,
) -> List[AudioSegment]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    segments: List[AudioSegment] = []
    total_samples = samples.numel()

    for index, (start_frame, end_frame) in enumerate(frame_ranges, start=1):
        start_sample = min(start_frame * frame_size, total_samples)
        end_sample = min(end_frame * frame_size, total_samples)
        if end_sample <= start_sample:
            continue

        chunk = samples[start_sample:end_sample].unsqueeze(0)
        segment_path = output_path / f"segment_{index:03d}.wav"
        torchaudio.save(str(segment_path), chunk, TARGET_SAMPLE_RATE)

        start_ms = int(start_sample * 1000 / TARGET_SAMPLE_RATE)
        end_ms = min(int(end_sample * 1000 / TARGET_SAMPLE_RATE), duration_ms)
        segments.append(
            AudioSegment(
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                path=str(segment_path),
            )
        )

    return segments


def create_segment_dir() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix="nudiscribe_segments_")
