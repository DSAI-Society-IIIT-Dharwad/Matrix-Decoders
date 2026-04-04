# NudiScribe ASR Session Handoff and Workflow

Last updated: 2026-04-04 (Asia/Kolkata)

## 1) Objective Completed in This Session

Built a practical multilingual ASR training pipeline and executed a bounded real training run that:

- uses curated Hugging Face datasets for `english`, `hindi`, `kannada`
- builds a separate `code_mixed` bucket
- trains within feasible limits for an RTX 5050 Laptop GPU (8 GB VRAM)
- writes reusable corpus + checkpoint artifacts for future incremental training

## 2) What Was Implemented in Code

Core training entrypoint and modules:

- `backend/app/train_asr.py`
- `backend/app/training/corpus.py`
- `backend/app/training/whisper_trainer.py`
- `backend/app/training/archive.py`
- `backend/app/training/dataset_sources.py`
- `backend/app/training/DATASETS.md`
- `backend/app/training/__init__.py`

Runtime hooks for future weak-supervision archive:

- `backend/app/api.py` archives `/api/transcribe` and websocket audio transcripts when enabled.

Configuration and docs updates:

- `backend/app/config.py`
- `backend/requirements.txt`
- `.env.example`
- `README.md`

## 3) Important Fixes Applied During This Session

1. Corpus source balancing fix

- Problem: with low hour targets, early sources (for example Librispeech/FLEURS) satisfied bucket quotas before gated AI4Bharat sources were used.
- Fix: source-level hour targets were introduced in `corpus.py` so each curated source receives a bounded share.
- Result: final corpus includes all intended source families instead of only first-loaded sources.

2. Whisper label-length training crash fix

- Problem: training failed with `Labels' sequence length 499 cannot exceed ... 448`.
- Root cause: tokenizer max length is larger than Whisper decoder target length.
- Fix: `whisper_trainer.py` now uses model target limit (`max_target_positions` / generation max) and pre-filters overlength transcripts before feature extraction.
- Result: bounded training run completes successfully.

3. Build/training feasibility tuning for local GPU

- Local default limits were set in `backend/.env` to avoid huge jobs:
  - `ASR_BASE_MODEL=openai/whisper-base`
  - `ASR_TARGET_HOURS_PER_BUCKET=1.0`
  - `ASR_TARGET_CODE_MIXED_HOURS=0.5`
  - `ASR_TRAIN_EPOCHS=1.0`
  - batching/eval/save/log steps tuned for a short, stable run.

## 4) Environment and Access Verification Done

- CUDA detected in runtime environment:
  - GPU: `NVIDIA GeForce RTX 5050 Laptop GPU`
  - VRAM: `8151 MiB`
  - CUDA available from training venv: `True`

- Gated dataset access verified as working for:
  - `ai4bharat/Shrutilipi`
  - `ai4bharat/Kathbath`

Note:

- `ASR_HF_TOKEN` is still commented in `backend/.env`; current access worked due to existing Hugging Face cached login on this machine.
- For portability to a new machine, set `ASR_HF_TOKEN` explicitly.

## 5) Data and Training Artifacts Produced

Corpus root:

- `/home/raviteja/nudiscribe/asr_corpus`

Checkpoint root:

- `/home/raviteja/nudiscribe/asr_checkpoints`

Final corpus stats file:

- `/home/raviteja/nudiscribe/asr_corpus/manifests/corpus_stats.json`

Key corpus outcomes:

- Train bucket sizes:
  - english: 311
  - hindi: 503
  - kannada: 430
  - code_mixed: 104
- Eval bucket sizes:
  - english: 36
  - hindi: 36
  - kannada: 32
  - code_mixed: 1
- Source usage includes:
  - Librispeech
  - FLEURS
  - Shrutilipi (Hindi + Kannada)
  - Kathbath (Hindi + Kannada)

Final training summary:

- `/home/raviteja/nudiscribe/asr_checkpoints/training_summary.json`
- Base model: `openai/whisper-base`
- Train samples: `1344`
- Eval samples: `105`
- Metrics snapshot:
  - `train_runtime`: `167.0064`
  - `train_loss`: `4.5952`
  - `eval_loss`: `0.9538`
  - `eval_wer`: `96.335`
  - `eval_cer`: `64.175`

Saved checkpoints:

- `/home/raviteja/nudiscribe/asr_checkpoints/checkpoint-100`
- `/home/raviteja/nudiscribe/asr_checkpoints/checkpoint-168`
- Final merged model files also in `/home/raviteja/nudiscribe/asr_checkpoints`

## 6) Workflow to Reproduce / Continue

From repository root:

```bash
cd /home/raviteja/nudiscribe/NudiV2/nudiscribe/backend
```

Install dependencies (already done in this session, rerun if needed):

```bash
/home/raviteja/nudiscribe/venv/bin/pip install -r requirements.txt
```

Optional token check:

```bash
/home/raviteja/nudiscribe/venv/bin/python - <<'PY'
from huggingface_hub import HfApi
api = HfApi()
for repo in ("ai4bharat/Shrutilipi", "ai4bharat/Kathbath"):
    files = api.list_repo_files(repo_id=repo, repo_type="dataset", revision="refs/convert/parquet")
    print(repo, len(files))
PY
```

Build bounded corpus:

```bash
/home/raviteja/nudiscribe/venv/bin/python -m app.train_asr build-corpus \
  --corpus-dir /home/raviteja/nudiscribe/asr_corpus \
  --target-hours 1.0 \
  --code-mixed-hours 0.5 \
  --local-archive-hours 0.0 \
  --eval-ratio 0.1 \
  --skip-local-archive
```

