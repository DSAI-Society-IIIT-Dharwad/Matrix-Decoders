from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime_validation import collect_runtime_validation_report


DEFAULT_TEXT = "Namaskara, mujhe multilingual TTS validation chahiye."


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _print_result(result: CheckResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"[{status}] {result.name}: {result.detail}")


def _base_ws_url(http_base_url: str) -> str:
    base = http_base_url.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    return base


def _write_audio_file(output_dir: Path, filename: str, audio_b64: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    output_path.write_bytes(base64.b64decode(audio_b64))
    return output_path


def _print_report(report: dict[str, object]) -> None:
    print("Runtime Validation")
    print(f"Python: {report['python_version']}")
    print(f"Env files: {report['env_files']}")
    print(f"Settings: {report['settings_summary']}")
    print(f"Required packages: {report['required_packages']}")
    print(f"Optional packages: {report['optional_packages']}")
    if report["settings_summary"].get("enable_tts"):
        print("TTS providers:")
        for provider in report["tts_providers"]:
            print(
                "  "
                f"- {provider['name']} | available={provider['available']} "
                f"| configured={provider['configured_languages']} "
                f"| issues={provider['issues']}"
            )
    print("Issues:")
    for issue in report["issues"]:
        print(f"  - {issue['level']}: {issue['message']}")


def run_self_check(run_command_probes: bool) -> int:
    report = collect_runtime_validation_report(
        run_command_probes=run_command_probes
    ).as_dict()
    _print_report(report)
    return 1 if report["has_errors"] else 0


async def _run_rest_checks(
    base_url: str,
    text: str,
    output_dir: Path,
    audio_file: Optional[Path],
    timeout_seconds: float,
    allow_tone_fallback: bool,
) -> list[CheckResult]:
    try:
        import httpx
    except ImportError as exc:
        return [
            CheckResult(
                name="REST dependency",
                passed=False,
                detail=f"httpx is not installed in this interpreter: {exc}",
            )
        ]

    results: list[CheckResult] = []
    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    timeout = httpx.Timeout(timeout_seconds)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            root_response = await client.get(f"{base_url}/")
            root_ok = root_response.status_code == 200
            results.append(
                CheckResult(
                    name="GET /",
                    passed=root_ok,
                    detail=root_response.text[:200],
                )
            )
            health_response = await client.get(f"{base_url}/api/health")
            health_ok = health_response.status_code == 200
            results.append(
                CheckResult(
                    name="GET /api/health",
                    passed=health_ok,
                    detail=health_response.text[:300],
                )
            )

            chat_response = await client.post(
                f"{base_url}/api/chat",
                json={"session_id": session_id, "text": text},
            )
            chat_ok = chat_response.status_code == 200
            results.append(
                CheckResult(
                    name="POST /api/chat",
                    passed=chat_ok,
                    detail=chat_response.text[:300],
                )
            )

            tts_response = await client.post(
                f"{base_url}/api/tts",
                json={"text": text, "languages": ["en", "hi", "kn"]},
            )
            tts_ok = tts_response.status_code == 200
            tts_detail = tts_response.text[:300]
            if tts_ok:
                payload = tts_response.json()
                provider = str(payload.get("provider", "unknown"))
                if provider == "tone-fallback" and not allow_tone_fallback:
                    tts_ok = False
                    tts_detail = (
                        "REST TTS returned tone-fallback, but a real speech provider is required "
                        "for full Phase 5 validation."
                    )
                elif payload.get("audio_b64"):
                    output_path = _write_audio_file(
                        output_dir,
                        "tts_rest_output.wav",
                        payload["audio_b64"],
                    )
                    tts_detail = (
                        f"provider={provider} "
                        f"sample_rate={payload.get('sample_rate')} "
                        f"saved={output_path}"
                    )
            results.append(
                CheckResult(
                    name="POST /api/tts",
                    passed=tts_ok,
                    detail=tts_detail,
                )
            )

            if audio_file is not None:
                with audio_file.open("rb") as handle:
                    files = {
                        "file": (
                            audio_file.name,
                            handle.read(),
                            "audio/wav",
                        )
                    }
                transcribe_response = await client.post(
                    f"{base_url}/api/transcribe",
                    files=files,
                )
                results.append(
                    CheckResult(
                        name="POST /api/transcribe",
                        passed=transcribe_response.status_code == 200,
                        detail=transcribe_response.text[:300],
                    )
                )
    except Exception as exc:
        results.append(
            CheckResult(
                name="REST smoke tests",
                passed=False,
                detail=str(exc),
            )
        )

    return results


async def _run_text_ws_check(
    base_ws_url: str,
    text: str,
    timeout_seconds: float,
) -> CheckResult:
    try:
        import websockets
    except ImportError as exc:
        return CheckResult(
            name="Text WebSocket dependency",
            passed=False,
            detail=f"websockets is not installed in this interpreter: {exc}",
        )

    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    uri = f"{base_ws_url}/ws/{session_id}"
    received_final = False
    received_delta = False

    try:
        async with websockets.connect(uri, max_size=8_000_000) as websocket:
            await websocket.send(json.dumps({"type": "input", "text": text}))

            while True:
                raw_message = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
                payload = json.loads(raw_message)
                message_type = payload.get("type")
                if message_type == "stream_started":
                    continue
                if message_type == "stream_complete" and payload.get("status") not in {"ok", "started"}:
                    return CheckResult(
                        name="WebSocket /ws/{session_id}",
                        passed=False,
                        detail=f"stream_complete status={payload.get('status')}",
                    )
                if message_type == "delta":
                    received_delta = True
                if message_type == "final":
                    received_final = True
                    break
                if message_type == "error":
                    return CheckResult(
                        name="WebSocket /ws/{session_id}",
                        passed=False,
                        detail=payload.get("error", "Unknown text WebSocket error"),
                    )
    except Exception as exc:
        return CheckResult(
            name="WebSocket /ws/{session_id}",
            passed=False,
            detail=str(exc),
        )

    passed = received_delta and received_final
    return CheckResult(
        name="WebSocket /ws/{session_id}",
        passed=passed,
        detail=f"received_delta={received_delta} received_final={received_final}",
    )


async def _run_tts_ws_check(
    base_ws_url: str,
    text: str,
    output_dir: Path,
    timeout_seconds: float,
    allow_tone_fallback: bool,
) -> CheckResult:
    try:
        import websockets
    except ImportError as exc:
        return CheckResult(
            name="TTS WebSocket dependency",
            passed=False,
            detail=f"websockets is not installed in this interpreter: {exc}",
        )

    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    uri = f"{base_ws_url}/ws/tts/{session_id}"
    chunk_count = 0
    final_provider = "unknown"

    try:
        async with websockets.connect(uri, max_size=16_000_000) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "synthesize",
                        "text": text,
                        "languages": ["en", "hi", "kn"],
                        "segments": [text],
                    }
                )
            )

            while True:
                raw_message = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
                payload = json.loads(raw_message)
                message_type = payload.get("type")
                if message_type == "stream_started":
                    continue
                if message_type == "stream_complete" and payload.get("status") not in {"ok", "started"}:
                    return CheckResult(
                        name="WebSocket /ws/tts/{session_id}",
                        passed=False,
                        detail=f"stream_complete status={payload.get('status')}",
                    )

                if message_type == "audio_chunk":
                    chunk_count += 1
                elif message_type == "final":
                    final_provider = str(payload.get("provider", "unknown"))
                    if final_provider == "tone-fallback" and not allow_tone_fallback:
                        return CheckResult(
                            name="WebSocket /ws/tts/{session_id}",
                            passed=False,
                            detail=(
                                "TTS WebSocket returned tone-fallback, but a real speech provider "
                                "is required for full Phase 5 validation."
                            ),
                        )
                    if payload.get("audio_b64"):
                        output_path = _write_audio_file(
                            output_dir,
                            "tts_ws_output.wav",
                            payload["audio_b64"],
                        )
                        return CheckResult(
                            name="WebSocket /ws/tts/{session_id}",
                            passed=True,
                            detail=f"chunks={chunk_count} provider={final_provider} saved={output_path}",
                        )
                    return CheckResult(
                        name="WebSocket /ws/tts/{session_id}",
                        passed=True,
                        detail=f"chunks={chunk_count} provider={final_provider}",
                    )
                elif message_type == "error":
                    return CheckResult(
                        name="WebSocket /ws/tts/{session_id}",
                        passed=False,
                        detail=payload.get("error", "Unknown TTS WebSocket error"),
                    )
    except Exception as exc:
        return CheckResult(
            name="WebSocket /ws/tts/{session_id}",
            passed=False,
            detail=str(exc),
        )


