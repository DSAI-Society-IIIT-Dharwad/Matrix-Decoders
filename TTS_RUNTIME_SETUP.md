# TTS Runtime Setup

This guide fixes the exact TTS warnings currently coming from this workspace:

- `ai4bharat-indic: hi: missing asset files ...`
- `ai4bharat-indic: kn: missing env values ...`
- `piper: en: Piper voice file does not exist ...`
- `The configured Indic-TTS python binary could not import TTS ...`

It also covers the clean way to configure real speech output so the backend does not fall back to tone output during normal runtime.

## What The Backend Expects

The router priority is:

1. `ai4bharat-indic` for Hindi and Kannada when those assets are configured
2. `piper` when a Piper binary and voice are configured
3. `coqui` when a Coqui model name is configured and `TTS.api` imports cleanly
4. `tone-fallback` only if no real provider works

Important repo-specific rules:

- Edit `backend/.env`. That is the env file currently loaded by this workspace.
- Use absolute paths for all TTS asset variables.
- Do not keep required models under `/tmp`. Your current Piper path under `/tmp/nudiscribe_runtime/...` is gone, which is why the warning appears.
- If you do not want to use a provider, leave that provider's env vars blank instead of pointing them at fake placeholder paths.

## Recommended Setup

For this repo, the safest clean runtime is:

- `AI4Bharat Indic-TTS` for `hi` and `kn`
- `Piper` for `en`
- `Coqui` only as an optional fallback after you verify `from TTS.api import TTS` works in the same Python environment that runs the server

That avoids depending on the deleted `/tmp` runtime and keeps Hindi/Kannada on the provider this code prefers first.

## 1. Create Stable Asset Directories

Run these once:

```bash
mkdir -p /media/raviteja/Volume/nudiscribe/backend/data/tts/indic/hi
mkdir -p /media/raviteja/Volume/nudiscribe/backend/data/tts/indic/kn
mkdir -p /media/raviteja/Volume/nudiscribe/backend/data/tts/piper/voices
```

If your repo lives somewhere else, replace `/media/raviteja/Volume/nudiscribe` with your actual repo root.

## 2. Fix The Python Environment First

Install backend dependencies in the same interpreter that will run the server:

```bash
cd /media/raviteja/Volume/nudiscribe
python -m pip install -r backend/requirements.txt
```

If you want Coqui available, force a compatible reinstall in that same interpreter:

```bash
python -m pip install --upgrade --force-reinstall "coqui-tts==0.27.5" "transformers>=4.57,<5"
```

Verify the interpreter that will run the backend:

```bash
python -c "import sys; print(sys.executable)"
python -c "import TTS"
python -c "from TTS.api import TTS; print('Coqui import OK')"
```

If the last command fails, do not enable Coqui yet. Fix that interpreter first, or keep the `COQUI_*` variables blank.

## 3. Download AI4Bharat Hindi And Kannada Assets

Official sources:

- AI4Bharat Indic-TTS repo: <https://github.com/AI4Bharat/Indic-TTS>
- AI4Bharat checkpoint release: <https://github.com/AI4Bharat/Indic-TTS/releases/tag/v1-checkpoints-release>

Download the Hindi and Kannada checkpoints from the official AI4Bharat release page and extract them into:

- `/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/hi`
- `/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/kn`

For each language, you need four real files:

- the acoustic model `.pth`
- the acoustic model `config.json`
- the vocoder `.pth`
- the vocoder `config.json`

After extraction, inspect the real filenames:

```bash
find /media/raviteja/Volume/nudiscribe/backend/data/tts/indic/hi -type f | sort
find /media/raviteja/Volume/nudiscribe/backend/data/tts/indic/kn -type f | sort
```

Map those real files to:

- `INDIC_TTS_MODEL_HI`
- `INDIC_TTS_CONFIG_HI`
- `INDIC_TTS_VOCODER_HI`
- `INDIC_TTS_VOCODER_CONFIG_HI`
- `INDIC_TTS_MODEL_KN`
- `INDIC_TTS_CONFIG_KN`
- `INDIC_TTS_VOCODER_KN`
- `INDIC_TTS_VOCODER_CONFIG_KN`

The code does not care about the filenames themselves. It only cares that those env vars point at files that actually exist.

## 4. Configure Piper Properly

Official sources:

- Piper release binaries: <https://github.com/rhasspy/piper/releases/tag/2023.11.14-2>
- Piper voice list: <https://github.com/rhasspy/piper/blob/master/VOICES.md>

The current warning exists because `backend/.env` points at:

- `/tmp/nudiscribe_runtime/piper/piper/piper`
- `/tmp/nudiscribe_runtime/piper/voices/en_US-lessac-low.onnx`

Those files are not present anymore. Replace them with stable paths under the repo.

Example setup for the English `en_US-lessac-low` voice:

```bash
cd /media/raviteja/Volume/nudiscribe/backend/data/tts/piper
curl -fL https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz -o piper_linux_x86_64.tar.gz
tar -xzf piper_linux_x86_64.tar.gz
curl -fL https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/low/en_US-lessac-low.onnx?download=true -o voices/en_US-lessac-low.onnx
curl -fL https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/low/en_US-lessac-low.onnx.json?download=true -o voices/en_US-lessac-low.onnx.json
```

Then use:

- `PIPER_BINARY=/media/raviteja/Volume/nudiscribe/backend/data/tts/piper/piper/piper`
- `PIPER_VOICE_EN=/media/raviteja/Volume/nudiscribe/backend/data/tts/piper/voices/en_US-lessac-low.onnx`

