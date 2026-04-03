"""
Test client for NuDiscribe text chat.

Examples of code-mixed inputs:
  - Hindi + English: "Mujhe help chahiye yaar"
  - Kannada + English: "Naanu help beku guru"
  - Hindi script + English: "मुझे help चाहिए"
  - Kannada script + English: "ನನಗೆ help ಬೇಕು"
  - Tri-lingual: "Hello, मुझे ನನಗೆ help चाहिए ಬೇಕು"
"""

import asyncio
import json

import websockets


CODE_MIXED_EXAMPLES = [
    ("Hindi + English", "Mujhe help chahiye yaar, can you explain machine learning?"),
    ("Kannada + English", "Naanu ondhu project maadtiddini, can you help me with Python?"),
    ("Hindi script + English", "मुझे Python सिखाओ, I want to learn coding"),
    ("Kannada script + English", "ನನಗೆ help ಬೇಕು, I need to understand AI"),
    ("Pure English", "Hello, how are you doing today?"),
    ("Mixed Kannada", "Hello, ನಾನು help ಮಾಡ್ತೀನಿ"),
]


async def test_single(uri: str, label: str, text: str):
    """Send a single message and print the response."""
    print(f"\n{'=' * 60}")
    print(f"Test: {label}")
    print(f"Input: {text}")
    print(f"{'=' * 60}")

    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "input", "text": text}))

        full_text = ""

        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(msg)

                if data["type"] == "language_info":
                    langs = data.get("languages", [])
                    mixed = data.get("is_code_mixed", False)
                    print(f"Languages: {langs} | Code-mixed: {mixed}")

                elif data["type"] == "delta":
                    full_text += data["text"]

                elif data["type"] == "final":
                    print(f"\nResponse:\n{full_text}")
                    final_langs = data.get("languages", [])
                    print(f"Response language: {data.get('language')} | All: {final_langs}")
                    break

                elif data["type"] == "error":
                    print(f"Error: {data.get('error')}")
                    break

        except asyncio.TimeoutError:
            print("Timeout waiting for response")
        except websockets.exceptions.ConnectionClosedOK:
            print("Connection closed normally")


async def run_all_tests():
    """Run all code-mixed test examples."""
    uri = "ws://localhost:8000/ws/test"

    print("NuDiscribe Code-Mixed Text Test Client")
    print("=" * 60)

    for label, text in CODE_MIXED_EXAMPLES:
        await test_single(uri, label, text)
        await asyncio.sleep(1)

    print(f"\n{'=' * 60}")
    print("All tests complete")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