async def _run_audio_ws_check(
    base_ws_url: str,
    audio_file: Path,
    timeout_seconds: float,
) -> CheckResult:
    try:
        import websockets
    except ImportError as exc:
        return CheckResult(
            name="Audio WebSocket dependency",
            passed=False,
            detail=f"websockets is not installed in this interpreter: {exc}",
        )

    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    uri = f"{base_ws_url}/ws/audio/{session_id}"

    try:
        with wave.open(str(audio_file), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            pcm_bytes = wav_file.readframes(wav_file.getnframes())

        if sample_width != 2:
            return CheckResult(
                name="WebSocket /ws/audio/{session_id}",
                passed=False,
                detail=(
                    "Only 16-bit PCM WAV is supported for audio WebSocket smoke tests, "
                    f"got sample_width={sample_width}"
                ),
            )

        frame_size = channels * sample_width
        chunk_bytes = max(sample_rate * frame_size // 2, frame_size)
        saw_transcription = False
        saw_final = False

        async with websockets.connect(uri, max_size=16_000_000) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "start",
                        "sample_rate": sample_rate,
                        "channels": channels,
                        "sample_width": sample_width,
                        "encoding": "pcm_s16le",
                    }
                )
            )

            for start in range(0, len(pcm_bytes), chunk_bytes):
                await websocket.send(pcm_bytes[start : start + chunk_bytes])

            await websocket.send("commit")

            while True:
                raw_message = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
                payload = json.loads(raw_message)
                message_type = payload.get("type")
                if message_type == "stream_started":
                    continue
                if message_type == "stream_complete" and payload.get("status") not in {"ok", "started"}:
                    return CheckResult(
                        name="WebSocket /ws/audio/{session_id}",
                        passed=False,
                        detail=f"stream_complete status={payload.get('status')}",
                    )
                if message_type == "transcription":
                    saw_transcription = True
                elif message_type == "final":
                    saw_final = True
                    break
                elif message_type == "error":
                    return CheckResult(
                        name="WebSocket /ws/audio/{session_id}",
                        passed=False,
                        detail=payload.get("error", "Unknown audio WebSocket error"),
                    )
    except Exception as exc:
        return CheckResult(
            name="WebSocket /ws/audio/{session_id}",
            passed=False,
            detail=str(exc),
        )

    return CheckResult(
        name="WebSocket /ws/audio/{session_id}",
        passed=saw_transcription and saw_final,
        detail=f"received_transcription={saw_transcription} received_final={saw_final}",
    )


