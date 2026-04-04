from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import torch
import torchaudio

from datasets import load_dataset
from huggingface_hub import HfApi

from ..config import settings
from ..language import detect_scripts, get_dominant_language, is_code_mixed
from ..logger import get_logger
from ..transcript_cleaner import clean_transcript
from .dataset_sources import CURATED_SOURCES, DatasetSource

log = get_logger("training.corpus")

LANGUAGE_BUCKETS = ("english", "hindi", "kannada", "code_mixed")
BUCKET_BY_LANGUAGE = {
    "en": "english",
    "hi": "hindi",
    "kn": "kannada",
}


@dataclass
class CorpusBuildConfig:
    corpus_root: Path
    hf_token: str = ""
    target_hours_per_bucket: float = 40.0
    target_code_mixed_hours: float = 20.0
    local_archive_hours_per_bucket: float = 5.0
    eval_ratio: float = 0.1
    min_clip_seconds: float = 0.7
    max_clip_seconds: float = 30.0
    random_seed: int = 42
    include_local_archive: bool = True

    @classmethod
    def from_settings(cls) -> "CorpusBuildConfig":
        return cls(
            corpus_root=Path(settings.asr_corpus_dir),
            hf_token=settings.asr_hf_token,
            target_hours_per_bucket=settings.asr_target_hours_per_bucket,
            target_code_mixed_hours=settings.asr_target_code_mixed_hours,
            local_archive_hours_per_bucket=settings.asr_local_archive_hours_per_bucket,
            eval_ratio=settings.asr_eval_ratio,
            max_clip_seconds=settings.asr_max_clip_seconds,
            include_local_archive=True,
        )


@dataclass
class CorpusBuildResult:
    corpus_root: Path
    train_manifest: Path
    eval_manifest: Path
    stats_path: Path
    bucket_manifests: dict[str, dict[str, Path]]
    stats: dict[str, Any]


