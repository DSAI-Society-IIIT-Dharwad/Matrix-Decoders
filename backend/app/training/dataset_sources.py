from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TEXT_FIELDS = (
    "text",
    "sentence",
    "transcription",
    "raw_transcription",
    "normalized_text",
    "transcript",
    "verbatim",
)

DEFAULT_AUDIO_FIELDS = (
    "audio",
    "audio_filepath",
    "audio_path",
    "path",
    "file",
)


@dataclass(frozen=True)
class DatasetSource:
    name: str
    repo_id: str
    config: str | None
    split: str
    expected_bucket: str
    role: str = "train"
    revision: str | None = None
    parquet_prefixes: tuple[str, ...] = ()
    transcript_fields: tuple[str, ...] = DEFAULT_TEXT_FIELDS
    audio_fields: tuple[str, ...] = DEFAULT_AUDIO_FIELDS
    requires_token: bool = False
    notes: str = ""


CURATED_SOURCES: tuple[DatasetSource, ...] = (
    DatasetSource(
        name="librispeech_train_clean_100",
        repo_id="openslr/librispeech_asr",
        config=None,
        split="train.clean.100",
        expected_bucket="english",
        revision="main",
        parquet_prefixes=("all/train.clean.100/",),
        notes="Open English ASR source with direct parquet access on the Hub.",
    ),
    DatasetSource(
        name="librispeech_train_clean_360",
        repo_id="openslr/librispeech_asr",
        config=None,
        split="train.clean.360",
        expected_bucket="english",
        revision="main",
        parquet_prefixes=("all/train.clean.360/",),
        notes="Additional large open English ASR coverage.",
    ),
    DatasetSource(
        name="librispeech_train_other_500",
        repo_id="openslr/librispeech_asr",
        config=None,
        split="train.other.500",
        expected_bucket="english",
        revision="main",
        parquet_prefixes=("all/train.other.500/",),
        notes="Noisier English speech to broaden robustness.",
    ),
    DatasetSource(
        name="librispeech_test_clean",
        repo_id="openslr/librispeech_asr",
        config=None,
        split="test.clean",
        expected_bucket="english",
        role="eval",
        revision="main",
        parquet_prefixes=("all/test.clean/",),
    ),
    DatasetSource(
        name="fleurs_en_us_train",
        repo_id="google/fleurs",
        config="en_us",
        split="train",
        expected_bucket="english",
        revision="refs/convert/parquet",
        parquet_prefixes=("en_us/train/",),
    ),
    DatasetSource(
        name="fleurs_en_us_validation",
        repo_id="google/fleurs",
        config="en_us",
        split="validation",
        expected_bucket="english",
        role="eval",
        revision="refs/convert/parquet",
        parquet_prefixes=("en_us/validation/",),
    ),
    DatasetSource(
        name="fleurs_hi_in_train",
        repo_id="google/fleurs",
        config="hi_in",
        split="train",
        expected_bucket="hindi",
        revision="refs/convert/parquet",
        parquet_prefixes=("hi_in/train/",),
    ),
    DatasetSource(
        name="fleurs_hi_in_validation",
        repo_id="google/fleurs",
        config="hi_in",
        split="validation",
        expected_bucket="hindi",
        role="eval",
        revision="refs/convert/parquet",
        parquet_prefixes=("hi_in/validation/",),
    ),
    DatasetSource(
        name="fleurs_kn_in_train",
        repo_id="google/fleurs",
        config="kn_in",
        split="train",
        expected_bucket="kannada",
        revision="refs/convert/parquet",
        parquet_prefixes=("kn_in/train/",),
    ),
    DatasetSource(
        name="fleurs_kn_in_validation",
        repo_id="google/fleurs",
        config="kn_in",
        split="validation",
        expected_bucket="kannada",
        role="eval",
        revision="refs/convert/parquet",
        parquet_prefixes=("kn_in/validation/",),
    ),
    DatasetSource(
        name="shrutilipi_hindi_train",
        repo_id="ai4bharat/Shrutilipi",
        config="hindi",
        split="train",
        expected_bucket="hindi",
        revision="refs/convert/parquet",
        parquet_prefixes=("hindi/train/",),
        requires_token=True,
        notes="AI4Bharat Hindi ASR corpus with large speaker and utterance coverage.",
    ),
    DatasetSource(
        name="shrutilipi_kannada_train",
        repo_id="ai4bharat/Shrutilipi",
        config="kannada",
        split="train",
        expected_bucket="kannada",
        revision="refs/convert/parquet",
        parquet_prefixes=("kannada/train/",),
        requires_token=True,
        notes="AI4Bharat Kannada ASR corpus with large speaker and utterance coverage.",
    ),
    DatasetSource(
        name="kathbath_hindi_train",
        repo_id="ai4bharat/Kathbath",
        config="hindi",
        split="train",
        expected_bucket="hindi",
        revision="refs/convert/parquet",
        parquet_prefixes=("hindi/train/",),
        requires_token=True,
        notes="AI4Bharat Kathbath is gated on Hugging Face but materially improves Hindi coverage.",
    ),
    DatasetSource(
        name="kathbath_hindi_valid",
        repo_id="ai4bharat/Kathbath",
        config="hindi",
        split="valid",
        expected_bucket="hindi",
        role="eval",
        revision="refs/convert/parquet",
        parquet_prefixes=("hindi/valid/",),
        requires_token=True,
    ),
    DatasetSource(
        name="kathbath_kannada_train",
        repo_id="ai4bharat/Kathbath",
        config="kannada",
        split="train",
        expected_bucket="kannada",
        revision="refs/convert/parquet",
        parquet_prefixes=("kannada/train/",),
        requires_token=True,
        notes="AI4Bharat Kathbath is gated on Hugging Face but materially improves Kannada coverage.",
    ),
    DatasetSource(
        name="kathbath_kannada_valid",
        repo_id="ai4bharat/Kathbath",
        config="kannada",
        split="valid",
        expected_bucket="kannada",
        role="eval",
        revision="refs/convert/parquet",
        parquet_prefixes=("kannada/valid/",),
        requires_token=True,
    ),
)
