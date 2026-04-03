import asyncio
import json

import websockets


async def run():
    uri = "ws://localhost:8000/ws/tts/test"
    payload = {
        "type": "synthesize",
        "text": "Namaskara, this is a multilingual TTS integration test.",
        "language": "en",
        "segments": [
            "Namaskara, this is a multilingual TTS integration test.",
            "Mujhe help chahiye.",
        ],
    }

    async with websockets.connect(uri, max_size=8_000_000) as ws:
        await ws.send(json.dumps(payload))

        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            print(data["type"], {k: v for k, v in data.items() if k != "audio_b64"})

            if data["type"] in {"final", "error"}:
                break


if __name__ == "__main__":
    asyncio.run(run())