class CorpusBuilder:
    """Build a local multilingual ASR corpus from curated Hugging Face sources."""

    def __init__(self, config: CorpusBuildConfig):
        self.config = config
        self.random = random.Random(config.random_seed)
        self.corpus_root = config.corpus_root.expanduser().resolve()
        self.raw_root = self.corpus_root / "raw"
        self.generated_root = self.corpus_root / "generated"
        self.manifest_root = self.corpus_root / "manifests"
        self.hf_api = HfApi(token=config.hf_token or None)
        self._repo_files_cache: dict[tuple[str, str | None], list[str]] = {}
        self._source_targets = self._build_source_targets()

    def build(self) -> CorpusBuildResult:
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.generated_root.mkdir(parents=True, exist_ok=True)
        self.manifest_root.mkdir(parents=True, exist_ok=True)

        records: dict[str, dict[str, list[dict[str, Any]]]] = {
            "train": {bucket: [] for bucket in LANGUAGE_BUCKETS},
            "eval": {bucket: [] for bucket in LANGUAGE_BUCKETS},
        }
        hours: dict[str, dict[str, float]] = {
            "train": {bucket: 0.0 for bucket in LANGUAGE_BUCKETS},
            "eval": {bucket: 0.0 for bucket in LANGUAGE_BUCKETS},
        }
        weak_hours: dict[str, float] = {bucket: 0.0 for bucket in LANGUAGE_BUCKETS}
        source_counts: dict[str, int] = defaultdict(int)
        source_hours: dict[str, float] = defaultdict(float)
        skipped_sources: list[dict[str, str]] = []

        for source in CURATED_SOURCES:
            try:
                self._ingest_source(
                    source=source,
                    records=records,
                    hours=hours,
                    source_hours=source_hours,
                    source_counts=source_counts,
                )
            except Exception as exc:
                skipped_sources.append({"source": source.name, "reason": str(exc)})
                log.warning(f"Failed to ingest {source.name}: {exc}")

        if self.config.include_local_archive:
            self._ingest_local_archive(records, hours, weak_hours)

        self._synthesize_code_mixed(records, hours)

        train_manifest, eval_manifest, bucket_manifests = self._write_manifests(records)
        stats = {
            "targets": {
                "english_hours": self.config.target_hours_per_bucket,
                "hindi_hours": self.config.target_hours_per_bucket,
                "kannada_hours": self.config.target_hours_per_bucket,
                "code_mixed_hours": self.config.target_code_mixed_hours,
                "local_archive_hours_per_bucket": self.config.local_archive_hours_per_bucket,
            },
            "achieved_hours": hours,
            "local_archive_hours": weak_hours,
            "source_counts": dict(source_counts),
            "source_hours": dict(source_hours),
            "source_hour_targets": self._source_targets,
            "skipped_sources": skipped_sources,
            "bucket_manifests": {
                split: {bucket: str(path) for bucket, path in manifest_paths.items()}
                for split, manifest_paths in bucket_manifests.items()
            },
            "consolidated_manifests": {
                "train": str(train_manifest),
                "eval": str(eval_manifest),
            },
            "curated_sources": [asdict(source) for source in CURATED_SOURCES],
        }

        stats_path = self.manifest_root / "corpus_stats.json"
        with stats_path.open("w", encoding="utf-8") as handle:
            json.dump(stats, handle, ensure_ascii=False, indent=2)

        return CorpusBuildResult(
            corpus_root=self.corpus_root,
            train_manifest=train_manifest,
            eval_manifest=eval_manifest,
            stats_path=stats_path,
            bucket_manifests=bucket_manifests,
            stats=stats,
        )

    def _ingest_source(
        self,
        source: DatasetSource,
        records: dict[str, dict[str, list[dict[str, Any]]]],
        hours: dict[str, dict[str, float]],
        source_hours: dict[str, float],
        source_counts: dict[str, int],
    ) -> None:
        source_split = "eval" if source.role == "eval" else "train"
        source_target = self._source_targets.get(source.name, 0.0)
        if self._bucket_target_reached(source.expected_bucket, hours, split=source_split):
            return
        if source_target > 0.0 and source_hours[source.name] >= source_target:
            return

        log.info(
            f"Loading {source.repo_id} config={source.config or '-'} split={source.split} "
            f"for {source.expected_bucket}"
        )
        if source.requires_token and not self.config.hf_token:
            log.info(
                f"{source.name} is gated; relying on cached Hugging Face credentials if available"
            )
        dataset = self._load_source_dataset(source)

        for index, example in enumerate(dataset):
            record = self._standardize_record(source, example, index)
            if record is None:
                continue

            split = "eval" if source.role == "eval" else self._choose_split(record["sample_id"])
            if self._bucket_target_reached(record["bucket"], hours, split=split):
                continue

            duration_hours = float(record["duration_seconds"]) / 3600.0
            records[split][record["bucket"]].append(record)
            hours[split][record["bucket"]] += duration_hours
            source_hours[source.name] += duration_hours
            source_counts[source.name] += 1

            if self._bucket_target_reached(source.expected_bucket, hours, split=source_split):
                break
            if source_target > 0.0 and source_hours[source.name] >= source_target:
                break

    def _load_source_dataset(self, source: DatasetSource):
        if source.parquet_prefixes:
            parquet_files = self._resolve_parquet_files(source)
            if not parquet_files:
                raise ValueError(
                    f"No parquet files found for repo={source.repo_id} revision={source.revision}"
                )
            return load_dataset(
                "parquet",
                data_files={"train": parquet_files},
                split="train",
                streaming=True,
                token=self.config.hf_token or None,
            )

        return load_dataset(
            source.repo_id,
            source.config,
            split=source.split,
            streaming=True,
            token=self.config.hf_token or None,
        )

    def _resolve_parquet_files(self, source: DatasetSource) -> list[str]:
        cache_key = (source.repo_id, source.revision)
        if cache_key not in self._repo_files_cache:
            self._repo_files_cache[cache_key] = self.hf_api.list_repo_files(
                repo_id=source.repo_id,
                repo_type="dataset",
                revision=source.revision,
            )

        repo_files = self._repo_files_cache[cache_key]
        parquet_files: list[str] = []
        revision_suffix = f"@{source.revision}" if source.revision else ""
        for prefix in source.parquet_prefixes:
            matches = sorted(
                file_path
                for file_path in repo_files
                if file_path.startswith(prefix) and file_path.endswith(".parquet")
            )
            parquet_files.extend(
                f"hf://datasets/{source.repo_id}{revision_suffix}/{file_path}"
                for file_path in matches
            )

        return parquet_files

    def _standardize_record(
        self,
        source: DatasetSource,
        example: dict[str, Any],
        index: int,
    ) -> dict[str, Any] | None:
        text = self._extract_text(example, source.transcript_fields)
        if not text:
            return None

        audio_value = self._extract_audio(example, source.audio_fields)
        if audio_value is None:
            return None

        waveform, sample_rate = self._audio_to_tensor(audio_value)
        waveform = self._normalize_waveform(waveform, sample_rate)
        duration_seconds = float(waveform.shape[-1]) / 16000.0
        if duration_seconds < self.config.min_clip_seconds or duration_seconds > self.config.max_clip_seconds:
            return None

        sample_id = self._sample_id(source, index, text)
        languages = detect_scripts(text)
        languages.discard("unknown")
        dominant_language = get_dominant_language(text, languages.copy()) if languages else "en"
        bucket = self._bucket_for_text(text, dominant_language, source.expected_bucket)

        audio_output = self.raw_root / bucket / source.name / f"{sample_id}.wav"
        audio_output.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(audio_output), waveform.cpu(), 16000)

        return {
            "sample_id": sample_id,
            "audio_path": str(audio_output.resolve()),
            "text": text,
            "bucket": bucket,
            "languages": sorted(languages or {"en"}),
            "dominant_language": dominant_language,
            "is_code_mixed": bucket == "code_mixed",
            "duration_seconds": round(duration_seconds, 3),
            "source": f"{source.repo_id}:{source.config or 'default'}:{source.split}",
            "source_repo": source.repo_id,
            "source_config": source.config or "",
            "source_split": source.split,
            "supervision": "gold",
            "metadata": {"dataset_source": source.name},
        }

    def _ingest_local_archive(
        self,
        records: dict[str, dict[str, list[dict[str, Any]]]],
        hours: dict[str, dict[str, float]],
        weak_hours: dict[str, float],
    ) -> None:
        manifest_path = Path(settings.asr_archive_dir).expanduser() / "weak_supervision.jsonl"
        if not manifest_path.exists():
            return

        log.info(f"Including runtime speech archive from {manifest_path}")
        with manifest_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                record = json.loads(raw_line)
                bucket = str(record.get("bucket", "english"))
                if bucket not in LANGUAGE_BUCKETS:
                    continue

                if weak_hours[bucket] >= self.config.local_archive_hours_per_bucket:
                    continue

                audio_path = Path(str(record.get("audio_path", ""))).expanduser()
                if not audio_path.exists():
                    continue

                duration_seconds = float(record.get("duration_seconds") or 0.0)
                if not duration_seconds:
                    duration_seconds = self._duration_from_file(audio_path)
                    record["duration_seconds"] = duration_seconds

                if duration_seconds < self.config.min_clip_seconds:
                    continue

                weak_hours[bucket] += duration_seconds / 3600.0
                hours["train"][bucket] += duration_seconds / 3600.0
                records["train"][bucket].append(record)

    def _synthesize_code_mixed(
        self,
        records: dict[str, dict[str, list[dict[str, Any]]]],
        hours: dict[str, dict[str, float]],
    ) -> None:
        if hours["train"]["code_mixed"] >= self.config.target_code_mixed_hours:
            return

        english_records = [r for r in records["train"]["english"] if r.get("supervision") == "gold"]
        hindi_records = [r for r in records["train"]["hindi"] if r.get("supervision") == "gold"]
        kannada_records = [r for r in records["train"]["kannada"] if r.get("supervision") == "gold"]

        if not english_records or (not hindi_records and not kannada_records):
            return

        silence = torch.zeros(1, int(0.25 * 16000))
        pair_pools = [pool for pool in (hindi_records, kannada_records) if pool]
        max_attempts = max(500, len(english_records) * 3)

        for _ in range(max_attempts):
            if hours["train"]["code_mixed"] >= self.config.target_code_mixed_hours:
                break
            left_record = self.random.choice(english_records)
            right_record = self.random.choice(self.random.choice(pair_pools))

            left_audio, _ = torchaudio.load(left_record["audio_path"])
            right_audio, _ = torchaudio.load(right_record["audio_path"])
            left_audio = self._normalize_waveform(left_audio, 16000)
            right_audio = self._normalize_waveform(right_audio, 16000)

            total_duration = (left_audio.shape[-1] + right_audio.shape[-1] + silence.shape[-1]) / 16000.0
            if total_duration > self.config.max_clip_seconds:
                continue

            sample_id = f"synthetic_cm_{hashlib.sha1((left_record['sample_id'] + right_record['sample_id']).encode('utf-8')).hexdigest()[:16]}"
            output_path = self.generated_root / "code_mixed" / f"{sample_id}.wav"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            waveform = torch.cat([left_audio, silence, right_audio], dim=-1)
            torchaudio.save(str(output_path), waveform.cpu(), 16000)

            text = clean_transcript(f"{left_record['text']} {right_record['text']}")
            languages = detect_scripts(text)
            languages.discard("unknown")
            dominant_language = get_dominant_language(text, languages.copy()) if languages else "en"
            record = {
                "sample_id": sample_id,
                "audio_path": str(output_path.resolve()),
                "text": text,
                "bucket": "code_mixed",
                "languages": sorted(languages or {"en", "hi"}),
                "dominant_language": dominant_language,
                "is_code_mixed": True,
                "duration_seconds": round(total_duration, 3),
                "source": "synthetic_code_mixed",
                "source_repo": "synthetic",
                "source_config": "",
                "source_split": "train",
                "supervision": "synthetic",
                "metadata": {
                    "left_sample_id": left_record["sample_id"],
                    "right_sample_id": right_record["sample_id"],
                },
            }
            records["train"]["code_mixed"].append(record)
            hours["train"]["code_mixed"] += total_duration / 3600.0

    def _write_manifests(
        self,
        records: dict[str, dict[str, list[dict[str, Any]]]],
    ) -> tuple[Path, Path, dict[str, dict[str, Path]]]:
        bucket_manifests: dict[str, dict[str, Path]] = {"train": {}, "eval": {}}
        for split in ("train", "eval"):
            split_root = self.manifest_root / split
            split_root.mkdir(parents=True, exist_ok=True)
            for bucket in LANGUAGE_BUCKETS:
                manifest_path = split_root / f"{bucket}.jsonl"
                bucket_manifests[split][bucket] = manifest_path
                self._write_jsonl(manifest_path, records[split][bucket])

        train_manifest = self.manifest_root / "train_all.jsonl"
        eval_manifest = self.manifest_root / "eval_all.jsonl"
        self._write_jsonl(
            train_manifest,
            [record for bucket in LANGUAGE_BUCKETS for record in records["train"][bucket]],
        )
        self._write_jsonl(
            eval_manifest,
            [record for bucket in LANGUAGE_BUCKETS for record in records["eval"][bucket]],
        )
        return train_manifest, eval_manifest, bucket_manifests

    def _write_jsonl(self, path: Path, records: Iterable[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _bucket_target_reached(
        self,
        bucket: str,
        hours: dict[str, dict[str, float]],
        split: str = "train",
    ) -> bool:
        base_target = (
            self.config.target_code_mixed_hours
            if bucket == "code_mixed"
            else self.config.target_hours_per_bucket
        )
        target = base_target if split == "train" else max(base_target * self.config.eval_ratio, 0.001)
        return hours[split][bucket] >= target

    def _build_source_targets(self) -> dict[str, float]:
        targets: dict[str, float] = {}
        for split_name, role in (("train", "train"), ("eval", "eval")):
            for bucket in ("english", "hindi", "kannada"):
                bucket_sources = [
                    source
                    for source in CURATED_SOURCES
                    if source.expected_bucket == bucket and source.role == role
                ]
                if not bucket_sources:
                    continue
                base_target = (
                    self.config.target_hours_per_bucket
                    if split_name == "train"
                    else max(self.config.target_hours_per_bucket * self.config.eval_ratio, 0.001)
                )
                per_source_target = base_target / float(len(bucket_sources))
                for source in bucket_sources:
                    targets[source.name] = per_source_target
        return targets

    def _choose_split(self, sample_id: str) -> str:
        digest = hashlib.sha1(sample_id.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) / 0xFFFFFFFF
        return "eval" if bucket < self.config.eval_ratio else "train"

    def _sample_id(self, source: DatasetSource, index: int, text: str) -> str:
        digest = hashlib.sha1(
            f"{source.repo_id}|{source.config}|{source.split}|{index}|{text[:120]}".encode("utf-8")
        ).hexdigest()
        return f"{source.name}_{digest[:16]}"

    def _bucket_for_text(self, text: str, dominant_language: str, fallback_bucket: str) -> str:
        if is_code_mixed(text):
            return "code_mixed"
        return BUCKET_BY_LANGUAGE.get(dominant_language, fallback_bucket)

    def _extract_text(self, example: dict[str, Any], fields: tuple[str, ...]) -> str:
        for field in fields:
            value = example.get(field)
            if value is None:
                continue
            text = clean_transcript(str(value))
            if text:
                return text
        return ""

    def _extract_audio(self, example: dict[str, Any], fields: tuple[str, ...]) -> Any:
        for field in fields:
            if field in example and example[field] is not None:
                return example[field]
        return None

    def _audio_to_tensor(self, audio_value: Any) -> tuple[torch.Tensor, int]:
        if isinstance(audio_value, dict):
            if audio_value.get("array") is not None:
                waveform = torch.as_tensor(audio_value["array"]).float()
                if waveform.ndim == 1:
                    waveform = waveform.unsqueeze(0)
                elif waveform.ndim == 2 and waveform.shape[0] > waveform.shape[1]:
                    waveform = waveform.transpose(0, 1)
                return waveform, int(audio_value.get("sampling_rate", 16000))
            if audio_value.get("path"):
                return torchaudio.load(str(audio_value["path"]))

        if hasattr(audio_value, "get_all_samples"):
            samples = audio_value.get_all_samples()
            waveform = getattr(samples, "data", samples)
            waveform = torch.as_tensor(waveform).float()
            if waveform.ndim == 1:
                waveform = waveform.unsqueeze(0)
            return waveform, int(getattr(samples, "sample_rate", 16000))

        if isinstance(audio_value, (str, Path)):
            return torchaudio.load(str(audio_value))

        raise TypeError(f"Unsupported audio payload type: {type(audio_value)!r}")

    def _normalize_waveform(self, waveform: torch.Tensor, sample_rate: int) -> torch.Tensor:
        if waveform.ndim == 1:
            waveform = waveform.unsqueeze(0)
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
        waveform = waveform.clamp(min=-1.0, max=1.0)
        return waveform

    def _duration_from_file(self, audio_path: Path) -> float:
        metadata = torchaudio.info(str(audio_path))
        if not metadata.sample_rate:
            return 0.0
        return float(metadata.num_frames) / float(metadata.sample_rate)
