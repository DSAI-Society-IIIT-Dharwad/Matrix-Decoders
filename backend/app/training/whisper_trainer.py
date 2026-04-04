from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import evaluate
import torch
from datasets import Audio, Dataset, load_dataset
from transformers import (
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    WhisperForConditionalGeneration,
    WhisperProcessor,
)

from ..config import settings
from ..logger import get_logger

log = get_logger("training.whisper")

WHISPER_LANGUAGE_NAMES = {
    "english": "english",
    "hindi": "hindi",
    "kannada": "kannada",
    "en": "english",
    "hi": "hindi",
    "kn": "kannada",
}


@dataclass
class TrainingConfig:
    train_manifest: Path
    eval_manifest: Path
    output_dir: Path
    base_model: str = "openai/whisper-small"
    num_train_epochs: float = 3.0
    learning_rate: float = 1e-5
    warmup_steps: int = 250
    per_device_train_batch_size: int = 4
    per_device_eval_batch_size: int = 4
    gradient_accumulation_steps: int = 4
    logging_steps: int = 25
    save_steps: int = 500
    eval_steps: int = 500
    generation_max_length: int = 225
    max_duration_seconds: float = 30.0
    include_weak_supervision: bool = False
    resume_from_checkpoint: str | None = None

    @classmethod
    def from_settings(cls, train_manifest: Path, eval_manifest: Path, output_dir: Path) -> "TrainingConfig":
        return cls(
            train_manifest=train_manifest,
            eval_manifest=eval_manifest,
            output_dir=output_dir,
            base_model=settings.asr_base_model,
            num_train_epochs=settings.asr_train_epochs,
            learning_rate=settings.asr_train_learning_rate,
            warmup_steps=settings.asr_warmup_steps,
            per_device_train_batch_size=settings.asr_train_batch_size,
            per_device_eval_batch_size=settings.asr_eval_batch_size,
            gradient_accumulation_steps=settings.asr_gradient_accumulation_steps,
            logging_steps=settings.asr_logging_steps,
            save_steps=settings.asr_save_steps,
            eval_steps=settings.asr_eval_steps,
            max_duration_seconds=settings.asr_max_clip_seconds,
        )


@dataclass
class DataCollatorSpeechSeq2SeqWithPadding:
    processor: Any

    def __call__(self, features: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
        input_features = [{"input_features": feature["input_features"]} for feature in features]
        batch = self.processor.feature_extractor.pad(input_features, return_tensors="pt")

        label_features = [{"input_ids": feature["labels"]} for feature in features]
        labels_batch = self.processor.tokenizer.pad(label_features, return_tensors="pt")
        labels = labels_batch["input_ids"].masked_fill(labels_batch.attention_mask.ne(1), -100)

        bos_token_id = self.processor.tokenizer.bos_token_id
        if bos_token_id is not None and (labels[:, 0] == bos_token_id).all().item():
            labels = labels[:, 1:]

        batch["labels"] = labels
        return batch


def run_whisper_training(config: TrainingConfig) -> dict[str, Any]:
    processor = WhisperProcessor.from_pretrained(config.base_model, task="transcribe")
    model = WhisperForConditionalGeneration.from_pretrained(config.base_model)
    max_label_length = int(
        getattr(model.config, "max_target_positions", None)
        or getattr(model.generation_config, "max_length", None)
        or getattr(processor.tokenizer, "model_max_length", 448)
        or 448
    )
    if getattr(model, "generation_config", None) is not None:
        model.generation_config.forced_decoder_ids = None
        model.generation_config.suppress_tokens = []
    if hasattr(model.config, "forced_decoder_ids"):
        model.config.forced_decoder_ids = None
    if hasattr(model.config, "suppress_tokens"):
        model.config.suppress_tokens = None

    train_dataset = _load_manifest_dataset(
        config.train_manifest,
        processor=processor,
        include_weak_supervision=config.include_weak_supervision,
        max_duration_seconds=config.max_duration_seconds,
        max_label_length=max_label_length,
    )
    eval_dataset = _load_manifest_dataset(
        config.eval_manifest,
        processor=processor,
        include_weak_supervision=False,
        max_duration_seconds=config.max_duration_seconds,
        max_label_length=max_label_length,
    )

    if len(train_dataset) == 0:
        raise ValueError(f"No trainable samples found in {config.train_manifest}")

    data_collator = DataCollatorSpeechSeq2SeqWithPadding(processor=processor)
    wer_metric = evaluate.load("wer")
    cer_metric = evaluate.load("cer")

    def compute_metrics(pred):
        pred_ids = pred.predictions
        label_ids = pred.label_ids.copy()
        label_ids[label_ids == -100] = processor.tokenizer.pad_token_id

        pred_text = processor.tokenizer.batch_decode(pred_ids, skip_special_tokens=True)
        label_text = processor.tokenizer.batch_decode(label_ids, skip_special_tokens=True)
        return {
            "wer": round(100.0 * wer_metric.compute(predictions=pred_text, references=label_text), 3),
            "cer": round(100.0 * cer_metric.compute(predictions=pred_text, references=label_text), 3),
        }

    output_dir = config.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    evaluation_strategy = "steps" if len(eval_dataset) > 0 else "no"
    load_best_model = len(eval_dataset) > 0
    training_args = Seq2SeqTrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=config.per_device_train_batch_size,
        per_device_eval_batch_size=config.per_device_eval_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        learning_rate=config.learning_rate,
        warmup_steps=config.warmup_steps,
        num_train_epochs=config.num_train_epochs,
        logging_steps=config.logging_steps,
        save_steps=config.save_steps,
        eval_steps=config.eval_steps,
        eval_strategy=evaluation_strategy,
        save_strategy="steps",
        predict_with_generate=load_best_model,
        generation_max_length=config.generation_max_length,
        fp16=torch.cuda.is_available(),
        use_cpu=not torch.cuda.is_available(),
        gradient_checkpointing=True,
        load_best_model_at_end=load_best_model,
        metric_for_best_model="wer" if load_best_model else None,
        greater_is_better=False if load_best_model else None,
        remove_unused_columns=False,
        report_to=[],
        save_total_limit=3,
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset if len(eval_dataset) > 0 else None,
        data_collator=data_collator,
        processing_class=processor,
        compute_metrics=compute_metrics if len(eval_dataset) > 0 else None,
    )

    resume_from = config.resume_from_checkpoint or _latest_checkpoint(output_dir)
    train_result = trainer.train(resume_from_checkpoint=resume_from)
    trainer.save_model()
    processor.save_pretrained(output_dir)

    metrics = dict(train_result.metrics)
    if len(eval_dataset) > 0:
        metrics.update(trainer.evaluate())

    summary = {
        "base_model": config.base_model,
        "output_dir": str(output_dir),
        "train_manifest": str(config.train_manifest),
        "eval_manifest": str(config.eval_manifest),
        "train_samples": len(train_dataset),
        "eval_samples": len(eval_dataset),
        "resume_from_checkpoint": resume_from or "",
        "include_weak_supervision": config.include_weak_supervision,
        "metrics": metrics,
    }

    summary_path = output_dir / "training_summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    log.info(f"Finished Whisper training. Summary written to {summary_path}")
    return summary