async def run_live_smoke_test(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    output_dir = Path(args.output_dir).resolve()
    audio_file = Path(args.audio_file).resolve() if args.audio_file else None
    results: list[CheckResult] = []

    results.extend(
        await _run_rest_checks(
            base_url=base_url,
            text=args.text,
            output_dir=output_dir,
            audio_file=audio_file,
            timeout_seconds=args.timeout,
            allow_tone_fallback=args.allow_tone_fallback,
        )
    )
    results.append(
        await _run_text_ws_check(
            base_ws_url=_base_ws_url(base_url),
            text=args.text,
            timeout_seconds=args.timeout,
        )
    )
    results.append(
        await _run_tts_ws_check(
            base_ws_url=_base_ws_url(base_url),
            text=args.text,
            output_dir=output_dir,
            timeout_seconds=args.timeout,
            allow_tone_fallback=args.allow_tone_fallback,
        )
    )

    if audio_file is not None:
        results.append(
            await _run_audio_ws_check(
                base_ws_url=_base_ws_url(base_url),
                audio_file=audio_file,
                timeout_seconds=args.timeout,
            )
        )

    for result in results:
        _print_result(result)

    return 1 if any(not result.passed for result in results) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Static validation and live smoke tests for the current NuDiscribe backend."
    )
    parser.add_argument("--self-check", action="store_true", help="Run static runtime validation only.")
    parser.add_argument(
        "--run-command-probes",
        action="store_true",
        help="During self-check, probe the configured Indic-TTS python binary with a lightweight import test.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL for the running backend when executing live smoke tests.",
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help="Sample multilingual text used for chat and TTS checks.",
    )
    parser.add_argument(
        "--audio-file",
        default="",
        help="Optional WAV file used for transcription and audio WebSocket coverage.",
    )
    parser.add_argument(
        "--output-dir",
        default="smoke_test_artifacts",
        help="Directory where synthesized audio artifacts should be written.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Request timeout in seconds for live smoke tests.",
    )
    parser.add_argument(
        "--allow-tone-fallback",
        action="store_true",
        help="Treat tone-fallback as acceptable during live TTS checks.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_check:
        return run_self_check(run_command_probes=args.run_command_probes)
    return asyncio.run(run_live_smoke_test(args))


if __name__ == "__main__":
    raise SystemExit(main())
