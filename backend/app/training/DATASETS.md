# ASR Dataset Inventory

This file lists the speech datasets used by the NudiScribe offline ASR corpus builder.

## Bucket Mapping

- `english`: native English speech
- `hindi`: native Hindi speech
- `kannada`: native Kannada speech
- `code_mixed`: naturally mixed transcripts when present, plus synthetic English+Hindi and English+Kannada stitched clips created by the corpus builder

## Curated Hugging Face Sources

- `mozilla-foundation/common_voice_17_0`
  - role: optional English source
  - URL: https://huggingface.co/datasets/mozilla-foundation/common_voice_17_0
  - note: currently not used by the automated loader because the present Hub layout is not directly consumable by the latest `datasets` runtime in this repo

- `google/fleurs`
  - configs used by the builder: `en_us`, `hi_in`, `kn_in`
  - role: multilingual English/Hindi/Kannada coverage through parquet-exported train/validation splits
  - URL: https://huggingface.co/datasets/google/fleurs

- `ai4bharat/Shrutilipi`
  - configs: `hindi`, `kannada`
  - role: large Hindi and Kannada ASR coverage
  - URL: https://huggingface.co/datasets/ai4bharat/Shrutilipi

- `ai4bharat/Kathbath`
  - configs: `hindi`, `kannada`
  - role: extra Hindi/Kannada train and eval coverage
  - URL: https://huggingface.co/datasets/ai4bharat/Kathbath
  - note: gated on Hugging Face; requires access approval

- `openslr/librispeech_asr`
  - splits used by the builder: `train.clean.100`, `train.clean.360`, `train.other.500`, `test.clean`
  - role: large open English ASR coverage through direct parquet files
  - URL: https://huggingface.co/datasets/openslr/librispeech_asr

## Local Continual-Learning Source

- `backend/data/asr_corpus/local_archive/weak_supervision.jsonl`
  - generated from live `/api/transcribe` uploads and `/ws/audio/{session_id}` traffic when `ASR_ARCHIVE_AUDIO_FOR_TRAINING=true`
  - marked as `weak` supervision so it is only used when you explicitly include it in training

## Notes

- The source-of-truth code registry is [dataset_sources.py](/media/raviteja/Volume/nudiscribe/backend/app/training/dataset_sources.py).
- The corpus builder writes normalized manifests under `backend/data/asr_corpus/manifests/`.
- Native code-mixed open datasets for exactly Kannada/Hindi/English conversational ASR remain thin, so the builder supplements them with synthetic stitched clips while keeping that supervision type labeled as `synthetic`.
