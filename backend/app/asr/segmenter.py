from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

import torch
import torchaudio


TARGET_SAMPLE_RATE = 16000


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


def segment_audio(
    audio_path: str,
    output_dir: str,
    frame_ms: int = 30,
    min_speech_ms: int = 300,
    min_silence_ms: int = 350,
    max_segment_ms: int = 8000,
    energy_threshold: float = 0.012,
) -> List[AudioSegment]:
    """Split audio into speech-like segments using frame energy."""
    waveform, sample_rate = torchaudio.load(audio_path)
    waveform = _normalize_waveform(waveform, sample_rate)

    samples = waveform.squeeze(0)
    total_samples = samples.numel()
    if total_samples == 0:
        return []

    frame_size = max(int(TARGET_SAMPLE_RATE * frame_ms / 1000), 1)
    min_speech_frames = max(int(min_speech_ms / frame_ms), 1)
    min_silence_frames = max(int(min_silence_ms / frame_ms), 1)
    max_segment_frames = max(int(max_segment_ms / frame_ms), min_speech_frames)

    energies = []
    for start in range(0, total_samples, frame_size):
        frame = samples[start:start + frame_size]
        if frame.numel() == 0:
            continue
        energies.append(float(torch.sqrt(torch.mean(frame.float() ** 2)).item()))

    if not energies:
        return []

    speech_ranges = []
    in_speech = False
    speech_start = 0
    silence_frames = 0
    speech_frames = 0

    for index, energy in enumerate(energies):
        if energy >= energy_threshold:
            if not in_speech:
                in_speech = True
                speech_start = index
                speech_frames = 0
            speech_frames += 1
            silence_frames = 0
        elif in_speech:
            silence_frames += 1
            if silence_frames >= min_silence_frames:
                speech_end = index - silence_frames + 1
                if speech_end - speech_start >= min_speech_frames:
                    speech_ranges.append((speech_start, speech_end))
                in_speech = False
                silence_frames = 0

    if in_speech:
        speech_end = len(energies)
        if speech_end - speech_start >= min_speech_frames:
            speech_ranges.append((speech_start, speech_end))

    if not speech_ranges:
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
