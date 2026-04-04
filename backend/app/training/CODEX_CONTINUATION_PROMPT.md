# Codex Continuation Prompt (Next Session)

Use the prompt below in the next Codex session.

---

You are continuing the NudiScribe ASR training and runtime-integration work.

Project root:

- `/home/raviteja/nudiscribe/NudiV2/nudiscribe`

Read these files first:

1. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/training/ASR_SESSION_WORKFLOW.md`
2. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/training/DATASETS.md`
3. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/training/dataset_sources.py`
4. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/training/corpus.py`
5. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/training/whisper_trainer.py`
6. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/asr/whisper_asr.py`
7. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/asr/router.py`
8. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/api.py`
9. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/.env`

Current artifact paths (already built):

- Corpus: `/home/raviteja/nudiscribe/asr_corpus`
- Checkpoints: `/home/raviteja/nudiscribe/asr_checkpoints`
- Corpus stats: `/home/raviteja/nudiscribe/asr_corpus/manifests/corpus_stats.json`
- Training summary: `/home/raviteja/nudiscribe/asr_checkpoints/training_summary.json`

Facts you must assume as true unless re-verified:

- Bounded multilingual corpus/training pipeline is working.
- Gated datasets (`Shrutilipi`, `Kathbath`) were successfully used on this machine.
- GPU is RTX 5050 Laptop (8 GB VRAM), CUDA available in training venv.
- Training completed with `openai/whisper-base` and saved checkpoints.
- Live API still uses hardcoded base Whisper in `backend/app/asr/whisper_asr.py`.

Primary task for this session:

- Wire live ASR runtime to use local fine-tuned checkpoint from `/home/raviteja/nudiscribe/asr_checkpoints` when available.
- Keep robust fallback to current `whisper-base` loading if local checkpoint load fails.
- Preserve existing router behavior for code-mixed handling and Indic fallback (`asr/router.py` + `indic_asr.py`).
- Do not break `/api/transcribe` and websocket audio flow.

Execution constraints:

- Do not delete current corpus/checkpoints.
- Keep training defaults bounded for this machine.
- If you run long commands, verify token/gated dataset access and CUDA before starting.
- Avoid reverting unrelated user changes in the repo.

Definition of done:

1. Runtime ASR loader can prefer fine-tuned local model.
2. API transcription path still works end-to-end.
3. Clear short summary of:
   - files changed
   - how model selection works now
   - how to force fallback if needed
   - validation commands run

---
