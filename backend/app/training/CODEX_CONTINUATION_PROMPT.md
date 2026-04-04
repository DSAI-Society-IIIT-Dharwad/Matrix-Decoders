# Codex Continuation Prompt (Next Session)

Use the prompt below in the next Codex session.

---

You are continuing the NudiScribe ASR evaluation and retraining work.

Project root:

- `/home/raviteja/nudiscribe/NudiV2/nudiscribe`

Read these files first:

1. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/training/ASR_SESSION_WORKFLOW.md`
2. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/training/DATASETS.md`
3. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/training/dataset_sources.py`
4. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/training/whisper_trainer.py`
5. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/asr/whisper_asr.py`
6. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/asr/router.py`
7. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/app/runtime_validation.py`
8. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/CURRENT_PHASE_CHECKLIST.md`
9. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/BUILD_PLAN_ALIGNMENT.md`
10. `/home/raviteja/nudiscribe/NudiV2/nudiscribe/backend/.env`

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
- Live runtime currently stays on base Whisper by default.
- Fine-tuned checkpoint loading still works when explicitly enabled for comparison.
- The latest benchmark did not show a quality win for the current fine-tuned checkpoints.

Primary task for this session:

- Build or gather a better multilingual evaluation set with English, Hindi, Kannada, and code-mixed speech.
- Retrain or refine the Whisper fine-tuning setup until a checkpoint clearly beats base Whisper on transcription quality.
- Preserve existing router behavior for code-mixed handling and Indic fallback (`asr/router.py` + `indic_asr.py`).
- Do not switch the default runtime back to fine-tuned checkpoints unless the new benchmark clearly justifies it.

Execution constraints:

- Do not delete current corpus/checkpoints.
- Keep training defaults bounded for this machine.
- If you run long commands, verify CUDA and sample availability before starting.
- Avoid reverting unrelated user changes in the repo.

Definition of done:

1. There is a clearer multilingual evaluation set or benchmark than the current synthetic-only spot check.
2. A retrained checkpoint either beats base Whisper or is explicitly rejected again with evidence.
3. Clear short summary of:
   - files changed
   - whether the default runtime should remain base or switch to a checkpoint
   - how to force fallback if needed
   - validation commands run

---
