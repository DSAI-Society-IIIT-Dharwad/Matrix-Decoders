import argparse
import asyncio
import json
import select
import sys
import time
import wave
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import sounddevice as sd
import websockets

try:
    import termios
except ImportError:  # pragma: no cover - only relevant outside POSIX terminals
    termios = None


DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2
DEFAULT_DURATION_SECONDS = 5.0
DEFAULT_STREAM_CHUNK_SECONDS = 0.25
DEFAULT_WS_BASE_URL = "ws://localhost:8000"
DEFAULT_SESSION_ID = "test"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "smoke_test_artifacts"


def _build_audio_ws_url(base_url: str, session_id: str) -> str:
    return f"{base_url.rstrip('/')}/ws/audio/{session_id}"


def _progress_bar(elapsed_seconds: float, duration_seconds: float, width: int = 28) -> str:
    safe_duration = max(duration_seconds, 0.1)
    ratio = min(max(elapsed_seconds / safe_duration, 0.0), 1.0)
    filled = int(width * ratio)
    remaining = max(duration_seconds - elapsed_seconds, 0.0)
    bar = "#" * filled + "-" * (width - filled)
    return (
        f"Recording [{bar}] {remaining:04.1f}s left "
        "(press Enter or q to stop early)"
    )


@contextmanager
def _keypress_mode():
    if termios is None or not sys.stdin.isatty():
        yield False
        return

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    new_settings = termios.tcgetattr(fd)
    new_settings[3] &= ~(termios.ICANON | termios.ECHO)

    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, new_settings)
        yield True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _poll_stop_key(keypress_enabled: bool) -> bool:
    if not keypress_enabled:
        return False

    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return False

    char = sys.stdin.read(1)
    return char in {"\n", "\r"} or char.lower() == "q"


def _save_recording(
    audio_bytes: bytes,
    sample_rate: int,
    channels: int,
    sample_width: int,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"audio_test_capture_{timestamp}.wav"

    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_bytes)

    return output_path


def _prompt_save_or_discard() -> bool:
    while True:
        choice = input("Save captured audio? [s]ave/[d]iscard: ").strip().lower()
        if choice in {"s", "save", "y", "yes"}:
            return True
        if choice in {"d", "discard", "n", "no", ""}:
            return False
        print("Enter 's' to save or 'd' to discard.")


async def _send_audio_chunks(ws, audio_queue: asyncio.Queue[bytes | None]) -> None:
    while True:
        chunk = await audio_queue.get()
        if chunk is None:
            return
        await ws.send(chunk)


async def _record_and_stream(
    ws,
    duration_seconds: float,
    sample_rate: int,
    channels: int,
) -> bytes:
    loop = asyncio.get_running_loop()
    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    captured_chunks: list[bytes] = []
    input_statuses: list[str] = []
    block_size = max(int(sample_rate * DEFAULT_STREAM_CHUNK_SECONDS), 1)
    stop_reason = "time-limit"

    def audio_callback(indata, frames, time_info, status):
        del frames, time_info

        if status:
            input_statuses.append(str(status))

        chunk = indata.copy().tobytes()
        captured_chunks.append(chunk)

        try:
            loop.call_soon_threadsafe(audio_queue.put_nowait, chunk)
        except RuntimeError:
            pass

    sender_task = asyncio.create_task(_send_audio_chunks(ws, audio_queue))
    started_at = time.perf_counter()

    print(f"Starting live recording for up to {duration_seconds:.1f} seconds.")

    try:
        with _keypress_mode() as keypress_enabled:
            if not keypress_enabled:
                print("Early-stop key handling is unavailable in this terminal.")

            with sd.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
                blocksize=block_size,
                callback=audio_callback,
            ):
                while True:
                    elapsed = time.perf_counter() - started_at
                    if elapsed >= duration_seconds:
                        break
                    if _poll_stop_key(keypress_enabled):
                        stop_reason = "manual-stop"
                        break

                    print(
                        "\r" + _progress_bar(elapsed, duration_seconds),
                        end="",
                        flush=True,
                    )
                    await asyncio.sleep(0.05)
    finally:
        elapsed = min(time.perf_counter() - started_at, duration_seconds)
        print("\r" + _progress_bar(elapsed, duration_seconds), flush=True)
        await audio_queue.put(None)
        await sender_task

    print(f"Recording ended ({stop_reason}).")
    if input_statuses:
        print("Input warnings:")
        for warning in input_statuses:
            print(f"  - {warning}")

    return b"".join(captured_chunks)


async def _print_server_events(ws) -> None:
    while True:
        raw_message = await ws.recv()

        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            print(raw_message)
            continue

        event = {key: value for key, value in payload.items() if key != "audio_b64"}
        print(json.dumps(event, ensure_ascii=False))

        if payload.get("type") in {"final", "error", "audio_skipped"}:
            return


async def stream_audio(
    base_url: str,
    session_id: str,
    duration_seconds: float,
    sample_rate: int,
    channels: int,
    sample_width: int,
    output_dir: Path,
) -> None:
    uri = _build_audio_ws_url(base_url, session_id)

    async with websockets.connect(uri, max_size=8_000_000) as ws:
        await ws.send(
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

        print(await ws.recv())
        audio_bytes = await _record_and_stream(
            ws=ws,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            channels=channels,
        )

        if not audio_bytes:
            print("No audio frames were captured.")
        else:
            await ws.send("commit")
            await _print_server_events(ws)

        if audio_bytes and _prompt_save_or_discard():
            output_path = _save_recording(
                audio_bytes=audio_bytes,
                sample_rate=sample_rate,
                channels=channels,
                sample_width=sample_width,
                output_dir=output_dir,
            )
            print(f"Saved recording to {output_path}")
        else:
            print("Captured audio discarded.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record live audio, stream it to /ws/audio, and optionally save the capture."
    )
    parser.add_argument("--base-url", default=DEFAULT_WS_BASE_URL)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--channels", type=int, default=DEFAULT_CHANNELS)
    parser.add_argument("--sample-width", type=int, default=DEFAULT_SAMPLE_WIDTH)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    asyncio.run(
        stream_audio(
            base_url=args.base_url,
            session_id=args.session_id,
            duration_seconds=max(args.duration, 0.5),
            sample_rate=args.sample_rate,
            channels=args.channels,
            sample_width=args.sample_width,
            output_dir=Path(args.output_dir).expanduser(),
        )
    )


if __name__ == "__main__":
    main()