def _load_manifest_dataset(
    manifest_path: Path,
    processor: WhisperProcessor,
    include_weak_supervision: bool,
    max_duration_seconds: float,
    max_label_length: int,
):
    manifest_path = manifest_path.expanduser().resolve()
    if not manifest_path.exists() or manifest_path.stat().st_size == 0:
        return Dataset.from_list([])

    dataset = load_dataset("json", data_files=str(manifest_path), split="train")

    if not include_weak_supervision:
        dataset = dataset.filter(lambda sample: sample.get("supervision") != "weak")

    dataset = dataset.filter(
        lambda sample: bool(sample.get("audio_path"))
        and Path(str(sample["audio_path"])).expanduser().exists()
        and float(sample.get("duration_seconds") or 0.0) <= max_duration_seconds
    )
    if len(dataset) == 0:
        return dataset

    def label_length_ok(sample):
        dominant_language = _whisper_language_name(
            sample.get("dominant_language") or sample.get("bucket") or "english"
        )
        processor.tokenizer.set_prefix_tokens(language=dominant_language, task="transcribe")
        return len(processor.tokenizer(str(sample.get("text") or "")).input_ids) <= max_label_length

    dataset = dataset.filter(label_length_ok)
    if len(dataset) == 0:
        return dataset

    dataset = dataset.map(lambda sample: {"audio": sample["audio_path"]})
    dataset = dataset.cast_column("audio", Audio(sampling_rate=16000))

    def prepare_sample(sample):
        audio = sample["audio"]
        dominant_language = _whisper_language_name(
            sample.get("dominant_language") or sample.get("bucket") or "english"
        )
        processor.tokenizer.set_prefix_tokens(language=dominant_language, task="transcribe")
        sample["input_features"] = processor.feature_extractor(
            audio["array"],
            sampling_rate=audio["sampling_rate"],
        ).input_features[0]
        sample["labels"] = processor.tokenizer(sample["text"]).input_ids
        return sample

    dataset = dataset.map(
        prepare_sample,
        remove_columns=dataset.column_names,
    )
    return dataset.filter(lambda sample: len(sample["labels"]) <= max_label_length)


def _latest_checkpoint(output_dir: Path) -> str | None:
    checkpoints = sorted(
        (
            path
            for path in output_dir.glob("checkpoint-*")
            if path.is_dir() and path.name.split("-")[-1].isdigit()
        ),
        key=lambda path: int(path.name.split("-")[-1]),
    )
    if not checkpoints:
        return None
    return str(checkpoints[-1])


def _whisper_language_name(value: str) -> str:
    return WHISPER_LANGUAGE_NAMES.get(str(value).lower(), "english")
