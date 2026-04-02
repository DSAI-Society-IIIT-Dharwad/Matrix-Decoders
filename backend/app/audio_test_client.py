import asyncio
import json

import sounddevice as sd
import websockets

SAMPLERATE = 16000
DURATION = 5  # seconds
MAX_CHUNK_BYTES = SAMPLERATE * 2  # 1 second of 16-bit mono PCM
STREAM_CHUNK_SECONDS = 0.5


async def stream_audio():
    uri = "ws://localhost:8000/ws/audio/test"

    async with websockets.connect(uri) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "start",
                    "sample_rate": SAMPLERATE,
                    "channels": 1,
                    "sample_width": 2,
                    "encoding": "pcm_s16le",
                }
            )
        )
        print(await ws.recv())

        print("Recording...")

        recording = sd.rec(
            int(DURATION * SAMPLERATE),
            samplerate=SAMPLERATE,
            channels=1,
            dtype="int16",
        )

        sd.wait()

        print("Sending audio...")

        pcm_bytes = recording.tobytes()
        chunk_bytes = min(int(SAMPLERATE * STREAM_CHUNK_SECONDS) * 2, MAX_CHUNK_BYTES)

        for start in range(0, len(pcm_bytes), chunk_bytes):
            await ws.send(pcm_bytes[start:start + chunk_bytes])
            await asyncio.sleep(STREAM_CHUNK_SECONDS)

        await ws.send("commit")

        while True:
            msg = await ws.recv()
            print(msg)

            if "final" in msg:
                break


asyncio.run(stream_audio())
