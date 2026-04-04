from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .config import settings
from .logger import get_logger

log = get_logger("train_asr")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build multilingual ASR corpora and fine-tune Whisper for NudiScribe."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build-corpus", help="Build a local multilingual ASR corpus.")
    _add_corpus_args(build_parser)

    train_parser = subparsers.add_parser("train", help="Fine-tune Whisper from existing manifests.")
    _add_training_args(train_parser)

    full_cycle_parser = subparsers.add_parser(
        "full-cycle",
        help="Build the corpus and immediately launch the fine-tuning run.",
    )
    _add_corpus_args(full_cycle_parser)
    _add_training_args(full_cycle_parser)

    return parser


def _add_corpus_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--corpus-dir", default=settings.asr_corpus_dir)
    parser.add_argument("--hf-token", default=settings.asr_hf_token)
    parser.add_argument("--target-hours", type=float, default=settings.asr_target_hours_per_bucket)
    parser.add_argument(
        "--code-mixed-hours",
        type=float,
        default=settings.asr_target_code_mixed_hours,
    )
    parser.add_argument(
        "--local-archive-hours",
        type=float,
        default=settings.asr_local_archive_hours_per_bucket,
    )
    parser.add_argument("--eval-ratio", type=float, default=settings.asr_eval_ratio)
    parser.add_argument(
        "--skip-local-archive",
        action="store_true",
        help="Ignore archived runtime speech when building the corpus.",
    )


def _add_training_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--train-manifest", default="")
    parser.add_argument("--eval-manifest", default="")
    parser.add_argument("--output-dir", default=settings.asr_checkpoint_dir)
    parser.add_argument("--base-model", default=settings.asr_base_model)
    parser.add_argument("--epochs", type=float, default=settings.asr_train_epochs)
    parser.add_argument("--learning-rate", type=float, default=settings.asr_train_learning_rate)
    parser.add_argument("--train-batch-size", type=int, default=settings.asr_train_batch_size)
    parser.add_argument("--eval-batch-size", type=int, default=settings.asr_eval_batch_size)
    parser.add_argument(
        "--gradient-accumulation-steps",
        type=int,
        default=settings.asr_gradient_accumulation_steps,
    )
    parser.add_argument("--logging-steps", type=int, default=settings.asr_logging_steps)
    parser.add_argument("--save-steps", type=int, default=settings.asr_save_steps)
    parser.add_argument("--eval-steps", type=int, default=settings.asr_eval_steps)
    parser.add_argument("--warmup-steps", type=int, default=settings.asr_warmup_steps)
    parser.add_argument(
        "--include-weak-supervision",
        action="store_true",
        help="Include runtime pseudo-labels captured from live product usage.",
    )
    parser.add_argument("--resume-from-checkpoint", default="")


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    from .training import (
        CorpusBuildConfig,
        CorpusBuilder,
        TrainingConfig,
        run_whisper_training,
    )

    corpus_result = None
    if args.command in {"build-corpus", "full-cycle"}:
        corpus_config = CorpusBuildConfig(
            corpus_root=Path(args.corpus_dir),
            hf_token=args.hf_token,
            target_hours_per_bucket=args.target_hours,
            target_code_mixed_hours=args.code_mixed_hours,
            local_archive_hours_per_bucket=args.local_archive_hours,
            eval_ratio=args.eval_ratio,
            max_clip_seconds=settings.asr_max_clip_seconds,
            include_local_archive=not args.skip_local_archive,
        )
        corpus_result = CorpusBuilder(corpus_config).build()
        log.info(f"Corpus built under {corpus_result.corpus_root}")
        print(json.dumps(corpus_result.stats, ensure_ascii=False, indent=2))

    if args.command == "build-corpus":
        return

    train_manifest = Path(args.train_manifest) if args.train_manifest else None
    eval_manifest = Path(args.eval_manifest) if args.eval_manifest else None
    if corpus_result is not None:
        train_manifest = corpus_result.train_manifest
        eval_manifest = corpus_result.eval_manifest

    if train_manifest is None or eval_manifest is None:
        parser.error("train and eval manifests are required unless you run full-cycle.")

    training_config = TrainingConfig(
        train_manifest=train_manifest,
        eval_manifest=eval_manifest,
        output_dir=Path(args.output_dir),
        base_model=args.base_model,
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        warmup_steps=args.warmup_steps,
        per_device_train_batch_size=args.train_batch_size,
        per_device_eval_batch_size=args.eval_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        eval_steps=args.eval_steps,
        max_duration_seconds=settings.asr_max_clip_seconds,
        include_weak_supervision=args.include_weak_supervision,
        resume_from_checkpoint=args.resume_from_checkpoint or None,
    )
    summary = run_whisper_training(training_config)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
    # Some dataset/audio decoder combinations trigger a Python finalization crash
    # after the work has already completed and outputs are written. Exit directly
    # once the CLI has finished successfully.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