Train bounded run:

```bash
/home/raviteja/nudiscribe/venv/bin/python -m app.train_asr train \
  --train-manifest /home/raviteja/nudiscribe/asr_corpus/manifests/train_all.jsonl \
  --eval-manifest /home/raviteja/nudiscribe/asr_corpus/manifests/eval_all.jsonl \
  --output-dir /home/raviteja/nudiscribe/asr_checkpoints \
  --base-model openai/whisper-base \
  --epochs 1 \
  --train-batch-size 2 \
  --eval-batch-size 2 \
  --gradient-accumulation-steps 4 \
  --logging-steps 10 \
  --save-steps 100 \
  --eval-steps 100 \
  --warmup-steps 20
```

Resume from latest checkpoint (if desired):

```bash
/home/raviteja/nudiscribe/venv/bin/python -m app.train_asr train \
  --train-manifest /home/raviteja/nudiscribe/asr_corpus/manifests/train_all.jsonl \
  --eval-manifest /home/raviteja/nudiscribe/asr_corpus/manifests/eval_all.jsonl \
  --output-dir /home/raviteja/nudiscribe/asr_checkpoints \
  --resume-from-checkpoint /home/raviteja/nudiscribe/asr_checkpoints/checkpoint-168
```

## 7) Cleanup Already Performed

Removed old smoke artifacts and stale runs:

- `/home/raviteja/nudiscribe/asr_corpus_smoke*`
- `/home/raviteja/nudiscribe/asr_checkpoints_smoke*`
- old oversized/stale `asr_corpus` and empty `asr_checkpoints` were replaced by the new bounded run outputs.

## 8) Current Runtime Status

Live API/runtime transcription can use the local fine-tuned Whisper checkpoint under `/home/raviteja/nudiscribe/asr_checkpoints`, but the selected default runtime is now the base Whisper model with `ASR_RUNTIME_PREFER_FINETUNED=false`.

Fallback behavior now in place:

- if `ASR_RUNTIME_PREFER_FINETUNED=true` and a valid fine-tuned checkpoint is present, `backend/app/asr/whisper_asr.py` loads it first
- if checkpoint loading fails, runtime falls back to the base Whisper model derived from `ASR_BASE_MODEL`
- the repository now keeps base-model Whisper selected by default with `ASR_RUNTIME_PREFER_FINETUNED=false`

Direct validation executed in this follow-up pass:

```bash
/home/raviteja/nudiscribe/venv/bin/python -m py_compile \
  /media/raviteja/Volume/nudiscribe/backend/app/asr/whisper_asr.py \
  /media/raviteja/Volume/nudiscribe/backend/app/asr/router.py \
  /media/raviteja/Volume/nudiscribe/backend/app/api.py \
  /media/raviteja/Volume/nudiscribe/backend/app/config.py

/home/raviteja/nudiscribe/venv/bin/python -c "import sys; sys.path.insert(0, '/media/raviteja/Volume/nudiscribe/backend'); from app.asr import whisper_asr; runtime = whisper_asr._load_runtime(); print({'kind': getattr(runtime, 'kind', 'unknown'), 'model_path': str(getattr(runtime, 'model_path', '')), 'model_name': getattr(runtime, 'model_name', '')})"

/home/raviteja/nudiscribe/venv/bin/python -c "import sys; sys.path.insert(0, '/media/raviteja/Volume/nudiscribe/backend'); from app.asr import whisper_asr; runtime = whisper_asr._build_runtime(force_base=True); print({'kind': getattr(runtime, 'kind', 'unknown'), 'model_name': getattr(runtime, 'model_name', '')})"

/home/raviteja/nudiscribe/venv/bin/python -c "import sys; sys.path.insert(0, '/media/raviteja/Volume/nudiscribe/backend'); from app.asr.whisper_asr import transcribe_with_language; text, lang = transcribe_with_language('/media/raviteja/Volume/nudiscribe/smoke_test_artifacts/tts_rest_output.wav'); print({'language': lang, 'text': text[:300]})"
```

Observed results:

- the opt-in fine-tuned runtime loaded as `fine_tuned` from `/home/raviteja/nudiscribe/asr_checkpoints`
- the explicit fallback path loaded as `fallback` with Whisper `base`
- direct transcription through both runtime paths returned non-empty English transcripts for the generated sample WAV

Benchmark summary used for the runtime decision:

- compared `base`, `finetuned_final`, `finetuned_ckpt168`, and `finetuned_ckpt100`
- on the known-text sample `smoke_test_artifacts/tts_rest_output.wav`, base Whisper produced the best output quality
- the fine-tuned checkpoints loaded slightly faster and were similar or slightly faster on short synthetic inference, but they did not beat base Whisper on transcript quality
- the offline training summary still reports weak eval quality (`eval_wer` `96.335`, `eval_cer` `64.175`), so the checkpoints do not yet justify becoming the default production path

Selected runtime decision:

- keep `ASR_RUNTIME_PREFER_FINETUNED=false` by default
- keep checkpoint loading support in code for controlled comparison and future retraining passes
- revisit the selection only after a stronger multilingual benchmark pass

## 9) Recommended Next Engineering Task

Collect a real multilingual evaluation set with English, Hindi, Kannada, and code-mixed speech, retrain with better supervision balance, and only then revisit whether any fine-tuned checkpoint should replace base Whisper as the default runtime.