`PIPER_VOICE_HI` and `PIPER_VOICE_KN` can stay blank if Hindi and Kannada are handled by AI4Bharat. If AI4Bharat fails, Piper will still use the English voice as a last-resort fallback.

## 5. Optional Coqui Fallback

Official sources:

- Coqui TTS docs: <https://docs.coqui.ai/en/latest/index.html>
- Coqui inference guide: <https://docs.coqui.ai/en/latest/inference.html>

Coqui in this repo is model-name based, not file-path based. The backend imports `TTS.api` directly, so the server interpreter itself must be able to run:

```bash
python -c "from TTS.api import TTS"
```

Use the same interpreter that will launch the backend. In this workspace, `/home/raviteja/nudiscribe/venv/bin/python` passes that import check.

If the import succeeds and you want a real English fallback, set:

```env
COQUI_MODEL_EN=tts_models/en/ljspeech/tacotron2-DDC
COQUI_MODEL_HI=
COQUI_MODEL_KN=
COQUI_SPEAKER=
```

That model is downloaded on first use and cached by Coqui. Leave `COQUI_*` blank only if you want to disable Coqui entirely or if the import check fails.

## 6. Replace The Broken TTS Block In `backend/.env`

Open [backend/.env](/media/raviteja/Volume/nudiscribe/backend/.env) and replace the current placeholder block with real values.

Use this template for the recommended `AI4Bharat + Piper` setup, with an optional Coqui English fallback:

```env
ENABLE_TTS=true
ENABLE_TTS_FALLBACK_TONE=true
TTS_SAMPLE_RATE=22050

INDIC_TTS_PYTHON_BIN=/absolute/path/to/python/that-can-import-TTS
INDIC_TTS_COMMAND_TEMPLATE=

INDIC_TTS_MODEL_HI=/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/hi/<real-hindi-model>.pth
INDIC_TTS_CONFIG_HI=/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/hi/<real-hindi-config>.json
INDIC_TTS_VOCODER_HI=/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/hi/<real-hindi-vocoder>.pth
INDIC_TTS_VOCODER_CONFIG_HI=/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/hi/<real-hindi-vocoder-config>.json

INDIC_TTS_MODEL_KN=/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/kn/<real-kannada-model>.pth
INDIC_TTS_CONFIG_KN=/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/kn/<real-kannada-config>.json
INDIC_TTS_VOCODER_KN=/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/kn/<real-kannada-vocoder>.pth
INDIC_TTS_VOCODER_CONFIG_KN=/media/raviteja/Volume/nudiscribe/backend/data/tts/indic/kn/<real-kannada-vocoder-config>.json

PIPER_BINARY=/media/raviteja/Volume/nudiscribe/backend/data/tts/piper/piper/piper
PIPER_VOICE_EN=/media/raviteja/Volume/nudiscribe/backend/data/tts/piper/voices/en_US-lessac-low.onnx
PIPER_VOICE_HI=
PIPER_VOICE_KN=

COQUI_MODEL_EN=tts_models/en/ljspeech/tacotron2-DDC
COQUI_MODEL_HI=
COQUI_MODEL_KN=
COQUI_SPEAKER=
```

If you do not want Coqui, clear the `COQUI_*` values. If you want `AI4Bharat + Coqui` instead of Piper, blank the `PIPER_*` values and keep `COQUI_MODEL_EN` set after the `from TTS.api import TTS` check passes.

## 7. Validate Before Starting The Server

From the repo root:

```bash
cd /media/raviteja/Volume/nudiscribe
python backend/app/product_smoke_test.py --self-check --run-command-probes
```

A clean real-speech setup should not show:

- missing AI4Bharat asset warnings
- missing Piper file warnings
- `Indic-TTS python binary could not import TTS`
- `No real speech TTS provider is available yet`

## 8. Start The Backend And Verify Runtime

Start the server:

```bash
cd /media/raviteja/Volume/nudiscribe/backend
python -m uvicorn app.main:app --reload
```

In another terminal, check health:

```bash
curl -s http://127.0.0.1:8000/api/health
```

What you want to see:

- `"tts_ready": true`
- `"tts_real_speech_ready": true`
- `tts_real_providers` includes at least one real provider such as `ai4bharat-indic`, `piper`, or `coqui`
- the `warnings` list does not contain the current placeholder-path messages

Then run the full smoke test without allowing tone fallback:

```bash
cd /media/raviteja/Volume/nudiscribe/backend
python app/product_smoke_test.py --base-url http://127.0.0.1:8000
```

If `POST /api/tts` or the TTS WebSocket still reports `tone-fallback`, the real provider setup is still incomplete.

## 9. Exact Fixes For The Current Workspace

Your current `backend/.env` needs these exact corrections:

- Replace `INDIC_TTS_PYTHON_BIN=/path/to/python/that-can-import-TTS` with the absolute path from `python -c "import sys; print(sys.executable)"`
- Replace every `/abs/path/to/...` Indic placeholder with real extracted Hindi and Kannada files
- Add the missing Kannada vocoder values:
  - `INDIC_TTS_VOCODER_KN`
  - `INDIC_TTS_VOCODER_CONFIG_KN`
- Stop pointing Piper at `/tmp/nudiscribe_runtime/...`
- Point `PIPER_BINARY` and `PIPER_VOICE_EN` at stable real files under `backend/data/tts/piper`
- Keep `COQUI_*` blank only if `python -c "from TTS.api import TTS"` fails or if you want to disable Coqui fallback

Once those changes are done and the self-check is clean, runtime TTS will use real providers instead of the synthetic tone fallback.
